"""
FDAS Event History Database Corrections Tool.

Run this to fix known data quality issues in the events table:
  1. Mark orphaned 'active' events (> 24 hours old) as 'resolved'
  2. Fix stuck 'pending' sms_status / call_status on events older than 1 hour
  3. Identify and optionally mark duplicate events (same device+type within window)

Usage:
    python3 -m tools.fix_event_history            # Dry-run (preview only)
    python3 -m tools.fix_event_history --apply    # Apply corrections
    python3 -m tools.fix_event_history --backup   # Backup DB before applying
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.db import get_connection, DB_PATH


def backup_db() -> Path:
    """Create a timestamped backup of the database."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = DB_PATH.parent / f"fdas_events_backup_{ts}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"[backup] Database backed up to: {backup_path}")
    return backup_path


def fix_stale_active_events(conn, dry_run: bool = True) -> int:
    """Mark events stuck in 'active' status for > 24 hours as 'resolved'."""
    rows = conn.execute(
        "SELECT id, device_code, detected_at FROM events "
        "WHERE status = 'active' AND detected_at < datetime('now', '-24 hours')"
    ).fetchall()
    count = len(rows)
    if count == 0:
        print("[fix] No stale active events found.")
        return 0
    print(f"[fix] Found {count} active event(s) older than 24 hours:")
    for r in rows:
        print(f"      ID #{r['id']} — {r['device_code']} at {r['detected_at']}")
    if not dry_run:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE events SET status = 'resolved', resolved_at = ? "
            "WHERE status = 'active' AND detected_at < datetime('now', '-24 hours')",
            (now,)
        )
        print(f"[fix] ✅ Resolved {count} stale active event(s).")
    else:
        print(f"[dry-run] Would resolve {count} stale active event(s).")
    return count


def fix_stuck_sms_status(conn, dry_run: bool = True) -> int:
    """Mark SMS status as 'unknown' if still 'pending' after 1 hour."""
    rows = conn.execute(
        "SELECT id, device_code FROM events "
        "WHERE sms_status = 'pending' AND detected_at < datetime('now', '-1 hour')"
    ).fetchall()
    count = len(rows)
    if count == 0:
        print("[fix] No stuck SMS statuses found.")
        return 0
    print(f"[fix] Found {count} event(s) with sms_status='pending' older than 1 hour.")
    if not dry_run:
        conn.execute(
            "UPDATE events SET sms_status = 'unknown' "
            "WHERE sms_status = 'pending' AND detected_at < datetime('now', '-1 hour')"
        )
        print(f"[fix] ✅ Corrected sms_status for {count} event(s).")
    else:
        print(f"[dry-run] Would correct sms_status for {count} event(s).")
    return count


def fix_stuck_call_status(conn, dry_run: bool = True) -> int:
    """Mark call_status as 'unknown' if still 'pending' after 1 hour."""
    rows = conn.execute(
        "SELECT id, device_code FROM events "
        "WHERE call_status = 'pending' AND detected_at < datetime('now', '-1 hour')"
    ).fetchall()
    count = len(rows)
    if count == 0:
        print("[fix] No stuck call statuses found.")
        return 0
    print(f"[fix] Found {count} event(s) with call_status='pending' older than 1 hour.")
    if not dry_run:
        conn.execute(
            "UPDATE events SET call_status = 'unknown' "
            "WHERE call_status = 'pending' AND detected_at < datetime('now', '-1 hour')"
        )
        print(f"[fix] ✅ Corrected call_status for {count} event(s).")
    else:
        print(f"[dry-run] Would correct call_status for {count} event(s).")
    return count


def find_duplicate_events(conn, window_seconds: int = 30) -> list[dict]:
    """
    Find duplicate events: same device_code + message_type within a time window.
    Returns list of dicts describing each duplicate group.
    """
    rows = conn.execute(
        "SELECT id, device_code, message_type, detected_at FROM events ORDER BY detected_at ASC"
    ).fetchall()

    duplicates = []
    seen: list[dict] = []

    for r in rows:
        try:
            ts = datetime.fromisoformat(r["detected_at"].replace("Z", "+00:00"))
        except Exception:
            continue

        # Remove entries outside the window
        seen = [s for s in seen if (ts - s["ts"]).total_seconds() <= window_seconds]

        # Check for a matching entry
        match = next(
            (s for s in seen
             if s["device_code"] == r["device_code"] and s["message_type"] == r["message_type"]),
            None
        )
        if match:
            duplicates.append({
                "original_id": match["id"],
                "duplicate_id": r["id"],
                "device_code": r["device_code"],
                "message_type": r["message_type"],
                "original_at": match["detected_at"],
                "duplicate_at": r["detected_at"],
            })
        else:
            seen.append({
                "id": r["id"],
                "device_code": r["device_code"],
                "message_type": r["message_type"],
                "detected_at": r["detected_at"],
                "ts": ts,
            })

    return duplicates


def report_duplicates(conn, dry_run: bool = True, window_seconds: int = 30) -> int:
    """Report and optionally mark duplicate events."""
    dupes = find_duplicate_events(conn, window_seconds)
    if not dupes:
        print("[fix] No duplicate events found.")
        return 0
    print(f"[fix] Found {len(dupes)} potential duplicate event(s) (within {window_seconds}s window):")
    for d in dupes:
        print(f"      Original #{d['original_id']} vs Duplicate #{d['duplicate_id']} "
              f"— {d['device_code']} {d['message_type']}")
    if not dry_run:
        dupe_ids = [d["duplicate_id"] for d in dupes]
        conn.executemany(
            "UPDATE events SET status = 'duplicate' WHERE id = ?",
            [(did,) for did in dupe_ids]
        )
        print(f"[fix] ✅ Marked {len(dupes)} event(s) as 'duplicate'.")
    else:
        print(f"[dry-run] Would mark {len(dupes)} event(s) as 'duplicate'.")
    return len(dupes)


def main():
    parser = argparse.ArgumentParser(description="FDAS Event History DB Corrections")
    parser.add_argument("--apply", action="store_true",
                        help="Apply corrections (default: dry-run preview only)")
    parser.add_argument("--backup", action="store_true",
                        help="Backup DB before applying changes")
    parser.add_argument("--dedup-window", type=int, default=30,
                        help="Seconds window for duplicate detection (default: 30)")
    args = parser.parse_args()

    dry_run = not args.apply

    print("=" * 60)
    print("  FDAS Event History Correction Tool")
    print(f"  Mode: {'DRY-RUN (preview only)' if dry_run else 'APPLY CHANGES'}")
    print("=" * 60)

    if not dry_run and args.backup:
        backup_db()

    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) as cnt FROM events").fetchone()["cnt"]
    print(f"\n[info] Total events in database: {total}\n")

    try:
        n1 = fix_stale_active_events(conn, dry_run)
        print()
        n2 = fix_stuck_sms_status(conn, dry_run)
        print()
        n3 = fix_stuck_call_status(conn, dry_run)
        print()
        n4 = report_duplicates(conn, dry_run, args.dedup_window)
        print()

        if not dry_run:
            conn.commit()
            print(f"[done] Applied: {n1} stale resolved, {n2} SMS fixed, "
                  f"{n3} call fixed, {n4} duplicates marked.")
        else:
            print("[done] Dry-run complete. Run with --apply to make changes.")
            print("       Add --backup to create a database backup first.")
    finally:
        conn.close()

    print("=" * 60)


if __name__ == "__main__":
    main()

