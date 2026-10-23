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
import logging
import os
import platform
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── ARM (Raspberry Pi) segfault prevention ────────────────────────────
# PaddlePaddle's C++ core reads these at MODULE LOAD TIME.
# They MUST be set BEFORE any import that could pull in paddle.
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
_machine = platform.machine().lower()
if _machine.startswith("aarch64") or _machine.startswith("arm"):
    os.environ["FLAGS_use_mkldnn"] = "0"
    os.environ["FLAGS_use_xdnn"] = "0"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"

# Silence all third-party debug and info loggers (ppocr, paddlex, urllib3, etc.)
logging.disable(logging.INFO)
os.environ["GLOG_minloglevel"] = "3"

import cv2

from cv.roi_crop import crop_screen_region
from cv.classify import classify_message
from cv.validate import extract_code, validate_code
from cv.event import DetectedEvent
from backend.pipeline import handle_detected_event
from backend.db import init_db

import re

# ── Constants ─────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
INBOX_DIR = _SCRIPT_DIR / "panel_inbox"
PROCESSED_DIR = INBOX_DIR / "processed"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}

_ALERT_STATE_FILE = INBOX_DIR / ".active_alert_state.json"
_current_active_alert: dict | None = None


def _load_alert_state() -> dict | None:
    """Load the currently active alarm state from memory or persistent disk cache."""
    global _current_active_alert
    if _current_active_alert is not None:
        return _current_active_alert
    try:
        if _ALERT_STATE_FILE.exists():
            with open(_ALERT_STATE_FILE, "r", encoding="utf-8") as f:
                _current_active_alert = json.load(f)
                return _current_active_alert
    except Exception:
        pass
    _current_active_alert = None
    return None


def _save_alert_state(state: dict | None):
    """Save or clear active alert state in memory and file."""
    global _current_active_alert
    _current_active_alert = state
    try:
        _ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if state is None:
            if _ALERT_STATE_FILE.exists():
                _ALERT_STATE_FILE.unlink(missing_ok=True)
        else:
            with open(_ALERT_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
    except Exception as e:
        print(f"  [warn] Could not write alert state: {e}")


def is_duplicate_alert(message_type: str, alert_key: str, detected_zone: str = "") -> bool:
    """
    Check if the detected alert matches or is covered by the currently active alarm.
    Prevents OCR fluctuations (e.g. oscillating between 'UNKNOWN', 'Zone 1', and 'L1 A053')
    from repeatedly spamming SMS and placing repetitive phone calls.
    """
    active = _load_alert_state()
    if not active:
        return False

    active_type = active.get("message_type")
    # If a fault is active and a fire breaks out, that is an escalation -> not duplicate
    if active_type != message_type:
        return False

    active_key = active.get("key", "")
    active_zone = active.get("zone", "")

    # 1. Exact match on alert key
    if active_key == alert_key:
        return True

    # 2. If an active alarm is already recorded, any generic / fallback detection
    #    (e.g. 'PANEL', 'UNKNOWN', '') for the same alarm type is a duplicate.
    if alert_key in ("PANEL", "UNKNOWN", ""):
        return True

    # 3. If the active alarm was recorded as generic or fallback, do not re-alert on same panel alarm
    if active_key in ("PANEL", "UNKNOWN", ""):
        return True

    # 4. If both have zones and they are the same zone
    if detected_zone and active_zone and detected_zone == active_zone:
        return True

    return False


def mark_alert_active(message_type: str, alert_key: str, summary: str = "", zone: str = ""):
    """Record an active alarm state so subsequent frames are suppressed."""
    state = {
        "message_type": message_type,
        "key": alert_key,
        "zone": zone,
        "summary": summary,
        "timestamp": datetime.now().isoformat(),
    }
    _save_alert_state(state)


def clear_active_alert():
    """Clear active alarm state when panel returns to normal."""
    _save_alert_state(None)


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
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
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

    try:
        from paddleocr import PaddleOCR

        if is_arm:
            # CRITICAL: Force PP-OCRv3 models on ARM and disable auxiliary models
            # (doc orientation classifier and unwarping) which segfault on ARM64 CPU.
            for attempt in [
                {
                    "lang": "en",
                    "device": "cpu",
                    "ocr_version": "PP-OCRv3",
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                },
                {
                    "lang": "en",
                    "device": "cpu",
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                },
                {"lang": "en", "device": "cpu", "ocr_version": "PP-OCRv3"},
                {"lang": "en", "device": "cpu"},
                {"lang": "en"},
                {"lang": "en", "use_gpu": False, "ocr_version": "PP-OCRv3"},
                {"lang": "en", "use_gpu": False},
            ]:
                try:
                    _paddle_engine = PaddleOCR(**attempt)
                    print(f"  [OK] PaddleOCR initialized on ARM with: {attempt}")
                    break
                except (TypeError, ValueError, Exception) as e:
                    print(f"  [..] PaddleOCR attempt failed ({e}), trying next...")
                    continue
        else:
            for attempt in [
                {
                    "lang": "en",
                    "device": "cpu",
                    "enable_mkldnn": False,
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                },
                {
                    "lang": "en",
                    "device": "cpu",
                    "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False,
                    "use_textline_orientation": False,
                },
                {"lang": "en", "device": "cpu"},
                {"lang": "en"},
                {"lang": "en", "use_gpu": False, "use_textline_orientation": False},
                {"lang": "en", "use_gpu": False, "use_angle_cls": False},
            ]:
                try:
                    _paddle_engine = PaddleOCR(**attempt)
                    break
                except (TypeError, ValueError):
                    continue

        if _paddle_engine is None:
            print("  [!!] All PaddleOCR init attempts failed.")
            _paddle_available = False
            return None

        import logging
        import os
        os.environ["GLOG_minloglevel"] = "3"
        for _name in ("ppocr", "paddlex"):
            _l = logging.getLogger(_name)
            _l.setLevel(logging.ERROR)
            _l.propagate = False
            for _h in _l.handlers:
                _h.setLevel(logging.ERROR)

        _paddle_available = True
        return _paddle_engine
    except ImportError:
        _paddle_available = False
        return None
    except Exception as e:
        print(f"  [!!] PaddleOCR init failed: {e}")
        _paddle_available = False
        return None


def _extract_paddlex_texts(res) -> tuple[list[str], list[float]]:
    """Extract recognized texts and scores from a PaddleX result object or dict."""
    texts = []
    scores = []

    # Try dict or json representation
    data = None
    if isinstance(res, dict):
        data = res
    elif hasattr(res, "json"):
        data = res.json
    elif hasattr(res, "__dict__"):
        data = res.__dict__

    if isinstance(data, dict):
        sub = data.get("res", {}) if isinstance(data.get("res"), dict) else data
        rec_texts = data.get("rec_texts") or sub.get("rec_texts") or []
        rec_scores = data.get("rec_scores") or sub.get("rec_scores") or []
        for t, s in zip(rec_texts, rec_scores):
            t_clean = str(t).strip()
            if t_clean:
                texts.append(t_clean)
                try:
                    scores.append(float(s))
                except (ValueError, TypeError):
                    scores.append(0.9)
        if texts:
            return texts, scores

    # Try direct attributes
    if hasattr(res, "rec_texts"):
        for t, s in zip(getattr(res, "rec_texts", []), getattr(res, "rec_scores", [])):
            t_clean = str(t).strip()
            if t_clean:
                texts.append(t_clean)
                try:
                    scores.append(float(s))
                except (ValueError, TypeError):
                    scores.append(0.9)
        if texts:
            return texts, scores

    # Try item subscript
    try:
        for t, s in zip(res["rec_texts"], res.get("rec_scores", [])):
            t_clean = str(t).strip()
            if t_clean:
                texts.append(t_clean)
                try:
                    scores.append(float(s))
                except (ValueError, TypeError):
                    scores.append(0.9)
    except Exception:
        pass

    return texts, scores


def _ocr_paddle(image_path: Path | None, roi=None, calibration: dict | None = None) -> tuple[str, float]:
    """
    Run PaddleOCR on the cropped screen ROI in RAM.
    Uses engine.ocr() which is rock-solid on ARM64 and does not segfault across continuous loop cycles.
    """
    engine = _get_paddle_engine()
    if engine is None:
        raise RuntimeError("PaddleOCR not installed")

    import numpy as np
    import warnings

    if roi is not None and isinstance(roi, np.ndarray) and roi.size > 0:
        target = np.ascontiguousarray(roi)
    elif image_path is not None and Path(image_path).exists():
        target = str(image_path)
    else:
        return "", 0.0

    all_texts = []
    all_scores = []

    # Use engine.ocr() directly (suppressing harmless 3.x DeprecationWarning).
    # engine.ocr() runs stably in RAM without ARM64 C++ thread-pool segfaults.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = engine.ocr(target, cls=False)

        if results:
            for line_group in results:
                if not line_group:
                    continue
                for line in line_group:
                    if isinstance(line, (list, tuple)) and len(line) >= 2:
                        text_part = line[1]
                        if isinstance(text_part, (list, tuple)) and len(text_part) >= 2:
                            t_clean = str(text_part[0]).strip()
                            if t_clean:
                                all_texts.append(t_clean)
                                all_scores.append(float(text_part[1]))
    except Exception as e:
        print(f"  [!!] PaddleOCR ocr() exception: {e}")

    if not all_texts:
        return "", 0.0

    text = " ".join(all_texts)
    avg_confidence = sum(all_scores) / len(all_scores) if all_scores else 0.0
    print(f"  [OK] PaddleOCR extracted: '{text}' ({avg_confidence*100:.1f}%)")
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
    with open(calib_path) as f:
        return json.load(f)


def process_image(image_path: Path, calibration: dict, dry_run: bool = False) -> bool:
    """
    Run a single panel image through the complete live pipeline.
    Returns True if the image was processed and a notification was triggered.
    """
    # ── Stage 1: Load image ──────────────────────────────────────────
    try:
        Path("/tmp/fdas_heartbeat").touch(exist_ok=True)
    except Exception:
        pass

    frame = cv2.imread(str(image_path))
    if frame is None:
        print(f"  [!!] Failed to load image: {image_path}")
        return False

    # Apply camera rotation if specified in calibration
    rot = calibration.get("camera", {}).get("rotation", 0)
    if rot == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif rot == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif rot == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

    h, w = frame.shape[:2]

    # ── Stage 2: ROI crop ────────────────────────────────────────────
    roi_cfg = calibration.get("screen_roi", {})
    rw, rh = roi_cfg.get("width", 0), roi_cfg.get("height", 0)
    roi = frame if (rw == 0 or rh == 0) else crop_screen_region(frame, roi_cfg)
    # Safety: if ROI is out of bounds or empty, fall back to full frame
    if roi is None or not hasattr(roi, 'shape') or roi.size == 0 or roi.shape[0] < 50 or roi.shape[1] < 50:
        roi = frame

    # ── Stage 3+4: OCR (PaddleOCR primary, Tesseract fallback) ─────────
    text = ""
    confidence = 0.0

    paddle_success = False
    try:
        text, confidence = _ocr_paddle(image_path, roi, calibration)
        if text:
            paddle_success = True
    except Exception as e:
        print(f"  [!!] PaddleOCR error: {e}")

    if not paddle_success:
        text, confidence = _ocr_tesseract(roi)

    if not text:
        print(f"┌{'─' * 66}┐")
        print(f"│  FDAS PANEL STATUS: ⚠️  NO TEXT DETECTED                          │")
        print(f"├─────────────────────┬────────────────────────────────────────────┤")
        print(f"│  Time               │ {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<43}│")
        print(f"│  Status             │ Blurry image / camera out of focus         │")
        print(f"└─────────────────────┴────────────────────────────────────────────┘\n")
        return False

    # ── Stage 5: Classify ────────────────────────────────────────────
    message_type = classify_message(text)
    if message_type in ("normal", "unknown"):
        if message_type == "normal":
            if _load_alert_state():
                print("  [FDAS] Panel returned to NORMAL. Cleared active alert state.")
                clear_active_alert()
        status_label = "✅ NORMAL (All Clear)" if message_type == "normal" else f"ℹ️  {message_type.upper()}"
        print(f"┌{'─' * 66}┐")
        print(f"│  FDAS PANEL STATUS: {status_label:<44}│")
        print(f"├─────────────────────┬────────────────────────────────────────────┤")
        print(f"│  Time               │ {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<43}│")
        print(f"│  Camera Image       │ {w} x {h} pixels (Arducam 64MP){' ' * max(0, 16)}│")
        print(f"│  PaddleOCR Reading  │ {len(text)} chars extracted ({confidence*100:.1f}% confidence){' ' * max(0, 43 - len(f'{len(text)} chars extracted ({confidence*100:.1f}% confidence)'))}│")
        print(f"│  Active Alarms      │ 0 active fires / faults                    │")
        print(f"│  Action             │ 🟢 Monitoring... No emergency dispatch     │")
        print(f"└─────────────────────┴────────────────────────────────────────────┘\n")
        return False

    # ── Stage 6: Extract & validate device code ──────────────────────
    code = extract_code(text)
    unknown_device = False

    detected_zone = ""
    zm = re.search(r'(?:\bZone|#Zones?)\s*[:#-]?\s*(\d+)\b', text, re.IGNORECASE)
    if zm:
        detected_zone = f"Zone {zm.group(1)}"

    print(f"  [OCR RAW TEXT] {text.strip()}")
    print(f"  [CODE EXTRACTED] code='{code}', zone='{detected_zone}'")

    if not code:
        if message_type == "fire":
            # Only treat as unknown-device fire if the panel text contains confirmed alarm banner phrases
            if any(h in text.lower() for h in ("first fire", "latest fire", "fire 1/", "fire 2/", "fire at")):
                unknown_device = True
            else:
                print(f"┌{'─' * 66}┐")
                print(f"│  FDAS STATUS: ℹ️  FIRE KEYWORD WITHOUT VALID ALARM BANNER       │")
                print(f"├─────────────────────┬────────────────────────────────────────────┤")
                print(f"│  Extracted Text     │ {text[:42]:<43}│")
                print(f"│  Status             │ Ignored (no device code or alarm banner)   │")
                print(f"└─────────────────────┴────────────────────────────────────────────┘\n")
                return False
        elif message_type == "fault":
            # Real fault displayed on panel (e.g. system fault, zone fault, supply fault)
            unknown_device = True
        else:
            print(f"┌{'─' * 66}┐")
            print(f"│  FDAS STATUS: ⚠️  {message_type.upper()} (NO DEVICE CODE FOUND)           │")
            print(f"├─────────────────────┬────────────────────────────────────────────┤")
            print(f"│  Extracted Text     │ {text[:42]:<43}│")
            print(f"│  Status             │ No valid device code extracted             │")
            print(f"└─────────────────────┴────────────────────────────────────────────┘\n")
            return False

    if code and not validate_code(code):
        if message_type in ("fire", "fault"):
            unknown_device = True
        else:
            print(f"┌{'─' * 66}┐")
            print(f"│  FDAS STATUS: ⚠️  INVALID CODE: {code:<39}│")
            print(f"├─────────────────────┬────────────────────────────────────────────┤")
            print(f"│  Extracted Text     │ {text[:42]:<43}│")
            print(f"│  Status             │ Device code failed whitelist validation    │")
            print(f"└─────────────────────┴────────────────────────────────────────────┘\n")
            return False

    # Unique key for deduplicating repeated notifications across continuous frames
    alert_key = code if code else (detected_zone if detected_zone else "PANEL")

    # ── Deduplication: Suppress repeated alerts for persistent active alarm ──
    if is_duplicate_alert(message_type, alert_key, detected_zone):
        print(f"┌{'─' * 66}┐")
        print(f"│  FDAS DEDUP: ⏸️  DUPLICATE {message_type.upper():<37}│")
        print(f"├─────────────────────┬────────────────────────────────────────────┤")
        print(f"│  Time               │ {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<43}│")
        print(f"│  Device / Zone      │ {alert_key:<43}│")
        print(f"│  Status             │ Active alert already notified (suppressed) │")
        print(f"│  Action             │ 🔕 Suppressed: No repeated SMS or call     │")
        print(f"└─────────────────────┴────────────────────────────────────────────┘\n")
        return True

    # Print clean alarm card
    icon = "🚨" if message_type == "fire" else "⚠️ "
    action_text = "📱 SMS Dispatched | 📞 Call Placed" if message_type == "fire" else "📱 SMS Dispatched (No Call)"
    print(f"┌{'─' * 66}┐")
    print(f"│  {icon} ALARM DETECTED — {message_type.upper():<41}│")
    print(f"├─────────────────────┬────────────────────────────────────────────┤")
    print(f"│  Time               │ {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<43}│")
    print(f"│  Device Code        │ {code or detected_zone or 'PANEL':<43}│")
    print(f"│  OCR Confidence     │ {confidence*100:.1f}%{' ' * 37}│")
    print(f"│  Action             │ {action_text:<43}│")
    print(f"└─────────────────────┴────────────────────────────────────────────┘\n")

    # ── Stage 7: Create event + route through backend ────────────────
    if unknown_device:
        from notify.sms_gateway import send_sms
        from notify.voice_call import place_call
        from backend.db import get_connection
        from backend.location import _get_global_contacts, resolve_zone_location

        contacts = _get_global_contacts("sms")
        if not contacts:
            contacts = ["+919545202660", "+919730814745", "+919561515546", "+919172319233"]

        call_contacts = _get_global_contacts("call")
        raw_primary = call_contacts[0] if call_contacts else (contacts[0] if contacts else "")
        primary_contact = str(raw_primary.get("phone", "")) if isinstance(raw_primary, dict) else str(raw_primary or "")
        safe_contacts = [c if isinstance(c, str) else str(c.get("phone", "")) for c in contacts]

        detected_code = code if code else (detected_zone if detected_zone else "UNKNOWN")
        loc_name = resolve_zone_location(detected_code)
        loc_str = loc_name if loc_name else "Check Panel"

        # Extract zone from OCR text
        zone_str = ""
        zm = re.search(r'\bZone\s*(\d+)\b', text, re.IGNORECASE)
        if zm:
            zone_str = f"Zone {zm.group(1)}"

        # Build SMS in standard format
        type_label = {"fire": "FIRE ALARM", "fault": "FAULT ALERT", "supervisory": "SUPERVISORY ALERT"}.get(
            message_type, f"{message_type.upper()} ALERT")
        alert_msg = f"{type_label}\nDevice: {detected_code}\nLoc: {loc_str}\n{zone_str}"

        for contact in safe_contacts:
            send_sms(contact, alert_msg, dry_run=dry_run)

        # Log to DB as an active event
        conn = get_connection()
        cur = conn.execute(
            """
            INSERT INTO events (device_code, message_type, raw_text, detected_at, confidence,
                                 location_name, contacts, primary_contact, status, sms_status, call_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 'sent', 'pending')
            """,
            (
                detected_code,
                message_type,
                text,
                datetime.now(timezone.utc).isoformat(),
                confidence,
                loc_name,
                json.dumps(safe_contacts),
                primary_contact,
            ),
        )
        conn.commit()
        event_id = cur.lastrowid
        conn.close()

        # Place voice call ONLY for FIRE emergencies! NEVER for faults!
        if message_type == "fire" and primary_contact:
            place_call(event_id, primary_contact, dry_run=dry_run)

        mark_alert_active(message_type, alert_key, panel_summary, zone=detected_zone)
        return True

    event = DetectedEvent(
        device_code=code,
        message_type=message_type,
        raw_text=text,
        confidence=confidence,
        frame_id=0,
    )

    handle_detected_event(event, dry_run=dry_run, skip_debounce=True)
    mark_alert_active(message_type, alert_key, text, zone=detected_zone)
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


def run_live_camera(calibration: dict, dry_run: bool = False, interval_seconds: float = 3.0):
    """
    Continuous 24/7 camera monitoring loop in a single Python process.
    Keeps PaddleOCR loaded in memory, capturing frames via in-memory RAM buffer (/dev/shm).
    Cycle time drops from ~60s down to ~4-6s!
    """
    import subprocess
    print(f"\n{SEP}")
    print(f"  FDAS FAST LIVE MONITOR (In-Memory AI Engine)")
    print(f"  Cycle interval: {interval_seconds}s (Continuous in-memory loop)")
    print(f"  Mode: {'DRY-RUN' if dry_run else 'LIVE — real SMS/calls'}")
    print(f"{SEP}\n")

    # 1. Warm up PaddleOCR once so it stays resident in RAM
    print("  [live] Initializing PaddleOCR in RAM...")
    _get_paddle_engine()
    print("  [live] PaddleOCR ready!\n")

    shm_path = Path("/dev/shm/live_cam.jpg")
    cmd = [
        "libcamera-still",
        "--nopreview",
        "-t", "500",
        "--width", "1920",
        "--height", "1080",
        "-q", "90",
        "-o", str(shm_path),
    ]

    try:
        while True:
            # Update watchdog heartbeat
            try:
                Path("/tmp/fdas_heartbeat").touch(exist_ok=True)
            except Exception:
                pass

            t0 = time.time()
            shm_path.unlink(missing_ok=True)

            try:
                res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
                if res.returncode == 0 and shm_path.exists():
                    process_image(shm_path, calibration, dry_run=dry_run)
                else:
                    # Fallback to panel_inbox if /dev/shm is not available
                    inbox_cam = INBOX_DIR / "live_cam.jpg"
                    cmd_inbox = list(cmd)
                    cmd_inbox[-1] = str(inbox_cam)
                    subprocess.run(cmd_inbox, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
                    if inbox_cam.exists():
                        process_image(inbox_cam, calibration, dry_run=dry_run)
                    else:
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Camera busy or capture retry...")
            except Exception as e:
                print(f"  [live] Loop error: {e}")

            elapsed = time.time() - t0
            sleep_time = max(0.5, interval_seconds - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n  Stopped live monitoring.")


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
        "--live", action="store_true",
        help="Continuous 24/7 camera monitoring with fast in-memory PaddleOCR"
    )
    parser.add_argument(
        "--interval", type=float, default=3.0,
        help="Seconds between capture cycles (default: 3.0s)"
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

    elif args.live:
        # Fast continuous in-memory camera monitoring (drops cycle from 60s to ~5s)
        run_live_camera(calibration, dry_run=args.dry_run, interval_seconds=args.interval)

    elif args.watch:
        # Watch mode (watches panel_inbox/ for new images)
        watch_inbox(calibration, dry_run=args.dry_run)

    else:
        # Process inbox once
        count = process_inbox(calibration, dry_run=args.dry_run)
        print(f"\n  Processed {count} image(s)")


if __name__ == "__main__":
    main()
