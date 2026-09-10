"""
SIM7600-H Hardware Ring-Only Voice Caller Module.

Implements blank voice calls over AT commands for SIM7600-H hardware.
Per post-visit architecture: ring-only call (no TTS required) to alert primary contact.

Owner: Member 4 (GSM Hardware Subsystem Lead)
"""

import time
from typing import Optional
from GSM7600.sim7600_driver import get_sim7600_serial, send_at_command


def place_call_sim7600(
    primary_contact: str,
    ring_duration: float = 12.0,
    dry_run: bool = False,
    port_override: Optional[str] = None
) -> bool:
    """
    Places a blank (ring-only) voice call to `primary_contact` using SIM7600-H.

    AT Command Execution Steps:
      Step 1: ATD<phone_number>;  -> Initiate voice call (semicolon ';' is mandatory for voice calls).
      Step 2: time.sleep(12.0)    -> Allow target phone to ring for 12 seconds (~3-4 rings).
      Step 3: ATH                 -> Execute hang-up command.

    Args:
        primary_contact: Phone number to dial (e.g. "+919876543210")
        ring_duration: Seconds to let recipient phone ring before hanging up (default: 12.0s)
        dry_run: If True, prints action without dialing hardware serial port
        port_override: Optional explicit serial device path (e.g. "/dev/ttyUSB2")

    Returns:
        True if call was successfully placed and hung up, False otherwise.
    """
    if dry_run:
        print(f"[GSM7600:DRY-RUN] CALL -> {primary_contact} (ring-only for {ring_duration}s)")
        return True

    print(f"[GSM7600:LIVE] Dialing ring-only call to {primary_contact}...")

    ser = get_sim7600_serial(port_override=port_override)

    try:
        # Step 1: Format dial command. Semicolon ';' at the end specifies Voice Call on GSM modems.
        dial_cmd = f"ATD{primary_contact};\r\n".encode("utf-8")
        ser.write(dial_cmd)
        
        time.sleep(0.5)
        response = ser.read_all().decode("utf-8", errors="ignore")
        print(f"[GSM7600:DIALING] Dial command issued. Modem response: {response.strip()}")

        # Step 2: Let target phone ring for specified duration
        print(f"[GSM7600:RINGING] Ringing phone for {ring_duration} seconds...")
        time.sleep(ring_duration)

        # Step 3: Hang up call (ATH command)
        print("[GSM7600:HANGUP] Hanging up call (ATH)...")
        ser.write(b"ATH\r\n")
        time.sleep(0.5)
        
        hangup_resp = ser.read_all().decode("utf-8", errors="ignore")
        print(f"[GSM7600:SUCCESS] Call completed and hung up. Response: {hangup_resp.strip()}")
        return True

    except Exception as err:
        print(f"[GSM7600:EXCEPTION] Error placing voice call to {primary_contact}: {err}")
        # Emergency hang-up attempt
        try:
            ser.write(b"ATH\r\n")
        except Exception:
            pass
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Standalone SIM7600 Voice Caller Tool")
    parser.add_argument("--number", required=True, help="Target phone number (e.g. +919876543210)")
    parser.add_argument("--duration", type=float, default=12.0, help="Ring duration in seconds (default: 12)")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run simulation mode")
    parser.add_argument("--port", default=None, help="Explicit serial port override (e.g. /dev/ttyUSB2)")
    args = parser.parse_args()

    success = place_call_sim7600(
        primary_contact=args.number,
        ring_duration=args.duration,
        dry_run=args.dry_run,
        port_override=args.port
    )
    print(f"Voice Call Result: {'SUCCESS' if success else 'FAILED'}")
