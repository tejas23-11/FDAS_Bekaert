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

    The panel display has WHITE TEXT on a BLUE BACKGROUND.
    Contrast analysis per BGR channel:
      - Blue  channel (index 0): background=HIGH,      text=HIGH  -> no contrast (WRONG!)
      - Green channel (index 1): background=LOW-MED,   text=HIGH  -> good contrast
      - Red   channel (index 2): background=VERY LOW,  text=HIGH  -> BEST contrast (use this!)

    White text  (R=255, G=255, B=255) -> Red channel = 255 (bright)
    Blue bg     (R~15,  G~40,  B~200) -> Red channel = 15  (very dark)
    This maximises the text/background separation for Tesseract.

    Steps:
      1. Extract RED channel (BGR index 2)
      2. Upscale 2x so Tesseract can read small LCD character fonts
      3. CLAHE for local contrast normalisation
      4. Adaptive threshold -> clean binary (dark text on white)
    """
    # Step 1: Red channel gives max contrast: text bright, blue bg very dark
    red_channel = roi[:, :, 2]   # BGR index 2 = Red

    # Step 2: Upscale 2x -- LCD fonts are small, Tesseract reads them better larger
    upscaled = cv2.resize(red_channel, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    # Step 3: CLAHE normalises local brightness variation (e.g. glare from display)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    contrast = clahe.apply(upscaled)

    # Step 4: Adaptive threshold -> Tesseract expects dark text on white background
    binary = cv2.adaptiveThreshold(
        contrast, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15, C=4
    )
    return binary
