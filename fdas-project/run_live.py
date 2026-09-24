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
_SCRIPT_DIR = Path(__file__).resolve().parent
INBOX_DIR = _SCRIPT_DIR / "panel_inbox"
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


# ── PaddleOCR engine (singleton) ──────────────────────────────────────
_paddle_engine = None
_paddle_available = None  # None = not checked yet


def _is_arm_platform() -> bool:
    """Detect ARM architecture (Raspberry Pi, etc.)."""
    import platform
    machine = platform.machine().lower()
    return machine.startswith("aarch64") or machine.startswith("arm")


def _setup_arm_env():
    """Set environment variables that prevent PaddlePaddle segfaults on ARM.

    MKL-DNN and aggressive threading cause native C++ crashes on aarch64.
    These must be set BEFORE importing paddlepaddle / paddleocr.
    """
    import os
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_use_xdnn", "0")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")


def _get_paddle_engine():
    """Lazily create PaddleOCR engine (singleton, heavy to init).

    On ARM (Raspberry Pi) we apply environment workarounds and use the
    older, lighter .ocr() API with PP-OCRv3 — the heavy PP-OCRv6 .predict()
    models are known to segfault on aarch64.
    """
    global _paddle_engine, _paddle_available
    if _paddle_available is False:
        return None
    if _paddle_engine is not None:
        return _paddle_engine

    is_arm = _is_arm_platform()

    # ARM workaround: set env vars BEFORE importing paddleocr
    if is_arm:
        _setup_arm_env()
        print("  [OK] ARM platform detected — using PaddleOCR with ARM-safe settings")

    try:
        from paddleocr import PaddleOCR

        # Try modern PaddleOCR 3.x API first
        try:
            _paddle_engine = PaddleOCR(
                lang="en",
                device="cpu",
                enable_mkldnn=False,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except TypeError:
            # Fallback for older PaddleOCR v2.x
            _paddle_engine = PaddleOCR(
                use_angle_cls=False,
                lang="en",
                use_gpu=False,
                show_log=False,
            )
        _paddle_available = True
        return _paddle_engine
    except ImportError:
        _paddle_available = False
        return None
    except Exception as e:
        print(f"  [!!] PaddleOCR init failed: {e}")
        _paddle_available = False
        return None




def _ocr_paddle(image_path: Path, roi, calibration: dict) -> tuple[str, float]:
    """
    Run PaddleOCR on the image. Uses the FULL original image (PaddleOCR
    handles text detection internally and works better on full images).

    On ARM: uses the older .ocr() API (lighter PP-OCRv3 models).
    On x86: uses the newer .predict() API (PP-OCRv6 models).

    Returns (text, confidence). Raises if PaddleOCR is not available.
    """
    engine = _get_paddle_engine()
    if engine is None:
        raise RuntimeError("PaddleOCR not installed")

    all_texts = []
    all_scores = []

    if hasattr(engine, "predict"):
        # Modern PaddleOCR 3.x API (.predict)
        results = engine.predict(input=str(image_path))
        for result in results:
            rec_texts = result.get("rec_texts", []) if isinstance(result, dict) else getattr(result, "rec_texts", [])
            rec_scores = result.get("rec_scores", []) if isinstance(result, dict) else getattr(result, "rec_scores", [])
            for t, s in zip(rec_texts, rec_scores):
                t_clean = str(t).strip()
                if t_clean:
                    all_texts.append(t_clean)
                    all_scores.append(float(s))
    else:
        # Legacy PaddleOCR 2.x API (.ocr)
        results = engine.ocr(str(image_path), cls=False)
        if results:
            for line_group in results:
                if line_group is None:
                    continue
                for line in line_group:
                    if isinstance(line, (list, tuple)) and len(line) >= 2:
                        text_part = line[1]
                        if isinstance(text_part, (list, tuple)) and len(text_part) >= 2:
                            t_clean = str(text_part[0]).strip()
                            if t_clean:
                                all_texts.append(t_clean)
                                all_scores.append(float(text_part[1]))

    if not all_texts:
        return "", 0.0

    text = " ".join(all_texts)
    avg_confidence = sum(all_scores) / len(all_scores) if all_scores else 0.0
    return text, avg_confidence


def _ocr_tesseract(roi) -> tuple[str, float]:
    """
    Fallback OCR using Tesseract. Tries colour ROI + inverted binary,
    keeps whichever produces more text.
    
    Returns (text, confidence).
    """
    import subprocess
    import tempfile
    from PIL import Image as PILImage, ImageFilter, ImageOps

    tesseract_cmd = _find_tesseract()
    if tesseract_cmd is None:
        print(f"  [!!] Tesseract not found! Install with: sudo apt install tesseract-ocr")
        return "", 0.0
    print(f"  [OK] Tesseract: {tesseract_cmd}")

    # Convert OpenCV BGR to Pillow RGB
    roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
    pil_colour = PILImage.fromarray(roi_rgb)

    # Pillow-based preprocessing (works well with blue LCD screens)
    gray = ImageOps.grayscale(pil_colour)
    eq = ImageOps.equalize(gray)
    sharp = eq.filter(ImageFilter.SHARPEN)
    binary = sharp.point(lambda p: 255 if p > 128 else 0, '1').convert("L")
    pil_inverted = ImageOps.invert(binary)

    text = ""
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
                print(f"  [OK] Tesseract ({label}): {len(text)} chars extracted")
        except Exception as e:
            print(f"  [!!] Tesseract ({label}): {e}")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return text, 0.5  # Tesseract confidence is unreliable, use 0.5 as placeholder


def load_calibration(path: str | None = None) -> dict:
    """Load calibration config (screen ROI coordinates)."""
    if path is None:
        path = str(_SCRIPT_DIR / "hardware" / "calibration.json")
    calib_path = Path(path)
    if not calib_path.exists():
        calib_path = _SCRIPT_DIR / "hardware" / "calibration.example.json"
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

    # ── Stage 3+4: OCR (PaddleOCR primary, Tesseract fallback) ─────────
    #
    # PaddleOCR gives ~96% confidence on LCD panels vs ~23% for Tesseract.
    # We try PaddleOCR first; if not installed or fails, fall back to
    # the Tesseract dual-attempt approach.
    text = ""
    confidence = 0.0

    paddle_success = False
    try:
        text, confidence = _ocr_paddle(image_path, roi, calibration)
        if text:
            paddle_success = True
            print(f"  [OK] PaddleOCR: {len(text)} chars (confidence: {confidence:.3f})")
    except Exception as e:
        print(f"  [!!] PaddleOCR failed: {e}")

    if not paddle_success:
        print(f"  [..] Falling back to Tesseract...")
        text, confidence = _ocr_tesseract(roi)

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
    unknown_device = False

    if not code:
        print(f"  [!!] No device code pattern found in OCR text")
        if message_type == "fire":
            unknown_device = True
            print(f"  [!!] FIRE detected — sending unknown-device alert")
        else:
            return False

    if code and not validate_code(code):
        print(f"  [!!] Device code '{code}' not in known_devices.txt")
        if message_type == "fire":
            unknown_device = True
            print(f"  [!!] FIRE detected — sending unknown-device alert")
        else:
            return False

    if not unknown_device:
        print(f"  [OK] Device code: {code}")

    # ── Stage 7: Create event + route through backend ────────────────
    print()
    print(f"  --- BACKEND PIPELINE ---")

    if unknown_device:
        # Fire detected but device is unknown — send a generic alert SMS
        from notify.sms_gateway import send_sms
        from backend.db import get_connection

        contacts = ["+1234567890", "+0987654321"]  # TODO: replace with real contacts
        unknown_msg = "FIRE detected but at unknown device. Please check the FDAS panel immediately."

        for contact in contacts:
            send_sms(contact, unknown_msg, dry_run=dry_run)

        # Log to DB as an unknown-device fire event
        conn = get_connection()
        conn.execute(
            "INSERT INTO events (device_code, message_type, raw_text, detected_at, confidence, location_name, sms_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("UNKNOWN", message_type, text, datetime.now(timezone.utc).isoformat(), confidence, "Unknown device", "sent"),
        )
        conn.commit()
        conn.close()
        print(f"  [OK] Unknown-device fire event logged to DB")

        print()
        print(f"  {'DRY-RUN complete' if dry_run else 'LIVE notifications sent'}")
        print(SEP)
        return True

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
        help="Path to calibration.json (default: hardware/calibration.json relative to script)"
    )
    args = parser.parse_args()

    # Initialize database
    init_db()

    # Load calibration
    calibration = load_calibration(args.calibration if args.calibration != "hardware/calibration.json" else None)

    if args.image:
        # Single image mode
        image_path = Path(args.image)
        if not image_path.exists():
            # Try relative to the script's own directory as fallback
            alt_path = _SCRIPT_DIR / args.image
            if alt_path.exists():
                image_path = alt_path
            else:
                print(f"ERROR: image not found: {image_path}")
                print(f"       (also checked: {alt_path})")
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
