"""
CLI Diagnostic Tool — inspect OCR text extraction on any panel image.

Usage:
    # Snap a fresh photo from the camera and analyze it
    python tools/test_ocr.py --snap

    # Test on a specific image
    python tools/test_ocr.py path/to/panel_image.jpg

    # Test without LCD auto-crop (run on raw full image)
    python tools/test_ocr.py path/to/panel_image.jpg --no-crop

    # Test the latest image in panel_inbox/
    python tools/test_ocr.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import cv2
from cv.roi_crop import crop_screen_region
from cv.ocr import read_screen_text, _get_rapid_engine
from cv.classify import classify_message
from cv.validate import extract_code, validate_code
from backend.db import init_db
from backend.location import resolve_location
from cv.event import DetectedEvent


def load_calibration():
    calib_path = _PROJECT_ROOT / "hardware" / "calibration.json"
    if not calib_path.exists():
        calib_path = _PROJECT_ROOT / "hardware" / "calibration.example.json"
    if calib_path.exists():
        with open(calib_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def capture_camera_frame(output_path: Path) -> bool:
    """Capture a live frame using libcamera-still or rpicam-still."""
    cam_tool = shutil.which("libcamera-still") or shutil.which("rpicam-still")
    if not cam_tool:
        print("❌ Error: Neither libcamera-still nor rpicam-still found on system.")
        return False

    cmd = [
        cam_tool,
        "--nopreview",
        "-t", "250",
        "--width", "1920",
        "--height", "1080",
        "-q", "80",
        "--denoise", "cdn_off",
        "-o", str(output_path),
    ]
    print(f"📸 Snapping picture with {Path(cam_tool).name}...")
    try:
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
        if res.returncode == 0 and output_path.exists():
            print(f"✅ Picture saved to {output_path}")
            return True
        else:
            err = res.stderr.decode(errors="replace").strip()
            print(f"❌ Camera capture failed (rc={res.returncode}): {err}")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Camera capture timed out (>10s).")
        return False
    except Exception as e:
        print(f"❌ Camera capture error: {e}")
        return False


def test_image(image_path: Path, no_crop: bool = False, rotate: int | None = None):
    if not image_path.exists():
        print(f"❌ Error: File not found: {image_path}")
        return

    print("=" * 68)
    print(f"  📸 Image: {image_path.name}")
    print(f"  📂 Path:  {image_path.resolve()}")
    print("=" * 68)

    img = cv2.imread(str(image_path))
    if img is None:
        print(f"❌ Error: Could not read image at {image_path}")
        return

    # Auto-rotate live camera image if mounted portrait (height > width or calibration rotation)
    calib = load_calibration()
    cam_rot = calib.get("camera", {}).get("rotation", 0)
    
    # If explicitly passed via CLI, use that; otherwise check calibration / aspect
    if rotate is not None:
        rot_deg = rotate
    elif image_path.name in ("live_cam.jpg", "current_cam.jpg") or "shm" in str(image_path):
        rot_deg = cam_rot if cam_rot in (90, 180, 270) else 90
    else:
        rot_deg = 0

    if rot_deg == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        print("  🔄 Auto-rotated 90° clockwise (camera portrait orientation)")
    elif rot_deg == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
        print("  🔄 Rotated 180°")
    elif rot_deg == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        print("  🔄 Rotated 270°")

    h, w = img.shape[:2]
    print(f"  Dimensions: {w} x {h} px")

    if no_crop:
        target = img
        print("  Crop:       [None] (running on full image)")
    else:
        target = crop_screen_region(img, calib.get("screen_roi", {}), skip_auto_detect=False)
        ch, cw = target.shape[:2]
        print(f"  Crop:       {cw} x {ch} px (LCD Screen ROI)")

    # Run RapidOCR engine directly to get raw line-by-line bounding boxes & confidences
    engine = _get_rapid_engine()
    t0 = time.time()
    raw_result, elapse_list = engine(target)
    ocr_time = time.time() - t0

    if not raw_result:
        print(f"\n⚠️  RapidOCR returned NO text detections. (Time: {ocr_time:.3f}s)")
        print("=" * 68)
        return

    det_t, cls_t, rec_t = elapse_list if elapse_list and len(elapse_list) == 3 else (0, 0, 0)
    print(f"\n⚡ RapidOCR Execution Time: {ocr_time:.3f}s")
    print(f"   Breakdown: Det={det_t:.3f}s | Cls={cls_t:.3f}s | Rec={rec_t:.3f}s")

    print("\n📝 Raw Text Lines Extracted ({} items):".format(len(raw_result)))
    print("-" * 68)
    lines = []
    for idx, item in enumerate(raw_result, 1):
        bbox, text, conf = item
        conf_float = float(conf)
        lines.append(text)
        print(f"  [{idx:02d}]  {conf_float*100:4.1f}% | {text}")
    print("-" * 68)

    full_text = " ".join(lines)
    print(f"\n📜 Combined Text:\n   \"{full_text}\"\n")

    # Run Pipeline Stages: Classify, Extract Device Code, Resolve Location
    msg_type = classify_message(full_text)
    code = extract_code(full_text)
    is_valid = validate_code(code) if code else False

    print("🔍 Analysis Results:")
    print(f"  • Message Type:     {msg_type.upper()}")
    print(f"  • Device Code:      {code or 'NONE'}")
    if code:
        status_icon = "✅" if is_valid else "⚠️"
        status_text = "Valid commissioned device" if is_valid else "Not in known devices"
        print(f"  • Known Whitelist:  {status_icon} {status_text}")

    if code and is_valid:
        dummy_event = DetectedEvent(
            device_code=code,
            message_type=msg_type,
            raw_text=full_text,
            confidence=0.95,
            frame_id=0,
        )
        resolved = resolve_location(dummy_event)
        if resolved:
            print(f"  • Location Name:    {resolved.location_name}")
            print(f"  • Zone:             {resolved.zone}")
            print(f"  • Device Type:      {resolved.device_type}")
            print(f"  • Contacts:         {', '.join(resolved.contacts)}")
    print("=" * 68 + "\n")


def main():
    init_db()
    parser = argparse.ArgumentParser(description="Test RapidOCR text extraction on panel images")
    parser.add_argument("image", nargs="?", default=None, help="Path to image file")
    parser.add_argument("--snap", action="store_true", help="Snap a live picture from the camera and test it")
    parser.add_argument("--no-crop", action="store_true", help="Do not crop LCD ROI, test on full image")
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=None, help="Rotate image before OCR (e.g. 90)")
    args = parser.parse_args()

    if args.snap:
        out_path = Path("/dev/shm/live_cam.jpg")
        if not out_path.parent.exists():
            out_path = Path("/tmp/live_cam.jpg")
        if capture_camera_frame(out_path):
            test_image(out_path, no_crop=args.no_crop, rotate=args.rotate)
        return

    if args.image:
        img_path = Path(args.image)
        if not img_path.exists() and "shm" in str(img_path):
            print("⚠️  Live image not in RAM. Snapping fresh picture from camera...")
            if capture_camera_frame(img_path):
                test_image(img_path, no_crop=args.no_crop, rotate=args.rotate)
            return
        test_image(img_path, no_crop=args.no_crop, rotate=args.rotate)
    else:
        # Check panel_inbox for latest image
        inbox = _PROJECT_ROOT / "panel_inbox"
        images = sorted(
            [p for p in inbox.glob("*.*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if images:
            print(f"Using latest inbox image: {images[0].name}")
            test_image(images[0], no_crop=args.no_crop, rotate=args.rotate)
        else:
            sample = _PROJECT_ROOT / "tests" / "real_panel.jpg"
            if sample.exists():
                print(f"Using sample image: {sample.name}")
                test_image(sample, no_crop=args.no_crop, rotate=args.rotate)
            else:
                print("Usage: python tools/test_ocr.py <path_to_image> or python tools/test_ocr.py --snap")


if __name__ == "__main__":
    main()
