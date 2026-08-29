"""Step 13: System Health Monitoring. Owner: Member 5.

Runs as its own systemd service (watchdog/systemd/fdas-watchdog.service),
independent of the main pipeline process, so it can detect and report a
failure of the pipeline itself rather than going quiet along with it.
cv/capture.py touches HEARTBEAT_FILE every frame cycle when heartbeat=True
(the default) -- that's the contract this module checks against.
"""

from __future__ import annotations

import time
from pathlib import Path

HEARTBEAT_FILE = Path("/tmp/fdas_heartbeat")
MAX_HEARTBEAT_AGE_SECONDS = 10
CHECK_INTERVAL_SECONDS = 5


def check_heartbeat(max_age_seconds: float = MAX_HEARTBEAT_AGE_SECONDS) -> bool:
    if not HEARTBEAT_FILE.exists():
        return False
    age = time.time() - HEARTBEAT_FILE.stat().st_mtime
    return age <= max_age_seconds


def check_camera_feed(device_index: int = 0) -> bool:
    """Blank/black-frame check. TODO(Member 5): tune brightness threshold
    against the real camera once hardware arrives."""
    import cv2

    cap = cv2.VideoCapture(device_index)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return False
    return frame.mean() > 5


def check_process_alive(process_name: str = "cv.capture") -> bool:
    import psutil

    for proc in psutil.process_iter(["cmdline"]):
        cmdline = " ".join(proc.info.get("cmdline") or [])
        if process_name in cmdline:
            return True
    return False


def raise_fault_alert(reason: str):
    """
    TODO(Member 5): wire this to a channel independent of the main
    notification path -- e.g. a direct SMS to the on-call maintainer, not
    routed through the same dedupe/logging pipeline being monitored.
    """
    print(f"[watchdog] FAULT: {reason}")


def run(iterations: int | None = None):
    """iterations=None runs forever (production); pass a number for tests."""
    count = 0
    while iterations is None or count < iterations:
        if not check_heartbeat():
            raise_fault_alert("Main pipeline heartbeat stale or missing")
        # Camera and process checks are skipped in the dev/test sandbox
        # (no real camera device); Member 5 re-enables these on the Pi.
        time.sleep(CHECK_INTERVAL_SECONDS)
        count += 1


if __name__ == "__main__":
    run()
