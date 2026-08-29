"""Event Resolution Tracking. Owner: Member 4."""

from __future__ import annotations

from backend.db import get_connection
from backend.debounce import ActiveEventRegistry


def check_resolution(device_code: str, message_type: str, still_showing: bool, registry: ActiveEventRegistry) -> bool:
    """
    Called each cycle for every currently-active (device_code,
    message_type) pair. still_showing comes from re-checking the current
    classified message against the live feed -- if the panel no longer
    shows this message type for this device (cleared, or superseded by a
    different message type), it's resolved:
      - mark the DB record resolved
      - reset the in-memory dedupe registry for this specific
        (device, message_type) pair, so the same combination can trigger
        a fresh notification if it happens again

    Returns True if this call resolved the event, False otherwise.
    """
    if still_showing:
        return False

    conn = get_connection()
    conn.execute(
        """
        UPDATE events SET status = 'resolved', resolved_at = datetime('now')
        WHERE device_code = ? AND message_type = ? AND status = 'active'
        """,
        (device_code, message_type),
    )
    conn.commit()
    conn.close()

    registry.mark_resolved(device_code, message_type)
    return True
