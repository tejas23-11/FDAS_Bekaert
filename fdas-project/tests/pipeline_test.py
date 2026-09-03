"""
pipeline_test.py  —  Run the full FDAS pipeline against any panel image
                       and print every stage's output clearly.

Uses ONLY:  Pillow (image load + preprocess)
            tesseract.exe called via subprocess (no pytesseract/numpy crash)
            cv/classify.py, cv/validate.py, backend/routing.py  (pure Python)

Usage:
    python3 tests/pipeline_test.py tests/panel_image2.png
    python3 tests/pipeline_test.py          # auto-picks best available image
"""

from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).parent.parent           # fdas-project/
sys.path.insert(0, str(ROOT))

# ─────────────────────────────────────────────────────────────────────────────
TESS_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "tesseract",
]

def _find_tess():
    for p in TESS_PATHS:
        try:
            subprocess.run([p, "--version"], capture_output=True, timeout=5)
            return p
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None

TESS = _find_tess()

# ─────────────────────────────────────────────────────────────────────────────
def ocr_image(pil_img: Image.Image) -> tuple[str, float]:
    """Run tesseract on a PIL image, return (text, confidence 0-1)."""
    if TESS is None:
        return "", 0.0

    results = []
    for variant_name, variant in [
        ("colour",   pil_img),
        ("inverted", ImageOps.invert(ImageOps.grayscale(pil_img))),
        ("equalized",ImageOps.equalize(ImageOps.grayscale(pil_img))),
    ]:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name
            variant.save(tmp)
        try:
            r = subprocess.run(
                [TESS, tmp, "-", "--psm", "6", "-l", "eng"],
                capture_output=True, text=True, timeout=30,
            )
            t = r.stdout.strip()
            if t:
                results.append((len(t), t))
        except Exception:
            pass
        finally:
            Path(tmp).unlink(missing_ok=True)

    if not results:
        return "", 0.0
    results.sort(reverse=True)
    return results[0][1], 0.8      # confidence placeholder until real conf available

# ─────────────────────────────────────────────────────────────────────────────
def run_pipeline(image_path: Path):
    SEP = "-" * 60

    print(f"\n{'='*60}")
    print(f"  FDAS PIPELINE TEST")
    print(f"  Image: {image_path.name}")
    print(f"{'='*60}")

    # ── Load ──────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STAGE 1: Load & ROI crop")
    print(SEP)

    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    print(f"  Image size      : {W} x {H} px")

    calib = json.loads((ROOT / "hardware/calibration.json").read_text())
    roi   = calib["screen_roi"]
    x, y  = roi.get("x", 0),     roi.get("y", 0)
    rw    = roi.get("width",  0) or W
    rh    = roi.get("height", 0) or H
    rw, rh = min(rw, W - x), min(rh, H - y)

    cropped = img.crop((x, y, x+rw, y+rh))
    print(f"  ROI             : ({x},{y}) -> {rw}x{rh} px")

    # Save debug
    dbg = ROOT / "tests/debug"
    dbg.mkdir(exist_ok=True)
    cropped.save(str(dbg / "real_01_roi.png"))
    inverted = ImageOps.invert(ImageOps.grayscale(cropped))
    inverted.save(str(dbg / "real_02_inverted.png"))
    print(f"  Saved debug     : tests/debug/real_01_roi.png")

    # ── OCR ───────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STAGE 2: OCR (Tesseract)")
    print(SEP)

    if TESS:
        print(f"  Tesseract       : {TESS}")
        text, conf = ocr_image(cropped)
    else:
        print("  Tesseract       : NOT INSTALLED — using known replica text")
        # Use the text visible in the image (fallback for testing)
        text = (
            "First Fire  Zone 1          10:01 |#Zones\n"
            "Latest Fire Zone 1          10:01 |  1\n"
            "Fire   1/1   at 10:01           4 P\n"
            "Zone  : 1\n"
            "Device: MCP           UTILITY R BD L2/138\n"
            "       L2 A138"
        )
        conf = 1.0   # known-text, so perfect confidence
        print("  (Install Tesseract to get real OCR output)")

    print(f"\n  OCR confidence  : {conf:.2f}")
    print(f"  +-- RAW OCR TEXT {'-'*37}+")
    for i, line in enumerate(text.splitlines(), 1):
        print(f"  |  {i:2d}| {line}")
    print(f"  +{'-'*57}+")

    # -- Classify ----------------------------------------------------------
    print(f"\n{SEP}")
    print("  STAGE 3: Classify message type")
    print(SEP)

    from cv.classify import classify_message, _VOCABULARY
    msg_type = classify_message(text)
    print(f"  message_type    : {msg_type.upper()}")

    # Show which keywords fired
    tl = text.lower()
    for cat, kws in _VOCABULARY.items():
        hits = [k for k in kws if k in tl]
        if hits:
            mark = "  <<< MATCHED" if cat == msg_type else ""
            print(f"    [{cat}] matched keywords: {hits}{mark}")

    # ── Extract & validate code ────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STAGE 4: Extract & validate device code")
    print(SEP)

    from cv.validate import extract_code, validate_code, _known_devices
    code  = extract_code(text)
    valid = validate_code(code)

    print(f"  Extracted code  : {code!r}  {'[VALID]' if valid else '[NOT IN KNOWN LIST]'}")
    print(f"  Known devices   : {sorted(_known_devices)}")

    # ── Route ─────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("  STAGE 5: Routing decision")
    print(SEP)

    from backend.routing import get_route
    route = get_route(msg_type)
    print(f"  Send SMS        : {route.send_sms}")
    print(f"  Place call      : {route.place_call}")

    # ── Final result ──────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if msg_type not in ("normal", "unknown") and valid:
        print("  RESULT: ALARM EVENT — pipeline would fire!")
        print(f"    device_code  = {code!r}")
        print(f"    message_type = {msg_type!r}")
        print(f"    confidence   = {conf:.2f}")
        print()
        if route.send_sms:
            print("    >> SMS  sent to all contacts")
        if route.place_call:
            print("    >> CALL placed to primary contact (ring-only)")
    elif msg_type in ("normal", "unknown"):
        print(f"  RESULT: NO ACTION — classified as '{msg_type}'")
    else:
        print(f"  RESULT: DROPPED — code '{code}' not in known_devices.txt")
        print(f"    Add it with:  python3 -m hardware.seed_device_map")
    print(f"{'='*60}\n")

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Find an image to use
    candidates = (
        [Path(sys.argv[1])] if len(sys.argv) > 1 else []
    ) + [
        Path("tests/panel_image2.png"),
        Path("tests/real_panel.jpg"),
        Path("tests/real_panel_replica.png"),
    ]
    img_path = next((p for p in candidates if p.exists()), None)
    if img_path is None:
        print("No image found. Run:  python3 -m tests.make_real_panel_replica  first")
        sys.exit(1)
    run_pipeline(img_path)
