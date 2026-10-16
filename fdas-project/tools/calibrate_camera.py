"""
Camera Calibration Tool — set the screen ROI for the live pipeline.

Point the camera at the fire alarm panel, then draw a rectangle around
the LCD text display area. The tool saves the coordinates directly to
hardware/calibration.json.

Usage (on the Pi, with a monitor/VNC connected):
    python3 -m tools.calibrate_camera

    # Use a specific camera index (default: 0)
    python3 -m tools.calibrate_camera --camera 1

    # Use a saved image instead of live camera
    python3 -m tools.calibrate_camera --image tests/real_panel.jpg

Controls:
    - Click and drag to draw the ROI rectangle
    - Press 'r' to reset the selection
    - Press 's' to save and quit
    - Press 'q' to quit without saving
    - Press 'c' to capture a snapshot (saved to tools/snapshot.jpg)

Owner: Member 1 (Hardware Integration)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_CALIB_PATH = _PROJECT_ROOT / "hardware" / "calibration.json"

# ── Mouse callback state ─────────────────────────────────────────────
_drawing = False
_start_x, _start_y = 0, 0
_end_x, _end_y = 0, 0
_roi_selected = False


def _mouse_callback(event, x, y, flags, param):
    global _drawing, _start_x, _start_y, _end_x, _end_y, _roi_selected

    if event == cv2.EVENT_LBUTTONDOWN:
        _drawing = True
        _start_x, _start_y = x, y
        _end_x, _end_y = x, y
        _roi_selected = False

    elif event == cv2.EVENT_MOUSEMOVE and _drawing:
        _end_x, _end_y = x, y

    elif event == cv2.EVENT_LBUTTONUP:
        _drawing = False
        _end_x, _end_y = x, y
        _roi_selected = True


def _load_calibration() -> dict:
    """Load existing calibration or create a default."""
    if _CALIB_PATH.exists():
        with open(_CALIB_PATH) as f:
            return json.load(f)

    # Load from example
    example_path = _PROJECT_ROOT / "hardware" / "calibration.example.json"
    if example_path.exists():
        with open(example_path) as f:
            return json.load(f)

    return {
        "camera": {"device_index": 0, "resolution": [1920, 1080], "capture_fps": 1},
        "screen_roi": {"x": 0, "y": 0, "width": 0, "height": 0, "change_threshold": 8.0},
        "debounce": {"required_consecutive_frames": 2},
    }


def _save_calibration(calibration: dict):
    with open(_CALIB_PATH, "w") as f:
        json.dump(calibration, f, indent=2)
    print(f"\n  [OK] Saved calibration to: {_CALIB_PATH}")


def run_calibration(source=0, image_path: str | None = None):
    global _start_x, _start_y, _end_x, _end_y, _roi_selected

    calibration = _load_calibration()
    roi = calibration["screen_roi"]

    # If we already have a saved ROI, pre-load it
    if roi["width"] > 0 and roi["height"] > 0:
        _start_x, _start_y = roi["x"], roi["y"]
        _end_x = roi["x"] + roi["width"]
        _end_y = roi["y"] + roi["height"]
        _roi_selected = True
        print(f"  [OK] Existing ROI: ({roi['x']},{roi['y']}) {roi['width']}x{roi['height']}")

    window_name = "FDAS Camera Calibration — draw ROI around LCD text area"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window_name, _mouse_callback)

    # Source: image or camera
    if image_path:
        frame = cv2.imread(image_path)
        if frame is None:
            print(f"  [!!] Could not load image: {image_path}")
            sys.exit(1)
        print(f"  [OK] Loaded image: {image_path} ({frame.shape[1]}x{frame.shape[0]})")
        cap = None
    else:
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            print(f"  [!!] Could not open camera {source}")
            print(f"       On the Pi, check: ls /dev/video*")
            print(f"       You may need: sudo modprobe bcm2835-v4l2")
            sys.exit(1)

        # Set resolution from calibration
        res = calibration["camera"].get("resolution", [1920, 1080])
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, res[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])

        ok, frame = cap.read()
        if not ok:
            print(f"  [!!] Could not read from camera {source}")
            sys.exit(1)
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"  [OK] Camera {source}: {actual_w}x{actual_h}")

    print()
    print("  Controls:")
    print("    Click+drag = draw ROI    r = reset    s = save    q = quit    c = snapshot")
    print()

    while True:
        # Get new frame if using camera
        if cap is not None:
            ok, frame = cap.read()
            if not ok:
                break

        display = frame.copy()

        # Draw the ROI rectangle
        if _roi_selected or _drawing:
            x1 = min(_start_x, _end_x)
            y1 = min(_start_y, _end_y)
            x2 = max(_start_x, _end_x)
            y2 = max(_start_y, _end_y)

            # Draw rectangle with green outline
            cv2.rectangle(display, (x1, y1), (x2, y2), (0, 255, 0), 2)

            # Show ROI dimensions
            w = x2 - x1
            h = y2 - y1
            label = f"ROI: ({x1},{y1}) {w}x{h}"
            cv2.putText(display, label, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

            # Show the cropped ROI in a small preview window
            if _roi_selected and w > 10 and h > 10:
                roi_preview = frame[y1:y2, x1:x2]
                cv2.imshow("ROI Preview (what OCR will see)", roi_preview)

        # Status bar at the bottom
        status = "DRAW the ROI | r=reset | s=SAVE | q=quit | c=snapshot"
        if _roi_selected:
            status = f"ROI ready: ({x1},{y1}) {x2-x1}x{y2-y1} | s=SAVE | r=reset | q=quit"
        cv2.putText(display, status, (10, display.shape[0] - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        cv2.imshow(window_name, display)
        key = cv2.waitKey(30) & 0xFF

        if key == ord("q"):
            print("  Quit without saving.")
            break

        elif key == ord("r"):
            _roi_selected = False
            _start_x = _start_y = _end_x = _end_y = 0
            cv2.destroyWindow("ROI Preview (what OCR will see)")
            print("  ROI reset.")

        elif key == ord("c"):
            snap_path = _SCRIPT_DIR / "snapshot.jpg"
            cv2.imwrite(str(snap_path), frame)
            print(f"  [OK] Snapshot saved: {snap_path}")

        elif key == ord("s") and _roi_selected:
            x1 = min(_start_x, _end_x)
            y1 = min(_start_y, _end_y)
            w = abs(_end_x - _start_x)
            h = abs(_end_y - _start_y)

            calibration["screen_roi"]["x"] = x1
            calibration["screen_roi"]["y"] = y1
            calibration["screen_roi"]["width"] = w
            calibration["screen_roi"]["height"] = h

            # Also save the actual camera resolution
            if cap is not None:
                calibration["camera"]["resolution"] = [
                    int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                ]

            _save_calibration(calibration)
            print(f"  ROI: x={x1}, y={y1}, width={w}, height={h}")
            break

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FDAS Camera Calibration Tool")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument("--image", type=str, default=None, help="Use a static image instead of live camera")
    args = parser.parse_args()

    print()
    print("=" * 50)
    print("  FDAS Camera Calibration Tool")
    print("=" * 50)

    if args.image:
        run_calibration(image_path=args.image)
    else:
        run_calibration(source=args.camera)
