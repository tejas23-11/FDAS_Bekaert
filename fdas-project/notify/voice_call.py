"""
Voice Call Dispatch via GSM module (SIM7600, AT commands).
Owner: Member 4
"""

from __future__ import annotations
from backend.db import get_connection

def _serial_port():
    """Open a serial connection to the SIM7600 GSM module."""
    from notify.gsm_config import get_serial_connection
    return get_serial_connection()

def place_call(db_record_id: int, primary_contact: str, dry_run: bool = True) -> bool:
    """
    Places a blank voice call (ring-only, no TTS) to primary_contact.
    """
    if dry_run:
        print(f"[notify:DRY-RUN] CALL -> {primary_contact} (ring-only)")
        status = "placed"
    else:
        import time
        ser = _serial_port()
        try:
            # Dial the number (semicolon = voice call)
            ser.write(f'ATD{primary_contact};\r'.encode())
            time.sleep(1)
            response = ser.read(ser.in_waiting).decode(errors='replace')
            print(f"[notify] Calling {primary_contact}: {response.strip()}")

            # Let it ring, then hang up
            from notify.gsm_config import CALL_RING_SECONDS
            time.sleep(CALL_RING_SECONDS)
            ser.write(b'ATH\r')  # Hang up
            time.sleep(1)
            status = "placed"
        except Exception as e:
            print(f"[notify] Call error to {primary_contact}: {e}")
            status = "failed"
        finally:
            ser.close()

    conn = get_connection()
    conn.execute(
        "UPDATE events SET call_status = ? WHERE id = ?",
        (status, db_record_id),
    )
    conn.commit()
    conn.close()

    return True
