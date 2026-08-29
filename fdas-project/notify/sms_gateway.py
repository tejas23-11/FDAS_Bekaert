"""SMS Dispatch via GSM module (SIM7600, AT commands). Owner: Member 4.

GSM-only, per the team's decision -- no cloud gateway path. dry_run mode
(the default here) lets the rest of the team build and test the full
pipeline without a live GSM module or SIM.
"""

from __future__ import annotations

import time

from backend.db import get_connection

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = [0, 2, 5]  # short for tests/dry-run; lengthen for production

_MESSAGE_TEMPLATES = {
    "fire": "FIRE ALARM: {code} at {location}. Respond immediately.",
    "fault": "FDAS FAULT: {code} at {location}. Maintenance check needed.",
    "supervisory": "FDAS SUPERVISORY: {code} at {location}. Please review.",
}


def _serial_port():
    """
    TODO(Member 4): open once and reuse across calls rather than
    reconnecting every dispatch -- placeholder for the real pyserial
    connection to the SIM7600.
        import serial
        return serial.Serial('/dev/ttyUSB2', 115200, timeout=5)
    """
    raise NotImplementedError("Wire up the real serial connection to the GSM module here")


def send_sms(to_number: str, message: str, dry_run: bool = True) -> bool:
    """
    Sends one SMS via AT commands over the GSM module's serial port.

    Real implementation sketch (SIM7600, text mode):
        ser = _serial_port()
        ser.write(b'AT+CMGF=1\\r')                        # text mode
        ser.write(f'AT+CMGS="{to_number}"\\r'.encode())
        ser.write(message.encode() + b"\\x1A")             # Ctrl+Z sends

    dry_run=True (default) just logs what would have been sent, so the
    full pipeline is testable without hardware or a live SIM.
    """
    if dry_run:
        print(f"[notify:DRY-RUN] SMS -> {to_number}: {message}")
        return True

    raise NotImplementedError("Wire up real AT-command SMS sending here")


def dispatch(
    db_record_id: int,
    device_code: str,
    message_type: str,
    location_name: str,
    contacts: list[str],
    dry_run: bool = True,
) -> bool:
    """
    Sends to every contact in the resolved contact group, with wording
    tailored to the message type. Retries with backoff on failure; marks
    'escalated' if all retries are exhausted. Always updates
    events.sms_status independently of the event record itself (already
    logged before this ever runs).
    """
    template = _MESSAGE_TEMPLATES.get(message_type, "FDAS ALERT: {code} at {location}.")
    message = template.format(code=device_code, location=location_name)

    success = False
    attempts = 0
    for delay in [0] + RETRY_BACKOFF_SECONDS[:MAX_RETRIES]:
        if delay:
            time.sleep(delay)
        attempts += 1
        try:
            for contact in contacts:
                send_sms(contact, message, dry_run=dry_run)
            success = True
            break
        except Exception as e:
            print(f"[notify] SMS attempt {attempts} failed for {device_code}: {e}")

    status = "sent" if success else "escalated"
    if not success:
        print(f"[notify] ESCALATING {device_code} -- all {attempts} SMS attempts failed")

    conn = get_connection()
    conn.execute(
        "UPDATE events SET sms_status = ?, sms_attempts = sms_attempts + ? WHERE id = ?",
        (status, attempts, db_record_id),
    )
    conn.commit()
    conn.close()

    return success
