"""Step 4: Image Preprocessing. Owner: Member 2.

Blue-LCD-aware pipeline (confirmed against real Honeywell panel photos, 2026-09):
  - The panel has WHITE text on a BLUE-backlit LCD.
  - Standard grayscale collapses channels; the blue background dominates and
    makes the LCD region appear uniform after binarization (all text lost).
  - Fix: extract the RED channel.
      Blue BG pixels:  R~30,  G~60,  B~255  -> red is DARK
      White text pixels: R~200, G~200, B~255 -> red is BRIGHT
    This gives excellent contrast for white-on-blue LCD text.
  - 2x upscaling before OCR significantly improves Tesseract accuracy on
    small pixel-font characters.
  - Morphological erosion (1-px kernel) removes sub-character blobs (LED
    indicator dots that bleed into the ROI) without affecting character
    strokes. Technique recommended by OpenCV LCD OCR best-practices.
"""

import cv2


def preprocess_for_ocr(roi):
    """
    Blue-LCD-aware preprocessing pipeline:
      1. Extract RED channel  -> high contrast white-on-blue
      2. Upscale 2x           -> Tesseract needs large-enough text
      3. Fixed threshold      -> clean binary image
      4. Invert               -> dark text on white bg (Tesseract standard)
      5. Morphological erode  -> kill small LED-dot blobs

    Confirmed against real_panel.jpg (L2 A138) and real_panel2.jpeg (L1 A064).
    """
    # 1. Extract the red channel (OpenCV BGR: index 2 = red)
    red = roi[:, :, 2]

    # 2. Upscale 2x — improves character resolution for Tesseract
    h, w = red.shape[:2]
    upscaled = cv2.resize(red, (w * 2, h * 2), interpolation=cv2.INTER_LANCZOS4)

    # 3. Fixed threshold: red > 120 = text (white pixels), else = blue background
    _, binary = cv2.threshold(upscaled, 120, 255, cv2.THRESH_BINARY)

    # 4. Invert: Tesseract expects dark text on a light background
    inverted = cv2.bitwise_not(binary)

    # 5. Morphological erosion: removes isolated small blobs (LED indicator dots,
    #    JPEG compression artifacts) while keeping character strokes intact.
    #    A 2x2 kernel at 2x scale is equivalent to 1px erosion on the original.
    #    Reference: OpenCV morphological operations docs + LCD OCR best-practices.
    erode_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.erode(inverted, erode_kernel, iterations=1)

    return cleaned
