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

        # Set recipient and wait specifically for '>' prompt
        clean_number = "".join(c for c in to_number if c.isdigit() or c == "+")
        ser.write(f'AT+CMGS="{clean_number}"\r'.encode('ascii', errors='ignore'))

        prompt_found = False
        start_t = time.time()
        buf = b""
        while time.time() - start_t < 3.0:
            if ser.in_waiting:
                buf += ser.read(ser.in_waiting)
                if b">" in buf:
                    prompt_found = True
                    break
            time.sleep(0.05)

        if not prompt_found:
            print(f"[notify] SMS failed to {clean_number}: no '>' prompt from modem (got: {buf.decode(errors='replace')})")
            return False

        # Send message body + Ctrl+Z to transmit
        ser.write(clean_msg.encode('ascii', errors='ignore') + b"\x1A")

        # Wait up to 10 seconds for +CMGS: or ERROR
        resp_buf = b""
        start_t = time.time()
        while time.time() - start_t < 10.0:
            if ser.in_waiting:
                resp_buf += ser.read(ser.in_waiting)
                if b"+CMGS:" in resp_buf or b"ERROR" in resp_buf:
                    break
            time.sleep(0.1)

        response = resp_buf.decode(errors='replace')
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
        time.sleep(1.0)  # Cooldown between SMS dispatches


def extract_panel_summary(text: str) -> str:
    """Extract only useful info from raw panel OCR: time and zone number.
    Returns a clean short string like 'Zone 1 | Time: 09:57' for SMS.
    """
    if not text:
        return ""
    import re

    # Extract time (HH:MM format)
    time_match = re.search(r'\b(\d{1,2}:\d{2})\b', text)
    time_str = time_match.group(1) if time_match else ""

    # Extract zone number
    zone_match = re.search(r'\bZone\s*(\d+)\b', text, re.IGNORECASE)
    zone_str = f"Zone {zone_match.group(1)}" if zone_match else ""

    # Extract fire count if available (e.g. "1/1" in "Fire 1/1")
    fire_match = re.search(r'Fire\s+(\d+/\d+)', text, re.IGNORECASE)
    fire_str = f"Fires: {fire_match.group(1)}" if fire_match else ""

    parts = [p for p in [zone_str, fire_str, f"Time: {time_str}" if time_str else ""] if p]
    return " - ".join(parts)


def clean_panel_ocr_for_sms(text: str) -> str:
    """Legacy: kept for backward compat. Use extract_panel_summary for new code."""
    return extract_panel_summary(text)


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
    For fire alarms, builds a clean structured message with device, location, time and zone.
    """
    if message_type == "fire":
        panel_summary = extract_panel_summary(raw_text)
        has_loc = location_name and location_name not in ("Unknown", "Unknown location", "Unknown location (unmapped device)")
        loc_line = f"\nLoc: {location_name}" if has_loc else ""
        time_line = f"\n{panel_summary}" if panel_summary else ""
        message = f"FIRE ALARM\nDevice: {device_code}{loc_line}{time_line}"
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
