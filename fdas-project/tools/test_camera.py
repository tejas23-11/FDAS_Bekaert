"""
Quick camera test — verify the Pi camera/USB webcam is working.

Usage:
    python3 -m tools.test_camera

    # With a specific camera index
    python3 -m tools.test_camera --camera 1

    # Save a snapshot without display (headless Pi)
    python3 -m tools.test_camera --headless

This script:
  1. Opens the camera and grabs a frame
  2. Prints resolution and brightness info
  3. Saves a test snapshot to tools/camera_test.jpg
  4. Optionally shows a live preview window

Owner: Member 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

_SCRIPT_DIR = Path(__file__).resolve().parent


def test_camera(camera_index: int = 0, headless: bool = False):
    print(f"\n  Testing camera {camera_index}...")

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"  [FAIL] Could not open camera {camera_index}")
        print(f"\n  Troubleshooting:")
        print(f"    1. Check camera is connected:  ls /dev/video*")
        print(f"    2. Load V4L2 driver:           sudo modprobe bcm2835-v4l2")
        print(f"    3. Check permissions:           sudo usermod -a -G video $USER")
        print(f"    4. Try a different index:       python3 -m tools.test_camera --camera 1")
        return False

    # Grab a frame
    ok, frame = cap.read()
    if not ok or frame is None:
        print(f"  [FAIL] Camera opened but could not read a frame")
        cap.release()
        return False

    h, w = frame.shape[:2]
    brightness = frame.mean()
    print(f"  [OK] Resolution: {w} x {h}")
    print(f"  [OK] Brightness: {brightness:.1f} (0=black, 255=white)")

    if brightness < 5:
        print(f"  [WARN] Frame is very dark — check lens cap / lighting")
    elif brightness > 250:
        print(f"  [WARN] Frame is very bright — check for overexposure")
    else:
        print(f"  [OK] Frame looks normal")

    # Save snapshot
    snap_path = _SCRIPT_DIR / "camera_test.jpg"
    cv2.imwrite(str(snap_path), frame)
    print(f"  [OK] Snapshot saved: {snap_path}")

    if not headless:
        print(f"\n  Showing live preview — press 'q' to quit")
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            cv2.imshow(f"Camera {camera_index} — press q to quit", frame)
            if cv2.waitKey(30) & 0xFF == ord("q"):
                break
        cv2.destroyAllWindows()

    cap.release()
    print(f"  [OK] Camera test passed!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FDAS Camera Test")
    parser.add_argument("--camera", type=int, default=0, help="Camera index (default: 0)")
    parser.add_argument("--headless", action="store_true", help="No display window (headless Pi)")
    args = parser.parse_args()

    print("=" * 40)
    print("  FDAS Camera Test")
    print("=" * 40)

    ok = test_camera(args.camera, headless=args.headless)
    sys.exit(0 if ok else 1)
