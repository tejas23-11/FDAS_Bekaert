"""Step 13: System Health Monitoring. Owner: Member 5.

Runs as its own systemd service (watchdog/systemd/fdas-watchdog.service),
independent of the main pipeline process, so it can detect and report a
failure of the pipeline itself rather than going quiet along with it.
cv/capture.py touches HEARTBEAT_FILE every frame cycle when heartbeat=True
(the default) -- that's the contract this module checks against.

Extended (step 14): each check result is now persisted to the system_health
table so the operator dashboard can display a live status banner.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_FILE = Path("/tmp/fdas_heartbeat")
MAX_HEARTBEAT_AGE_SECONDS = 10
CHECK_INTERVAL_SECONDS = 5

# Keep only the last N rows per check type to prevent unbounded growth.
_MAX_HEALTH_ROWS_PER_CHECK = 1000


def _record_health(check_name: str, status: str, detail: str | None = None):
    """Persist a single health check result to the database."""
    from backend.db import get_connection

    conn = get_connection()
    conn.execute(
        "INSERT INTO system_health (check_name, status, detail, checked_at) "
        "VALUES (?, ?, ?, ?)",
        (check_name, status, detail, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def _prune_old_checks(check_name: str):
    """Keep only the most recent _MAX_HEALTH_ROWS_PER_CHECK rows for a check."""
    from backend.db import get_connection

    conn = get_connection()
    conn.execute(
        "DELETE FROM system_health WHERE check_name = ? AND id NOT IN "
        "(SELECT id FROM system_health WHERE check_name = ? "
        "ORDER BY checked_at DESC LIMIT ?)",
        (check_name, check_name, _MAX_HEALTH_ROWS_PER_CHECK),
    )
    conn.commit()
    conn.close()


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


def run(iterations: int | None = None, persist: bool = True):
    """iterations=None runs forever (production); pass a number for tests.
    persist=True writes each check result to the system_health table."""
    if persist:
        from backend.db import init_db
        init_db()

    count = 0
    while iterations is None or count < iterations:
        # --- Heartbeat check ---
        hb_ok = check_heartbeat()
        if not hb_ok:
            raise_fault_alert("Main pipeline heartbeat stale or missing")
        if persist:
            _record_health(
                "heartbeat",
                "ok" if hb_ok else "fault",
                None if hb_ok else "Main pipeline heartbeat stale or missing",
            )

        # Camera and process checks are skipped in the dev/test sandbox
        # (no real camera device); Member 5 re-enables these on the Pi.
        # When enabled, they follow the same pattern:
        #   cam_ok = check_camera_feed()
        #   if not cam_ok:
        #       raise_fault_alert("Camera feed blank or unavailable")
        #   if persist:
        #       _record_health("camera", "ok" if cam_ok else "fault",
        #                      None if cam_ok else "Camera feed blank or unavailable")
        #
        #   proc_ok = check_process_alive()
        #   if not proc_ok:
        #       raise_fault_alert("Pipeline process not running")
        #   if persist:
        #       _record_health("process", "ok" if proc_ok else "fault",
        #                      None if proc_ok else "Pipeline process not running")

        # Prune old rows periodically (every 100 cycles ≈ ~8 min at 5s interval)
        if persist and count > 0 and count % 100 == 0:
            _prune_old_checks("heartbeat")
            _prune_old_checks("camera")
            _prune_old_checks("process")

        time.sleep(CHECK_INTERVAL_SECONDS)
        count += 1


if __name__ == "__main__":
    run()
