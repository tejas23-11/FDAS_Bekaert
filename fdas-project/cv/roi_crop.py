"""
Region of interest extraction.

Two-stage approach (confirmed against real Honeywell panel photos, 2026-09):
  1. AUTO-DETECT: Use HSV colour thresholding to find the blue LCD screen
     rectangle automatically.  The Honeywell panel has a vivid blue
     backlight (HSV hue ~100-130) that is easy to isolate even in a
     photo taken at varying distances / angles.
  2. CALIBRATION FALLBACK: If no sufficiently large blue region is found
     (e.g., the frame is already a tight camera crop, or the panel is off)
     fall back to the bounding box defined in calibration.json.

References:
  - OpenCV HSV range selection for LCD backlight isolation:
    https://docs.opencv.org/4.x/df/d9d/tutorial_py_colorspaces.html
  - cv2.findContours / boundingRect pattern for screen detection:
    standard OpenCV contour pipeline (RETR_EXTERNAL + CHAIN_APPROX_SIMPLE)

Owner: Member 2.
"""

from __future__ import annotations

import cv2
import numpy as np


# HSV range for the Honeywell blue LCD backlight.
# Hue 100-130 covers pure blue in OpenCV's 0-179 hue scale.
# Saturation >= 80 excludes white/grey pixels (low saturation).
# Value >= 60 excludes very dark pixels (off/standby screen).
_BLUE_HSV_LOWER = np.array([85, 50, 40],  dtype=np.uint8)
_BLUE_HSV_UPPER = np.array([140, 255, 255], dtype=np.uint8)

# The detected LCD rectangle must be at least 1% of total image area
_MIN_LCD_AREA_FRACTION = 0.01

_BORDER_PADDING = 15


def _auto_detect_lcd(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    Detect the blue LCD backlight rectangle using HSV thresholding.

    Returns (x, y, w, h) of the bounding box, or None if not found.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _BLUE_HSV_LOWER, _BLUE_HSV_UPPER)

    # Morphological cleanup: open removes small specks, close fills holes.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    img_area = frame.shape[0] * frame.shape[1]
    if cv2.contourArea(largest) < img_area * _MIN_LCD_AREA_FRACTION:
        return None

    x, y, w, h = cv2.boundingRect(largest)

    # Expand slightly so edge text like 'L2 A138' at bottom right is not clipped
    p = _BORDER_PADDING
    img_h, img_w = frame.shape[:2]
    x_new = max(0, x - p)
    y_new = max(0, y - p)
    w_new = min(img_w - x_new, w + 2 * p)
    h_new = min(img_h - y_new, h + 2 * p)

    return x_new, y_new, w_new, h_new


def crop_screen_region(frame: np.ndarray, screen_roi: dict, skip_auto_detect: bool = False) -> np.ndarray:
    """
    Return the cropped LCD region from `frame`.

    When skip_auto_detect=True and calibrated ROI fits within frame, directly uses calibration
    to save 1-3s of CPU per frame. Otherwise auto-detects blue LCD screen.
    """
    img_h, img_w = frame.shape[:2]
    x = screen_roi.get("x", 0)
    y = screen_roi.get("y", 0)
    w = screen_roi.get("width", img_w)
    h = screen_roi.get("height", img_h)

    # If calibrated ROI is valid and inside frame, and skip_auto_detect requested:
    if skip_auto_detect and (x + w <= img_w) and (y + h <= img_h) and w > 50 and h > 50:
        return frame[y:y + h, x:x + w]

    # Try auto-detect first for arbitrary images or when calibration doesn't fit
    detected = _auto_detect_lcd(frame)
    if detected is not None:
        dx, dy, dw, dh = detected
        return frame[dy:dy + dh, dx:dx + dw]

    # Calibration fallback clipped to frame
    x_clip = max(0, min(x, img_w - 1))
    y_clip = max(0, min(y, img_h - 1))
    w_clip = min(w, img_w - x_clip)
    h_clip = min(h, img_h - y_clip)
    if w_clip > 50 and h_clip > 50:
        return frame[y_clip:y_clip + h_clip, x_clip:x_clip + w_clip]

    return frame
