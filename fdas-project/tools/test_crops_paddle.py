"""
Test OCR directly on a folder of cropped panel images.

Primary engine: RapidOCR (ONNX Runtime based; PP-OCR models with zero memory leaks)
Loads the exact OCR engine and settings used in run_live.py once,
then processes every image in the target directory and displays:
  - Extracted Text
  - OCR Confidence Score
  - Alarm State (FIRE / FAULT / SUPERVISORY / NORMAL)
  - Extracted Device Code (e.g. L1/53 or L1 A053)

Usage:
    python3 tools/test_crops_paddle.py /home/Pi1/Desktop/NewCamImages/crops
    # Or without arguments to use the default crops folder
"""

import sys
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
import os
from pathlib import Path

# Add project root to sys.path
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from cv.classify import classify_message
from cv.validate import extract_code
from run_live import _get_ocr_engine, _ocr_rapid, _is_arm_platform


def main():
    target_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/home/Pi1/Desktop/NewCamImages/crops")

    if not target_dir.exists() or not target_dir.is_dir():
        print(f"❌ Error: Folder not found: {target_dir}")
        print("Usage: python3 tools/test_crops_paddle.py <path_to_crops_folder>")
        sys.exit(1)

    extensions = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.JPG", "*.PNG")
    files = sorted([f for ext in extensions for f in target_dir.glob(ext)])

    if not files:
        print(f"❌ No images found in {target_dir}")
        sys.exit(1)

    print(f"\n{'=' * 75}")
    print(f"  FDAS OCR Crop Tester (RapidOCR Primary from run_live.py)")
    print(f"  Target Folder : {target_dir}")
    print(f"  Images Found  : {len(files)}")
    print(f"  Platform      : {'ARM (Raspberry Pi)' if _is_arm_platform() else 'x86/Other'}")
    print(f"{'=' * 75}\n")

    print("⏳ Initializing RapidOCR engine...")
    engine = _get_ocr_engine()
    if engine is None:
        print("❌ Failed to initialize RapidOCR!")
        sys.exit(1)
    print("✅ RapidOCR Engine Ready!\n")

    for idx, p in enumerate(files, 1):
        print(f"[{idx}/{len(files)}] 🖼️  File: {p.name}")
        try:
            # Run exact RapidOCR extraction
            text, conf = _ocr_rapid(p, roi=None, calibration={})

            if not text:
                print("   ⚠️  No text detected by RapidOCR")
                print("-" * 75)
                continue

            cls = classify_message(text)
            code = extract_code(text)

            # Visual badge for state
            badge = "🚨 FIRE" if cls == "fire" else ("⚠️ FAULT" if cls == "fault" else f"ℹ️ {cls.upper()}")

            print(f"   🔍 OCR Text       : {repr(text)}")
            print(f"   📊 Confidence     : {conf * 100:.1f}%")
            print(f"   🏷️  Classified As  : {badge}")
            print(f"   🔢 Device Code    : {code if code else 'None detected'}")
        except Exception as e:
            print(f"   ❌ Error during OCR: {e}")
        print("-" * 75)


if __name__ == "__main__":
    main()
