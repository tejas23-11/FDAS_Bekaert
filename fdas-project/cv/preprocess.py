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
