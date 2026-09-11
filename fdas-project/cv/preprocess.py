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

    The panel display has WHITE TEXT on a BLUE BACKGROUND. Standard
    grayscale preprocessing gives poor results on blue-dominant images
    because it reduces blue-channel contrast. This function instead:
      1. Extracts the Blue channel from BGR (where white text has highest value)
      2. Inverts the channel so text becomes dark on white background
      3. Upscales the image 2x for better Tesseract character recognition
      4. Applies CLAHE for local contrast normalization
      5. Applies adaptive thresholding for clean binary image output

    Use this function instead of preprocess_for_ocr() when reading real
    panel camera images from the Honeywell LCD display.
    """
    # Step 1: Extract BLUE channel only (white text appears brightest in blue channel)
    blue_channel = roi[:, :, 0]   # OpenCV BGR ordering: index 0 = Blue channel

    # Step 2: Invert the channel so white text becomes dark (black text on white)
    inverted = cv2.bitwise_not(blue_channel)

    # Step 3: Upscale 2x for better Tesseract character recognition on small LCD fonts
    upscaled = cv2.resize(inverted, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    # Step 4: CLAHE for local contrast normalization
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    contrast = clahe.apply(upscaled)

    # Step 5: Adaptive threshold -- produces clean black text on white background
    binary = cv2.adaptiveThreshold(
        contrast, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15, C=4
    )
    return binary
