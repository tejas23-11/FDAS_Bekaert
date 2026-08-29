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
    """
    x, y, w, h = screen_roi["x"], screen_roi["y"], screen_roi["width"], screen_roi["height"]
    return frame[y:y + h, x:x + w]
