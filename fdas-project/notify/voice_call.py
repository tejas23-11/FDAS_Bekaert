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

ENABLE_VOICE_CALL = False  # Set to True when ready for live emergency calls


def place_call(db_record_id: int, primary_contact: str, dry_run: bool = True) -> bool:
    """
    Places a blank voice call (ring-only, no TTS) to primary_contact.
    """
    if dry_run:
        print(f"[notify:DRY-RUN] CALL -> {primary_contact} (ring-only)")
        status = "placed"
    elif not ENABLE_VOICE_CALL:
        print(f"[notify] Voice call temporarily DISABLED for testing (skipping call to {primary_contact})")
        status = "disabled_for_test"
    else:
        import time
        ser = None
        clean_phone = "".join(c for c in primary_contact if c.isdigit() or c == "+")
        try:
            time.sleep(1)  # Brief pause between SMS and Call for modem buffer
            ser = _serial_port()
            # Dial the number (semicolon = voice call)
            ser.write(f'ATD{clean_phone};\r'.encode())
            time.sleep(2)
            response = ser.read(ser.in_waiting).decode(errors='replace')
            print(f"[notify] Calling {clean_phone}: {response.strip()}")

            if "ERROR" in response or "NO CARRIER" in response:
                print(f"[notify] Call failed to {clean_phone}: {response.strip()}")
                status = "failed"
            else:
                # Let it ring, then hang up
                from notify.gsm_config import CALL_RING_SECONDS
                time.sleep(CALL_RING_SECONDS)
                ser.write(b'ATH\r')  # Hang up
                time.sleep(1)
                status = "placed"
        except Exception as e:
            print(f"[notify] Call error to {clean_phone}: {e}")
            status = "failed"
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass

    conn = get_connection()
    conn.execute(
        "UPDATE events SET call_status = ? WHERE id = ?",
        (status, db_record_id),
    )
    conn.commit()
    conn.close()

    return True
