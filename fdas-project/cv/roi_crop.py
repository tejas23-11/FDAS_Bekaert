"""
Region of interest extraction -- now the full message display area, not
just a small device-code box, since we need to read and classify the
whole message (fire / fault / supervisory / normal), not just extract a
code from a known-fixed spot.

Owner: Member 2.
"""


def crop_screen_region(frame, screen_roi: dict):
    """
    Crop the statically defined bounding box containing the panel's full
    text display, established during calibration (see hardware/CALIBRATION.md).
    Wider than the old code-only ROI -- covers however many lines the
    panel shows (message type line + zone/device line, typically).

    Falls back to the full frame if width/height are 0 (not yet calibrated).
    """
    x, y = screen_roi.get("x", 0), screen_roi.get("y", 0)
    w, h = screen_roi.get("width", 0), screen_roi.get("height", 0)

    if w == 0 or h == 0:
        # Not calibrated yet — use full frame
        return frame

    return frame[y:y + h, x:x + w]
