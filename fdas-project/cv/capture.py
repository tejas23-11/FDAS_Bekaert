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


def frame_source(source) -> Iterator[np.ndarray]:
    """
    Yields frames (BGR numpy arrays) from a camera index, video file, or a
    directory of images. This is the one place source-type branching
    happens, so everything downstream just deals with frames.
    """
    path = Path(str(source)) if not isinstance(source, int) else None

    if path is not None and path.is_dir():
        for image_path in sorted(path.glob("*.png")) + sorted(path.glob("*.jpg")):
            frame = cv2.imread(str(image_path))
            if frame is not None:
                yield frame
        return

    cap = cv2.VideoCapture(source)
    try:
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=0, help="Camera index, video path, or image folder")
    parser.add_argument("--calibration", default="hardware/calibration.json")
    parser.add_argument("--dry-run", action="store_true", help="Print events instead of forwarding to backend")
    args = parser.parse_args()

    calib_path = args.calibration
    if not Path(calib_path).exists():
        calib_path = "hardware/calibration.example.json"
        print(f"[warn] {args.calibration} not found, using {calib_path}")
    calibration = load_calibration(calib_path)

    source = args.source
    if isinstance(source, str) and source.isdigit():
        source = int(source)

    for event in run_pipeline(source, calibration):
        if args.dry_run:
            print(event)
        else:
            from backend.pipeline import handle_detected_event

            handle_detected_event(event)
