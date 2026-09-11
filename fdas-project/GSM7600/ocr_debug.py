"""
OCR Diagnostic Script - saves preprocessed images and tries all Tesseract PSM modes.
Run this on the Pi to debug OCR issues with the real panel image.

Usage:
    python -m GSM7600.ocr_debug --image GSM7600/real_panel.jpg.jpeg --roi 230,115,740,270
"""

import argparse
import cv2
import numpy as np
from pathlib import Path

from cv.roi_crop import crop_screen_region
from cv.preprocess import preprocess_for_ocr, preprocess_lcd_panel


def run_debug(image_path: str, roi_str: str = None):
    print(f"\n[DEBUG] Loading image: {image_path}")
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"[ERROR] Could not load image: {image_path}")
        return

    h, w = frame.shape[:2]
    print(f"[DEBUG] Image size: {w}x{h}")

    # Parse ROI
    if roi_str:
        parts = [int(v.strip()) for v in roi_str.split(",")]
        roi_config = {"x": parts[0], "y": parts[1], "width": parts[2], "height": parts[3]}
    else:
        roi_config = {"x": 0, "y": 0, "width": w, "height": h}

    print(f"[DEBUG] ROI: x={roi_config['x']}, y={roi_config['y']}, w={roi_config['width']}, h={roi_config['height']}")

    # Crop ROI
    roi = crop_screen_region(frame, roi_config)
    rh, rw = roi.shape[:2]
    print(f"[DEBUG] Cropped ROI size: {rw}x{rh}")

    # Save raw ROI
    cv2.imwrite("GSM7600/debug_1_raw_roi.png", roi)
    print("[DEBUG] Saved: GSM7600/debug_1_raw_roi.png  <-- Check if this shows the LCD screen text!")

    # Save individual BGR channels
    cv2.imwrite("GSM7600/debug_2_blue_channel.png", roi[:, :, 0])
    cv2.imwrite("GSM7600/debug_3_green_channel.png", roi[:, :, 1])
    cv2.imwrite("GSM7600/debug_4_red_channel.png", roi[:, :, 2])
    print("[DEBUG] Saved BGR channels: debug_2_blue_channel.png, debug_3_green_channel.png, debug_4_red_channel.png")

    # Save standard preprocessing output
    std_processed = preprocess_for_ocr(roi)
    cv2.imwrite("GSM7600/debug_5_std_preprocess.png", std_processed)
    print("[DEBUG] Saved: GSM7600/debug_5_std_preprocess.png")

    # Save LCD-specific preprocessing output
    lcd_processed = preprocess_lcd_panel(roi)
    cv2.imwrite("GSM7600/debug_6_lcd_preprocess.png", lcd_processed)
    print("[DEBUG] Saved: GSM7600/debug_6_lcd_preprocess.png")

    # Try all Tesseract PSM modes
    import pytesseract
    print("\n[DEBUG] Testing all Tesseract PSM modes on LCD preprocessed image:")
    print("-" * 60)

    # Try PSM modes that work well for multi-line structured text displays
    psm_modes = [3, 4, 6, 11, 12]
    best_text = ""
    best_psm = 6

    for psm in psm_modes:
        try:
            cfg = f"--psm {psm}"
            text = pytesseract.image_to_string(lcd_processed, config=cfg).strip()
            clean = " | ".join(line.strip() for line in text.splitlines() if line.strip())
            conf_data = pytesseract.image_to_data(lcd_processed, config=cfg, output_type=pytesseract.Output.DICT)
            confs = [c for c in conf_data["conf"] if c >= 0]
            avg_conf = sum(confs) / len(confs) / 100.0 if confs else 0.0
            print(f"  PSM {psm:2d} (conf={avg_conf:.2f}): {clean[:80]}")
            if avg_conf > 0.3 and len(text) > len(best_text):
                best_text = text
                best_psm = psm
        except Exception as e:
            print(f"  PSM {psm:2d}: ERROR - {e}")

    print("-" * 60)

    # Also try on red channel directly (without adaptive threshold)
    print("\n[DEBUG] Trying raw Red channel (no threshold) with PSM 6:")
    try:
        red = roi[:, :, 2]
        red_upscaled = cv2.resize(red, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        cv2.imwrite("GSM7600/debug_7_red_upscaled.png", red_upscaled)
        text = pytesseract.image_to_string(red_upscaled, config="--psm 6").strip()
        clean = " | ".join(line.strip() for line in text.splitlines() if line.strip())
        print(f"  Result: {clean[:120]}")
    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"\n[DEBUG] Best result was PSM {best_psm}:")
    print(f"  {best_text[:200]}")
    print("\n[DEBUG] Inspect the saved PNG files above on your PC via RealVNC or scp to see what Tesseract sees!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OCR Debug Tool - saves preprocessed images and tries all PSM modes")
    parser.add_argument("--image", required=True, help="Path to panel image")
    parser.add_argument("--roi", default=None, help="ROI as x,y,w,h (e.g. 230,115,740,270)")
    args = parser.parse_args()

    run_debug(args.image, args.roi)
