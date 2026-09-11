"""Step 4: Image Preprocessing. Owner: Member 2."""

import cv2


def preprocess_for_ocr(roi):
    """
    Grayscale -> contrast enhancement -> adaptive binarization, to improve
    text legibility prior to OCR.

    TODO(Member 2): tune CLAHE clip limit / adaptive threshold block size
    against real panel footage; lighting conditions on-site may need
    different values than a default starting point.
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast = clahe.apply(gray)

    binary = cv2.adaptiveThreshold(
        contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, blockSize=11, C=2,
    )
    return binary


def preprocess_lcd_panel(roi):
    """
    Specialized preprocessing for blue-backlit LCD panels (e.g. the Honeywell
    fire alarm panel at the Bekaert site).

    Diagnostic finding (2026-09-11):
      Raw Red channel WITHOUT thresholding reads: "First Fire Zone 1 | Latest Fire Zone 1 | MCP UTILITY R BD L2-13"
      Adaptive threshold was DESTROYING the text quality (confirmed via ocr_debug.py).

    The panel display has WHITE TEXT on a BLUE BACKGROUND.
      - Red channel (BGR index 2): blue bg = near-zero, white text = 255 -> MAX contrast
      - Do NOT apply adaptive threshold -> it fragments and distorts the LCD characters

    Steps:
      1. Extract RED channel (BGR index 2)
      2. Upscale 2x for Tesseract character recognition on small LCD fonts
      3. CLAHE for local contrast normalisation (no threshold - raw channel is cleaner)
    """
    # Step 1: Red channel: white text=255, blue background=~15 -> maximum contrast
    red_channel = roi[:, :, 2]

    # Step 2: Upscale 2x -- LCD fonts are small, Tesseract reads them better larger
    upscaled = cv2.resize(red_channel, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    # Step 3: CLAHE for local brightness normalisation only -- NO threshold
    # Diagnostic confirmed adaptive threshold destroys LCD character quality
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    contrast = clahe.apply(upscaled)

    return contrast

