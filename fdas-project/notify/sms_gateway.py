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
    "fire": "FIRE ALARM: {code} [{device_type}] at {location}, Zone: {zone}. Respond immediately.",
    "fault": "FDAS FAULT: {code} [{device_type}] at {location}, Zone: {zone}. Maintenance check needed.",
    "supervisory": "FDAS SUPERVISORY: {code} [{device_type}] at {location}, Zone: {zone}. Please review.",
}


def _serial_port():
    """Open a serial connection to the SIM7600 GSM module."""
    from notify.gsm_config import get_serial_connection
    return get_serial_connection()


def send_sms(to_number: str, message: str, dry_run: bool = True) -> bool:
    """
    Sends one SMS via AT commands over the GSM module's serial port.

    Real implementation sketch (SIM7600, text mode):
        ser = _serial_port()
        ser.write(b'AT+CMGF=1\r')                        # text mode
        ser.write(f'AT+CMGS="{to_number}"\r'.encode())
        ser.write(message.encode() + b"\x1A")             # Ctrl+Z sends

    dry_run=True (default) just logs what would have been sent, so the
    full pipeline is testable without hardware or a live SIM.
    """
    if dry_run:
        print(f"[notify:DRY-RUN] SMS -> {to_number}: {message}")
        return True

    import time
    ser = None
    try:
        ser = _serial_port()
        # Ensure standard GSM charset and text mode
        ser.write(b'AT+CSCS="GSM"\r')
        time.sleep(0.2)
        ser.write(b'AT+CMGF=1\r')
        time.sleep(0.3)
        ser.read(ser.in_waiting)  # flush response

        # Ensure message is strictly GSM 7-bit ASCII
        clean_msg = "".join(c for c in message if 32 <= ord(c) <= 126 or c in "\r\n")
        # Replace characters that break standard GSM 7-bit charset and explode size in text mode
        clean_msg = clean_msg.replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")").replace("#", " ")
        # Hard truncate to 140 chars to ensure it fits in a single standard 160-char SMS
        if len(clean_msg) > 140:
            clean_msg = clean_msg[:137] + "..."

        # Set recipient
        clean_number = "".join(c for c in to_number if c.isdigit() or c == "+")
        ser.write(f'AT+CMGS="{clean_number}"\r'.encode('ascii', errors='ignore'))
        time.sleep(0.5)
        ser.read(ser.in_waiting)  # wait for '>' prompt

        # Send message body + Ctrl+Z to transmit
        ser.write(clean_msg.encode('ascii', errors='ignore') + b"\x1A")
        time.sleep(4)  # SIM7600 needs a few seconds to send

        response = ser.read(ser.in_waiting).decode(errors='replace')
        if "+CMGS:" in response:
            print(f"[notify] SMS sent to {clean_number}")
            return True
        else:
            print(f"[notify] SMS failed to {clean_number}: {response}")
            return False
    except Exception as e:
        print(f"[notify] SMS error to {to_number}: {e}")
        return False
    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass


def clean_panel_ocr_for_sms(text: str) -> str:
    """Clean and format raw OCR text from the panel display for SMS inclusion."""
    if not text:
        return ""
    import re

    # Strip painted plastic faceplate labels and cabinet branding
    faceplate_patterns = [
        r"\bfire\s+fault\s+(?:disablement\s+)?buzzer\s+muted.*",
        r"\bfire\s+fault\s+buzzer\s+muted.*",
        r"\b(?:system\s+fault\s+)?delayed\s+mode\s+sounders\s+silenced.*",
        r"\bfire\s+alarm\s+control\s+panel\b",
        r"\bfire\s+alarm\s+system\b",
        r"\bhoneywell\s+fire\b",
        r"\bintelligent\s+fire\b",
    ]
    cleaned = text
    for pat in faceplate_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()

    # Replace bracket and hash characters that break standard 7-bit GSM SMS
    cleaned = cleaned.replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")").replace("#", " ")

    # Collapse excess whitespace into single spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Keep within SMS limit — panel reading must leave room for header + location
    if len(cleaned) > 70:
        cleaned = cleaned[:67] + "..."

    return cleaned


def dispatch(
    db_record_id: int,
    device_code: str,
    message_type: str,
    location_name: str,
    contacts: list[str],
    device_type: str = "",
    zone: str = "",
    dry_run: bool = True,
    raw_text: str = "",
) -> bool:
    """
    Sends to every contact in the resolved contact group.
    For fire alarms, attaches the clean OCR panel reading so time, zone, and
    panel location details are immediately visible.
    """
    if message_type == "fire":
        panel_reading = clean_panel_ocr_for_sms(raw_text)
        has_loc = location_name and location_name not in ("Unknown", "Unknown location", "Unknown location (unmapped device)")
        loc_line = f"\nLocation: {location_name}" if has_loc else ""
        if panel_reading:
            message = f"FIRE ALARM: {device_code}{loc_line}\nPanel: {panel_reading}"
        else:
            message = f"FIRE ALARM: {device_code}{loc_line}\nZone: {zone}. Respond immediately."
    else:
        template = _MESSAGE_TEMPLATES.get(message_type, "FDAS ALERT: {code} [{device_type}] at {location}, Zone: {zone}.")
        message = template.format(code=device_code, location=location_name, device_type=device_type, zone=zone)

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
