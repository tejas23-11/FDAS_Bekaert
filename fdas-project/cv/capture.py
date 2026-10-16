"""
Frame acquisition plus orchestration of the full detection pipeline:
change detection -> full-screen OCR -> classify -> extract code -> validate.

Owner: Member 2 (CV / OCR Engineer)

Works against three kinds of source, so the whole team can develop and
test without needing the real camera hardware:
  - an integer camera index (real Raspberry Pi HQ camera / USB webcam)
  - a video file path (.mp4 etc.)
  - a directory of ordered image frames (the synthetic test rig -- see
    tests/generate_test_footage.py)

Run against the synthetic test rig:
    python3 -m cv.capture --source tests/sample_footage/fire --dry-run
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Iterator
# pyrefly: ignore [missing-import]
import cv2
import numpy as np

from cv.event import DetectedEvent
from cv.change_detect import screen_changed
from cv.roi_crop import crop_screen_region
from cv.preprocess import preprocess_for_ocr
from cv.ocr import read_screen_text
from cv.classify import classify_message
from cv.validate import extract_code, validate_code

HEARTBEAT_FILE = Path("/tmp/fdas_heartbeat")


def load_calibration(path: str = "hardware/calibration.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _arducam_frame_source() -> Iterator[np.ndarray]:
    """
    Captures frames directly from Arducam / libcamera using in-memory RAM (/dev/shm).
    Stores temporary frames in RAM (tmpfs) to prevent SD card wear during
    24/7 continuous operation.
    """
    import subprocess

    shm_path = Path("/dev/shm/fdas_live.jpg")
    cmd = [
        "libcamera-still",
        "--nopreview",
        "-t", "500",
        "--width", "1920",
        "--height", "1080",
        "-q", "90",
        "-o", str(shm_path),
    ]

    print("  [capture] Starting Arducam / libcamera continuous capture via RAM buffer...")
    while True:
        try:
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
            if res.returncode == 0 and shm_path.exists():
                frame = cv2.imread(str(shm_path))
                if frame is not None:
                    yield frame
            time.sleep(1.0)
        except Exception as e:
            print(f"  [capture] Frame capture retry: {e}")
            time.sleep(2.0)


def frame_source(source) -> Iterator[np.ndarray]:
    """
    Yields frames (BGR numpy arrays) from a camera index, video file,
    directory of images, or Arducam / libcamera ribbon camera.
    """
    # Direct Arducam / libcamera request
    if str(source).lower() in ("arducam", "libcamera", "rpicam"):
        yield from _arducam_frame_source()
        return

    path = Path(str(source)) if not isinstance(source, int) else None

    if path is not None and path.is_dir():
        for image_path in sorted(path.glob("*.png")) + sorted(path.glob("*.jpg")):
            frame = cv2.imread(str(image_path))
            if frame is not None:
                yield frame
        return

    cap = cv2.VideoCapture(source)
    try:
        ok, frame = cap.read()
        if not ok:
            # If standard OpenCV V4L2 camera fails, on Pi it's an Arducam CSI ribbon camera!
            print("  [capture] V4L2 camera 0 not accessible — switching to Arducam (libcamera)...")
            cap.release()
            yield from _arducam_frame_source()
            return

        yield frame
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            yield frame
    finally:
        cap.release()


def is_black_or_overexposed(frame: np.ndarray, low: float = 5.0, high: float = 250.0) -> bool:
    mean = frame.mean()
    return mean < low or mean > high


def _touch_heartbeat():
    """Lets the watchdog (step 13) know this process is alive each cycle."""
    HEARTBEAT_FILE.touch()


def run_pipeline(source, calibration: dict, heartbeat: bool = True):
    """
    Frame acquisition through validated code extraction, end to end.
    Yields a DetectedEvent for every frame where the screen changed, was
    read and classified, and produced a validated device code.

    Unlike the old LED-gated design, "normal"/idle messages are NOT
    trigger-worthy on their own but a transition INTO fire/fault/
    supervisory always is -- change detection just decides whether to
    bother reading the screen at all, classification decides what to do
    with what was read.
    """
    previous_frame = None
    frame_id = 0

    for frame in frame_source(source):
        frame_id += 1
        if heartbeat:
            _touch_heartbeat()

        if is_black_or_overexposed(frame):
            continue

        if not screen_changed(frame, previous_frame, calibration["screen_roi"]):
            previous_frame = frame
            continue
        previous_frame = frame

        roi = crop_screen_region(frame, calibration["screen_roi"])
        clean = preprocess_for_ocr(roi)
        text, confidence = read_screen_text(clean)

        message_type = classify_message(text)
        if message_type in ("normal", "unknown"):
            # Nothing actionable -- still worth this being visible for
            # debugging, but not an event to push downstream.
            continue

        code = extract_code(text)
        if not validate_code(code):
            # A real message type was detected but we couldn't pin down a
            # valid device code -- don't drop this silently in production;
            # TODO(Member 2/6): decide whether this should still notify
            # with "unknown device" rather than being dropped entirely,
            # since a fire message with an unreadable code is still a fire.
            continue

        yield DetectedEvent(
            device_code=code,
            message_type=message_type,
            raw_text=text,
            confidence=confidence,
            frame_id=frame_id,
        )

        if isinstance(source, int):
            time.sleep(1.0 / calibration["camera"].get("capture_fps", 1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FDAS Camera Pipeline — live or test")
    parser.add_argument("--source", default=0, help="Camera index, video path, or image folder")
    parser.add_argument("--calibration", default="hardware/calibration.json")
    parser.add_argument("--dry-run", action="store_true", help="Print events instead of sending real SMS/calls")
    args = parser.parse_args()

    calib_path = args.calibration
    if not Path(calib_path).exists():
        calib_path = "hardware/calibration.example.json"
        print(f"[warn] {args.calibration} not found, using {calib_path}")
    calibration = load_calibration(calib_path)

    source = args.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    # Initialize the database before processing events
    from backend.db import init_db
    init_db()

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    src_label = f"camera {source}" if isinstance(source, int) else source
    print(f"[FDAS] Starting pipeline — source: {src_label}, mode: {mode}")
    print(f"[FDAS] Calibration: {calib_path}")
    if isinstance(source, int):
        print(f"[FDAS] Camera FPS: {calibration['camera'].get('capture_fps', 1)}")
    print(f"[FDAS] Press Ctrl+C to stop\n")

    event_count = 0
    try:
        for event in run_pipeline(source, calibration):
            event_count += 1
            print(f"\n{'='*60}")
            print(f"  EVENT #{event_count}")
            print(f"  Device: {event.device_code}")
            print(f"  Type:   {event.message_type.upper()}")
            print(f"  Conf:   {event.confidence:.3f}")
            print(f"  Frame:  {event.frame_id}")
            print(f"  Text:   {event.raw_text[:100]}...")
            print(f"{'='*60}")

            if args.dry_run:
                print(f"  [DRY-RUN] Would route to backend pipeline")
                from backend.pipeline import handle_detected_event
                handle_detected_event(event, dry_run=True)
            else:
                from backend.pipeline import handle_detected_event
                handle_detected_event(event, dry_run=False)
    except KeyboardInterrupt:
        print(f"\n[FDAS] Stopped. Total events detected: {event_count}")

