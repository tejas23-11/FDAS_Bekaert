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
_BLUE_HSV_LOWER = np.array([100, 80, 60],  dtype=np.uint8)
_BLUE_HSV_UPPER = np.array([130, 255, 255], dtype=np.uint8)

# The detected LCD rectangle must be at least this fraction of the image
# area to be trusted (rejects small blue reflections / indicator LEDs).
_MIN_LCD_AREA_FRACTION = 0.05  # 5% of total image area

# Small margin (pixels) to trim from each side of the detected rectangle --
# removes the frame/bezel edge pixels that can bleed into the binarized image.
_BEZEL_MARGIN = 8


def _auto_detect_lcd(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """
    Detect the blue LCD backlight rectangle using HSV thresholding.

    Returns (x, y, w, h) of the bounding box, or None if not found.

    Approach (from OpenCV color detection best-practices):
      1. Convert BGR -> HSV (robust to brightness changes).
      2. Threshold for blue hue range to build a binary mask.
      3. Morphological open+close to remove noise and fill gaps.
      4. Find external contours; pick the largest one.
      5. Return its axis-aligned bounding rectangle, shrunk by bezel margin.
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
        return None  # Too small — probably a stray blue LED reflection

    x, y, w, h = cv2.boundingRect(largest)

    # Trim bezel margin from all sides
    m = _BEZEL_MARGIN
    x, y, w, h = x + m, y + m, w - 2 * m, h - 2 * m

    # Guard against degenerate rectangles after trimming
    if w <= 0 or h <= 0:
        return None

    return x, y, w, h


def crop_screen_region(frame: np.ndarray, screen_roi: dict) -> np.ndarray:
    """
    Return the cropped LCD region from `frame`.

    Tries HSV-based auto-detection first so that test images taken at
    arbitrary distances work without manual ROI calibration.  Falls back
    to the calibration.json bounding box for live camera frames (where
    the field of view is already controlled by camera mounting).
    """
    detected = _auto_detect_lcd(frame)
    if detected is not None:
        x, y, w, h = detected
        return frame[y:y + h, x:x + w]

    # Calibration fallback
    x = screen_roi.get("x", 0)
    y = screen_roi.get("y", 0)
    w = screen_roi.get("width",  frame.shape[1])
    h = screen_roi.get("height", frame.shape[0])
    return frame[y:y + h, x:x + w]
