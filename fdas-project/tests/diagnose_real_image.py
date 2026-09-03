"""
Diagnostic: run the REAL panel image through every pipeline stage and
show exactly what gets extracted.

Does NOT import numpy, cv2, or pytesseract (all crash on this Python
3.13 + MINGW numpy build). Instead:
  - Pillow loads and preprocesses the image
  - tesseract.exe is called directly via subprocess
  - classify / validate are pure-Python, no numpy needed

Usage:
    python3 -m tests.diagnose_real_image [path_to_image]

Default: tests/real_panel_replica.png  or  tests/real_panel.jpg
"""

from __future__ import annotations

import json, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image as PILImage, ImageFilter, ImageOps

# ── helpers ───────────────────────────────────────────────────────────────────
SEP = "=" * 65

def hdr(t):  print(f"\n{SEP}\n  {t}\n{SEP}")
def ok(l,v): print(f"  [OK]  {l}: {v!r}")
def warn(l,v): print(f"  [!!]  {l}: {v!r}")

# ── find tesseract binary ─────────────────────────────────────────────────────
def _find_tesseract() -> str | None:
    """Search common install locations on Windows."""
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    # Also try PATH
    for c in candidates:
        if Path(c).exists():
            return c
    # Try bare name (on PATH)
    try:
        subprocess.run(["tesseract", "--version"],
                       capture_output=True, timeout=5)
        return "tesseract"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None

TESSERACT = _find_tesseract()

# ── locate image ──────────────────────────────────────────────────────────────
for p in ([sys.argv[1]] if len(sys.argv) > 1 else []) + [
    "tests/real_panel.jpg",
    "tests/real_panel_replica.png",
]:
    if p and Path(p).exists():
        image_path = Path(p)
        break
else:
    print("ERROR: no image found. Run:  python3 -m tests.make_real_panel_replica")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 0 — Load
# ══════════════════════════════════════════════════════════════════════════════
hdr(f"STAGE 0 - Load image: {image_path}")
img = PILImage.open(image_path).convert("RGB")
W, H = img.size
ok("Size", f"{W} x {H}")

# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 1 — ROI crop
# ══════════════════════════════════════════════════════════════════════════════
hdr("STAGE 1 - ROI crop (calibration.json)")
calib = json.loads(Path("hardware/calibration.json").read_text())
roi = calib["screen_roi"]
ok("screen_roi", roi)

x, y = roi.get("x", 0), roi.get("y", 0)
rw = roi.get("width", 0) or W
rh = roi.get("height", 0) or H

# Clamp to actual image size
rw = min(rw, W - x)
rh = min(rh, H - y)

cropped = img.crop((x, y, x + rw, y + rh))
ok("Cropped size", f"{cropped.size[0]} x {cropped.size[1]}")

debug = Path("tests/debug")
debug.mkdir(exist_ok=True)
cropped.save(str(debug / "01_roi.png"))
ok("Saved", "tests/debug/01_roi.png")

# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 2 — Preprocess
# ══════════════════════════════════════════════════════════════════════════════
hdr("STAGE 2 - Preprocess for OCR")

gray   = ImageOps.grayscale(cropped)
eq     = ImageOps.equalize(gray)
sharp  = eq.filter(ImageFilter.SHARPEN)
binary = sharp.point(lambda p: 255 if p > 128 else 0, '1').convert("L")
# Invert: Tesseract prefers dark text on light background
inverted = ImageOps.invert(binary)

binary.save(str(debug / "02_binary.png"))
inverted.save(str(debug / "03_inverted.png"))
ok("Saved", "tests/debug/02_binary.png  +  03_inverted.png")

# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 3 — OCR (call tesseract.exe directly, NO pytesseract/numpy)
# ══════════════════════════════════════════════════════════════════════════════
hdr("STAGE 3 - OCR via tesseract subprocess")

text = ""
confidence = 0.0

if TESSERACT is None:
    warn("Tesseract", "NOT FOUND on this machine!")
    print("  Install: winget install UB-Mannheim.TesseractOCR")
    print("  Or download: https://github.com/UB-Mannheim/tesseract/wiki")
    print()
    print("  Falling back to KNOWN text from the replica image...")
    # Use the text we know is in the replica as fallback
    text = (
        "First Fire Zone 1 08:10 | #Zones\n"
        "Latest Fire Zone 1 08:10 | 1\n"
        "Fire 1/1 at 08:10 << >>\n"
        "Zone : 1\n"
        "Device: OPT ABV B100 MC SD L1/53\n"
        "L1 A053"
    )
    confidence = 1.0
    warn("Using known text", "(OCR will be real once Tesseract is installed)")
else:
    ok("Tesseract found", TESSERACT)

    # Try OCR on: (a) original colour crop, (b) inverted binary
    for label, pil_img in [("colour ROI", cropped), ("inverted binary", inverted)]:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
            pil_img.save(tmp_path)

        try:
            result = subprocess.run(
                [TESSERACT, tmp_path, "-", "--psm", "6", "-l", "eng"],
                capture_output=True, text=True, timeout=30,
            )
            candidate = result.stdout.strip()
            if candidate and len(candidate) > len(text):
                text = candidate
                ok(f"OCR ({label})", f"{len(text)} chars extracted")
        except Exception as e:
            warn(f"OCR ({label})", str(e))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    if not text:
        warn("OCR result", "EMPTY from both attempts")

print(f"\n  --- RAW OCR TEXT ({len(text)} chars) ---\n")
for i, line in enumerate(text.splitlines(), 1):
    print(f"  {i:2d}| {line}")
print()

# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 4 — Classify
# ══════════════════════════════════════════════════════════════════════════════
hdr("STAGE 4 - Classify message type")
from cv.classify import classify_message
message_type = classify_message(text)
(ok if message_type in ("fire","fault","supervisory") else warn)("message_type", message_type)

# Show which keyword matched
text_lower = text.lower()
from cv.classify import _VOCABULARY
for cat, kws in _VOCABULARY.items():
    hits = [kw for kw in kws if kw in text_lower]
    if hits:
        print(f"    matched keywords for '{cat}': {hits}")

# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 5 — Extract & validate device code
# ══════════════════════════════════════════════════════════════════════════════
hdr("STAGE 5 - Extract & validate device code")
from cv.validate import extract_code, validate_code, _known_devices
code  = extract_code(text)
valid = validate_code(code)

(ok if code else warn)("Extracted code (canonical)", code)
if valid:
    ok("validate_code", f"PASS - '{code}' is in known_devices.txt")
elif code:
    warn("validate_code", f"FAIL - '{code}' not in {_known_devices}")
else:
    warn("validate_code", "FAIL - no device code pattern found in OCR text")

# ══════════════════════════════════════════════════════════════════════════════
#  STAGE 6 — Routing + pipeline decision
# ══════════════════════════════════════════════════════════════════════════════
hdr("STAGE 6 - Routing & pipeline decision")
from backend.routing import get_route
route = get_route(message_type)
print(f"  message_type = {message_type!r}")
print(f"  send_sms     = {route.send_sms}")
print(f"  place_call   = {route.place_call}")

if message_type not in ("normal", "unknown") and valid:
    print()
    print("  +++ WOULD EMIT DetectedEvent +++")
    print(f"      device_code  = {code!r}")
    print(f"      message_type = {message_type!r}")
    print(f"      confidence   = {confidence:.3f}")
    print()
    print("  +++ THEN (after debounce + location resolve) +++")
    print(f"      SMS  -> contacts for '{code}'")
    if route.place_call:
        print(f"      CALL -> primary_contact for '{code}' (ring-only, no TTS)")
    print()
    print("  This is what would happen for every frame where the panel")
    print("  shows this FIRE message. The debouncer requires 2+ consecutive")
    print("  identical reads before triggering, and the deduplicator ensures")
    print("  only ONE notification per (device, message_type) pair.")
elif message_type in ("normal", "unknown"):
    print()
    warn("Decision", f"'{message_type}' - NOT forwarded, no notification")
else:
    print()
    warn("Decision", "code invalid/missing - event dropped")

hdr("DONE")
print("  Debug images in tests/debug/:")
print("    01_roi.png      - cropped screen region")
print("    02_binary.png   - after threshold")
print("    03_inverted.png - inverted (what Tesseract sees)")
print()
