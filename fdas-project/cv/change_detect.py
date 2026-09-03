"""
Change detection for camera feed.
Owner: Member 2
"""

from __future__ import annotations
import cv2
import numpy as np

def screen_changed(frame: np.ndarray, previous_frame: np.ndarray | None, screen_roi: dict) -> bool:
    """
    Compares the current frame's screen ROI against the previous frame.
    Returns True if the mean pixel difference is above the threshold.
    """
    if previous_frame is None:
        return True

    x, y = screen_roi.get("x", 0), screen_roi.get("y", 0)
    w, h = screen_roi.get("width", 0), screen_roi.get("height", 0)

    # Use the full frame if width or height is 0 or missing
    if w == 0 or h == 0:
        roi_current = frame
        roi_prev = previous_frame
    else:
        roi_current = frame[y:y+h, x:x+w]
        roi_prev = previous_frame[y:y+h, x:x+w]

    # Calculate absolute difference
    diff = cv2.absdiff(roi_current, roi_prev)
    mean_diff = np.mean(diff)

    threshold = screen_roi.get("change_threshold", 8.0)
    return mean_diff >= threshold
