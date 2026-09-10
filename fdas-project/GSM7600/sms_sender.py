"""
SIM7600-H Hardware SMS Dispatch Module.

Implements text-mode SMS transmission over AT commands via pyserial for SIM7600-H.
Includes line-by-line explanation of AT command sequence and response handling.

Owner: Member 4 (GSM Hardware Subsystem Lead)
"""

import time
from typing import Optional
from GSM7600.sim7600_driver import get_sim7600_serial, send_at_command


def send_sms_sim7600(
    to_number: str,
    message: str,
    dry_run: bool = False,
    port_override: Optional[str] = None
) -> bool:
    """
    Transmits an SMS to `to_number` with payload `message`.

    AT Command Execution Steps:
      Step 1: AT+CMGF=1         -> Set modem to SMS Text Mode.
      Step 2: AT+CSCS="GSM"     -> Set character set to standard 7-bit GSM.
      Step 3: AT+CMGS="<num>"   -> Send target phone number. Wait for '>' prompt.
      Step 4: <text>\x1A        -> Send message text terminated with Ctrl+Z (0x1A).
      Step 5: Parse output      -> Check for "+CMGS: <msg_id>" and "OK".

    Args:
        to_number: Destination phone number in international or local format (e.g. "+919876543210")
        message: Text payload of the SMS
        dry_run: If True, prints dispatch details without writing to serial hardware
        port_override: Optional explicit serial device path (e.g. "/dev/ttyUSB2")

    Returns:
        True if SMS was successfully acknowledged by modem, False otherwise.
    """
    if dry_run:
        print(f"[GSM7600:DRY-RUN] SMS -> {to_number}: \"{message}\"")
        return True

    print(f"[GSM7600:LIVE] Sending SMS to {to_number}...")

    # Get active serial port handle to SIM7600 hardware
    ser = get_sim7600_serial(port_override=port_override)

    try:
        # Step 1: Set modem to SMS Text Mode (AT+CMGF=1)
        ser.write(b"AT+CMGF=1\r\n")
        time.sleep(0.3)
        
        # Step 2: Set character set encoding (AT+CSCS="GSM")
        ser.write(b'AT+CSCS="GSM"\r\n')
        time.sleep(0.3)
        
        # Read and discard startup response headers from buffer
        ser.read_all()

        # Step 3: Issue AT+CMGS command with target phone number
        cmd = f'AT+CMGS="{to_number}"\r\n'.encode("utf-8")
        ser.write(cmd)
        
        # Give modem 0.5s to respond with the '>' prompt
        time.sleep(0.5)
        prompt_response = ser.read_all().decode("utf-8", errors="ignore")

        if ">" not in prompt_response and "OK" not in prompt_response:
            print(f"[GSM7600:ERROR] Modem did not return '>' prompt. Response: {prompt_response}")
            # Retry sending prompt once
            ser.write(cmd)
            time.sleep(0.5)

        # Step 4: Write text message payload followed by Ctrl+Z (\x1A) to send
        payload = message.encode("utf-8") + b"\x1A"
        ser.write(payload)

        # Step 5: Wait up to 5 seconds for cellular transmission and modem ACK (+CMGS: <id>)
        time.sleep(4.5)
        response_text = ser.read_all().decode("utf-8", errors="ignore")

        if "+CMGS:" in response_text or "OK" in response_text:
            print(f"[GSM7600:SUCCESS] SMS delivered to {to_number}! Response: {response_text.strip()}")
            return True
        else:
            print(f"[GSM7600:FAIL] Modem response did not confirm delivery: {response_text.strip()}")
            return False

    except Exception as err:
        print(f"[GSM7600:EXCEPTION] Error during SMS transmission to {to_number}: {err}")
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Standalone SIM7600 SMS Sender Tool")
    parser.add_argument("--number", required=True, help="Target phone number (e.g. +919876543210)")
    parser.add_argument("--message", default="FDAS TEST: Fire Alarm L1 A053 at Server Room", help="SMS text message")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run simulation mode")
    parser.add_argument("--port", default=None, help="Explicit serial port override (e.g. /dev/ttyUSB2)")
    args = parser.parse_args()

    success = send_sms_sim7600(
        to_number=args.number,
        message=args.message,
        dry_run=args.dry_run,
        port_override=args.port
    )
    print(f"SMS Dispatch Result: {'SUCCESS' if success else 'FAILED'}")
