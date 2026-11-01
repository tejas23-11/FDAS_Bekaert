"""Step 13: System Health Monitoring. Owner: Member 5.

Runs as its own systemd service (watchdog/systemd/fdas-watchdog.service),
independent of the main pipeline process, so it can detect and report a
failure of the pipeline itself rather than going quiet along with it.
cv/capture.py touches HEARTBEAT_FILE every frame cycle when heartbeat=True
(the default) -- that's the contract this module checks against.

Extended (step 14): each check result is now persisted to the system_health
table so the operator dashboard can display a live status banner.

Feature 5 extension: GSM signal strength is polled via AT+CSQ every ~30s
and stored as a 'gsm_signal' health check.

Feature 4 extension: stale 'active' events older than 24h are auto-resolved
every ~8 minutes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_FILE = Path("/tmp/fdas_heartbeat")
MAX_HEARTBEAT_AGE_SECONDS = 60
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


def _auto_resolve_stale_events():
    """Auto-resolve events stuck in 'active' status for more than 24 hours."""
    from backend.db import get_connection
    try:
        conn = get_connection()
        now = datetime.now(timezone.utc).isoformat()
        result = conn.execute(
            "UPDATE events SET status = 'resolved', resolved_at = ? "
            "WHERE status = 'active' AND detected_at < datetime('now', '-24 hours')",
            (now,)
        )
        if result.rowcount > 0:
            print(f"[watchdog] Auto-resolved {result.rowcount} stale active event(s)")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[watchdog] Could not auto-resolve stale events: {e}")


def check_heartbeat(max_age_seconds: float = MAX_HEARTBEAT_AGE_SECONDS) -> bool:
    if not HEARTBEAT_FILE.exists():
        return False
    age = time.time() - HEARTBEAT_FILE.stat().st_mtime
    return age <= max_age_seconds


def check_camera_feed(device_index: int = 0) -> bool:
    """Check if the camera is producing frames."""
    # If pipeline is alive and heartbeating, camera must be OK
    if HEARTBEAT_FILE.exists():
        age = time.time() - HEARTBEAT_FILE.stat().st_mtime
        if age <= MAX_HEARTBEAT_AGE_SECONDS:
            return True

    # Check if a recent live frame exists in /dev/shm or panel_inbox
    for p in (Path("/dev/shm/live_cam.jpg"), Path("/dev/shm/fdas_live.jpg"), Path("panel_inbox/live_cam.jpg")):
        if p.exists() and (time.time() - p.stat().st_mtime) <= MAX_HEARTBEAT_AGE_SECONDS:
            return True

    # Pipeline isn't running — try direct camera access as last resort
    try:
        import cv2
        cap = cv2.VideoCapture(device_index)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            return False
        return frame.mean() > 5
    except Exception:
        return False


def check_process_alive(process_names: tuple[str, ...] = ("cv.capture", "run_live", "run_monitor", "start_fdas")) -> bool:
    import psutil

    for proc in psutil.process_iter(["cmdline"]):
        cmdline = " ".join(proc.info.get("cmdline") or [])
        if any(p in cmdline for p in process_names):
            return True
    return False


def check_gsm_signal() -> tuple[str, int | None, str]:
    """
    Query GSM module signal strength via AT+CSQ.

    Returns:
        (status, rssi_value, detail_string)
        status: 'ok' | 'fault'
        rssi_value: 0-31 integer, or None if unreadable
        detail_string: human-readable description

    AT+CSQ RSSI values:
        0       = -113 dBm or less (no signal)
        1       = -111 dBm
        2-9     = Marginal
        10-14   = OK
        15-19   = Good
        20-31   = Excellent
        99      = Not known / not detectable
    """
    try:
        from notify.gsm_config import get_serial_connection
        ser = get_serial_connection()
        try:
            ser.write(b"AT+CSQ\r\n")
            time.sleep(0.6)
            resp = ser.read(ser.in_waiting or 64).decode(errors="replace")
        finally:
            ser.close()

        for line in resp.splitlines():
            if "+CSQ:" in line:
                try:
                    rssi = int(line.split(":")[1].split(",")[0].strip())
                except (ValueError, IndexError):
                    continue
                if rssi == 99:
                    return ("fault", None, "Signal not detectable — check antenna")
                elif rssi == 0:
                    return ("fault", 0, "No signal (0/31)")
                elif rssi < 10:
                    return ("fault", rssi, f"Weak signal ({rssi}/31)")
                elif rssi < 15:
                    return ("ok", rssi, f"Signal OK ({rssi}/31)")
                elif rssi < 20:
                    return ("ok", rssi, f"Good signal ({rssi}/31)")
                else:
                    return ("ok", rssi, f"Excellent signal ({rssi}/31)")
        return ("fault", None, "No CSQ response from modem")
    except Exception as e:
        return ("fault", None, f"GSM check error: {e}")


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

        # --- Camera feed check ---
        cam_ok = check_camera_feed()
        if not cam_ok:
            raise_fault_alert("Camera feed blank or unavailable")
        if persist:
            _record_health("camera", "ok" if cam_ok else "fault",
                           None if cam_ok else "Camera feed blank or unavailable")

        # --- Pipeline process check ---
        proc_ok = check_process_alive()
        if not proc_ok:
            raise_fault_alert("Pipeline process not running")
        if persist:
            _record_health("process", "ok" if proc_ok else "fault",
                           None if proc_ok else "Pipeline process not running")

        # --- GSM signal check (every 6 cycles ≈ 30s to avoid port contention) ---
        if count % 6 == 0:
            gsm_status, rssi, gsm_detail = check_gsm_signal()
            if persist:
                _record_health("gsm_signal", gsm_status, gsm_detail)

        # Prune old rows + auto-resolve stale events (every 100 cycles ≈ ~8 min at 5s interval)
        if persist and count > 0 and count % 100 == 0:
            _prune_old_checks("heartbeat")
            _prune_old_checks("camera")
            _prune_old_checks("process")
            _prune_old_checks("gsm_signal")
            _auto_resolve_stale_events()

        time.sleep(CHECK_INTERVAL_SECONDS)
        count += 1


if __name__ == "__main__":
    run()
