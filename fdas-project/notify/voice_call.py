"""
Voice Call Dispatch via GSM module (SIM7600, AT commands).
Owner: Member 4
"""

from __future__ import annotations
from backend.db import get_connection

def _serial_port():
    """
    TODO(Member 4): open once and reuse across calls rather than
    reconnecting every dispatch -- placeholder for the real pyserial
    connection to the SIM7600.
        import serial
        return serial.Serial('/dev/ttyUSB2', 115200, timeout=5)
    """
    raise NotImplementedError("Wire up the real serial connection to the GSM module here")

def place_call(db_record_id: int, primary_contact: str, dry_run: bool = True) -> bool:
    """
    Places a blank voice call (ring-only, no TTS) to primary_contact.
    """
    if dry_run:
        print(f"[notify:DRY-RUN] CALL -> {primary_contact} (ring-only)")
        status = "placed"
    else:
        # Real implementation sketch:
        # ser = _serial_port()
        # ser.write(f'ATD{primary_contact};\\r'.encode())
        raise NotImplementedError("Wire up real AT-command voice call here")

    conn = get_connection()
    conn.execute(
        "UPDATE events SET call_status = ? WHERE id = ?",
        (status, db_record_id),
    )
    conn.commit()
    conn.close()

    return True
