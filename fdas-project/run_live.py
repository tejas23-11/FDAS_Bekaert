"""
FDAS Live Pipeline — process panel images and send real notifications.

Drop a panel image into panel_inbox/ (or pass --image path) and this
script will:
  1. Load and crop to the screen ROI
  2. Preprocess for OCR
  3. Run OCR (Tesseract) to extract text
  4. Classify the message type (fire / fault / supervisory / normal)
  5. Extract and validate the device code
  6. Log to DB, route, and send real SMS + voice call via SIM7600

Usage:
    # Process a single image
    python3 run_live.py --image tests/real_panel.jpg

    # Process all images in panel_inbox/
    python3 run_live.py

    # Watch panel_inbox/ for new images continuously
    python3 run_live.py --watch

    # Dry-run mode (print what would be sent, no real SMS/call)
    python3 run_live.py --image tests/real_panel.jpg --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2

from cv.roi_crop import crop_screen_region
from cv.classify import classify_message
from cv.validate import extract_code, validate_code
from cv.event import DetectedEvent
from backend.pipeline import handle_detected_event
from backend.db import init_db

# ── Constants ─────────────────────────────────────────────────────────
INBOX_DIR = Path("panel_inbox")
PROCESSED_DIR = INBOX_DIR / "processed"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}

SEP = "=" * 65


def _find_tesseract() -> str | None:
    """Search common install locations on Windows and Linux."""
    import subprocess as _sp
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    # Try bare name (on PATH)
    try:
        _sp.run(["tesseract", "--version"], capture_output=True, timeout=5)
        return "tesseract"
    except (FileNotFoundError, _sp.TimeoutExpired):
        pass
    return None


def load_calibration(path: str = "hardware/calibration.json") -> dict:
    """Load calibration config (screen ROI coordinates)."""
    calib_path = Path(path)
    if not calib_path.exists():
        calib_path = Path("hardware/calibration.example.json")
        print(f"  [!!] {path} not found, using {calib_path}")
    with open(calib_path) as f:
        return json.load(f)


def process_image(image_path: Path, calibration: dict, dry_run: bool = False) -> bool:
    """
    Run a single panel image through the complete live pipeline.
    Returns True if the image was processed and a notification was triggered.
    """
    print(f"\n{SEP}")
    print(f"  PROCESSING: {image_path}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {'DRY-RUN' if dry_run else 'LIVE — real SMS/calls'}")
    print(SEP)

    # ── Stage 1: Load image ──────────────────────────────────────────
    frame = cv2.imread(str(image_path))
    if frame is None:
        print(f"  [!!] Failed to load image: {image_path}")
        return False
    h, w = frame.shape[:2]
    print(f"  [OK] Loaded image: {w} x {h}")

    # ── Stage 2: ROI crop ────────────────────────────────────────────
    roi_cfg = calibration["screen_roi"]
    rx, ry = roi_cfg.get("x", 0), roi_cfg.get("y", 0)
    rw, rh = roi_cfg.get("width", 0), roi_cfg.get("height", 0)

    if rw == 0 or rh == 0:
        # No ROI configured — use full image
        roi = frame
        print(f"  [OK] ROI: full image (no crop configured)")
    else:
        roi = crop_screen_region(frame, roi_cfg)
        print(f"  [OK] ROI crop: ({rx},{ry}) {rw}x{rh}")

    # ── Stage 3+4: OCR (dual-attempt — colour ROI + preprocessed) ─────
    #
    # Strategy: try OCR on both the raw colour crop AND a preprocessed
    # (inverted binary) version, keep whichever produces more text.
    # This is the same approach that worked in diagnose_real_image.py.
    text = ""
    confidence = 0.0

    import subprocess
    import tempfile
    from PIL import Image as PILImage, ImageFilter, ImageOps

    # Find tesseract binary
    tesseract_cmd = _find_tesseract()
    if tesseract_cmd is None:
        print(f"  [!!] Tesseract not found! Install with: sudo apt install tesseract-ocr")
        return False
    print(f"  [OK] Tesseract: {tesseract_cmd}")

    # Convert OpenCV BGR frame to Pillow RGB for preprocessing
    roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
    pil_colour = PILImage.fromarray(roi_rgb)

    # Pillow-based preprocessing (works well with blue LCD screens)
    gray = ImageOps.grayscale(pil_colour)
    eq = ImageOps.equalize(gray)
    sharp = eq.filter(ImageFilter.SHARPEN)
    binary = sharp.point(lambda p: 255 if p > 128 else 0, '1').convert("L")
    pil_inverted = ImageOps.invert(binary)

    # Try OCR on both versions, keep the longer result
    for label, pil_img in [("colour ROI", pil_colour), ("inverted binary", pil_inverted)]:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
            pil_img.save(tmp_path)
        try:
            result = subprocess.run(
                [tesseract_cmd, tmp_path, "-", "--psm", "6", "-l", "eng"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=30,
            )
            candidate = result.stdout.strip()
            if candidate and len(candidate) > len(text):
                text = candidate
                print(f"  [OK] OCR ({label}): {len(text)} chars extracted")
        except Exception as e:
            print(f"  [!!] OCR ({label}): {e}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    if not text:
        print(f"  [!!] OCR returned empty text — cannot proceed")
        return False
    print(f"  [OK] Best OCR result: {len(text)} chars")
    print()
    print(f"  --- OCR TEXT ---")
    for i, line in enumerate(text.splitlines(), 1):
        print(f"    {i:2d}| {line}")
    print()

    # ── Stage 5: Classify ────────────────────────────────────────────
    message_type = classify_message(text)
    if message_type in ("normal", "unknown"):
        print(f"  [!!] Classified as '{message_type}' — no notification needed")
        return False
    print(f"  [OK] Classified: {message_type.upper()}")

    # Show matched keywords
    from cv.classify import _VOCABULARY
    text_lower = text.lower()
    for cat, kws in _VOCABULARY.items():
        hits = [kw for kw in kws if kw in text_lower]
        if hits:
            print(f"       matched keywords for '{cat}': {hits}")

    # ── Stage 6: Extract & validate device code ──────────────────────
    code = extract_code(text)
    if not code:
        print(f"  [!!] No device code pattern found in OCR text")
        return False

    valid = validate_code(code)
    if not valid:
        print(f"  [!!] Device code '{code}' not in known_devices.txt — dropping")
        return False
    print(f"  [OK] Device code: {code}")

    # ── Stage 7: Create event + route through backend ────────────────
    print()
    print(f"  --- BACKEND PIPELINE ---")
    event = DetectedEvent(
        device_code=code,
        message_type=message_type,
        raw_text=text,
        confidence=confidence,
        frame_id=0,
    )

    # skip_debounce=True because we're processing a single manually-dropped image
    handle_detected_event(event, dry_run=dry_run, skip_debounce=True)

    print()
    print(f"  {'DRY-RUN complete' if dry_run else 'LIVE notifications sent'}")
    print(SEP)
    return True


def process_inbox(calibration: dict, dry_run: bool = False) -> int:
    """Process all images in panel_inbox/. Returns count of images processed."""
    INBOX_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)

    images = sorted(
        p for p in INBOX_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not images:
        print(f"  No images found in {INBOX_DIR}/")
        return 0

    print(f"  Found {len(images)} image(s) in {INBOX_DIR}/")
    processed = 0

    for image_path in images:
        success = process_image(image_path, calibration, dry_run=dry_run)
        # Move to processed/ regardless of success (so it's not re-processed)
        dest = PROCESSED_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{image_path.name}"
        try:
            shutil.move(str(image_path), str(dest))
            print(f"  Moved to: {dest}")
        except Exception as e:
            print(f"  [!!] Could not move {image_path}: {e}")
        if success:
            processed += 1

    return processed


def watch_inbox(calibration: dict, dry_run: bool = False, poll_seconds: float = 2.0):
    """Continuously watch panel_inbox/ for new images."""
    INBOX_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)

    print(f"\n{SEP}")
    print(f"  WATCHING: {INBOX_DIR.resolve()}/")
    print(f"  Mode: {'DRY-RUN' if dry_run else 'LIVE — real SMS/calls'}")
    print(f"  Polling every {poll_seconds}s — press Ctrl+C to stop")
    print(SEP)

    try:
        while True:
            images = sorted(
                p for p in INBOX_DIR.iterdir()
                if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
            )
            for image_path in images:
                process_image(image_path, calibration, dry_run=dry_run)
                dest = PROCESSED_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{image_path.name}"
                try:
                    shutil.move(str(image_path), str(dest))
                    print(f"  Moved to: {dest}")
                except Exception as e:
                    print(f"  [!!] Could not move {image_path}: {e}")

            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print("\n  Stopped watching.")


def main():
    parser = argparse.ArgumentParser(
        description="FDAS Live Pipeline — process panel images and send notifications"
    )
    parser.add_argument(
        "--image", type=str, default=None,
        help="Path to a single panel image to process"
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Continuously watch panel_inbox/ for new images"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be sent without actually sending SMS/calls"
    )
    parser.add_argument(
        "--calibration", type=str, default="hardware/calibration.json",
        help="Path to calibration.json"
    )
    args = parser.parse_args()

    # Initialize database
    init_db()

    # Load calibration
    calibration = load_calibration(args.calibration)

    if args.image:
        # Single image mode
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"ERROR: image not found: {image_path}")
            sys.exit(1)
        success = process_image(image_path, calibration, dry_run=args.dry_run)
        sys.exit(0 if success else 1)

    elif args.watch:
        # Watch mode
        watch_inbox(calibration, dry_run=args.dry_run)

    else:
        # Process inbox once
        count = process_inbox(calibration, dry_run=args.dry_run)
        print(f"\n  Processed {count} image(s)")


if __name__ == "__main__":
    main()
