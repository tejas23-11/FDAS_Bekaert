"""
CLI Diagnostic Tool — inspect OCR text extraction on any panel image.

Usage:
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
        print("❌ Error: Could not read image with OpenCV")
        return

    h, w = img.shape[:2]
    print(f"  Original:   {w} x {h} px")

    calib = load_calibration()
    screen_roi = calib.get("screen_roi", {})

    # Auto-apply camera mounting rotation from calibration for camera captures, or user flag
    rot = rotate
    if rot is None and ("live_cam" in image_path.name or "fdas_live" in image_path.name):
        rot = calib.get("camera", {}).get("rotation", 0)

    if rot == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        print(f"  Rotation:   90° clockwise (per camera calibration)")
    elif rot == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
        print(f"  Rotation:   180°")
    elif rot == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        print(f"  Rotation:   270°")

    h, w = img.shape[:2]

    # ROI crop
    if no_crop:
        target = img
        print("  Crop:       [None] (running on full image)")
    else:
        target = crop_screen_region(img, screen_roi, skip_auto_detect=False)
        th, tw = target.shape[:2]
        print(f"  Crop:       {tw} x {th} px (LCD Screen ROI)")

    # Warm up / run RapidOCR
    engine = _get_rapid_engine()
    t0 = time.time()
    results, elapse = engine(target)
    ocr_time = time.time() - t0

    print(f"\n⚡ RapidOCR Execution Time: {ocr_time:.3f}s")
    if elapse:
        print(f"   Breakdown: Det={elapse[0]:.3f}s | Cls={elapse[1]:.3f}s | Rec={elapse[2]:.3f}s")

    if not results:
        print("\n⚠️  No text detected in this image.")
        return

    print(f"\n📝 Raw Text Lines Extracted ({len(results)} items):")
    print("-" * 68)
    all_texts = []
    for i, item in enumerate(results, 1):
        if isinstance(item, (list, tuple)) and len(item) >= 3:
            box, t, score = item[0], str(item[1]).strip(), float(item[2])
            all_texts.append(t)
            print(f"  [{i:02d}] {score*100:5.1f}% | {t}")
    print("-" * 68)

    full_text = " ".join(all_texts)
    print(f"\n📜 Combined Text:\n   \"{full_text}\"")

    # Classification & Code extraction
    msg_type = classify_message(full_text)
    code = extract_code(full_text)
    is_valid = validate_code(code)

    print("\n🔍 Analysis Results:")
    print(f"  • Message Type:     {msg_type.upper()}")
    print(f"  • Device Code:      {code or 'NONE'}")
    print(f"  • Known Whitelist:  {'✅ Valid commissioned device' if is_valid else '⚠️ Not in known devices'}")

    if code:
        dummy_event = DetectedEvent(
            device_code=code,
            message_type=msg_type,
            raw_text=full_text,
            confidence=0.9,
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
    parser.add_argument("--no-crop", action="store_true", help="Do not crop LCD ROI, test on full image")
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], default=None, help="Rotate image before OCR (e.g. 90)")
    args = parser.parse_args()

    if args.image:
        test_image(Path(args.image), no_crop=args.no_crop, rotate=args.rotate)
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
                print("Usage: python tools/test_ocr.py <path_to_image>")


if __name__ == "__main__":
    main()
