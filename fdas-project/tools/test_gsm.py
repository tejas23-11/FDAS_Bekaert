"""
GSM SIM7600 Diagnostic and Test Tool.

Tests serial connection, AT commands, SIM card status, network signal,
and optionally sends a real test SMS to verify communication.

Usage (on the Pi):
    # 1. Quick diagnostic (checks connection, SIM, and signal):
    python3 -m tools.test_gsm

    # 2. Test sending a real SMS to your phone number:
    python3 -m tools.test_gsm --phone +919876543210

    # 3. Specify a different serial port (default: /dev/ttyUSB2):
    python3 -m tools.test_gsm --port /dev/ttyUSB3
"""

from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path

# Add project root to sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from notify.gsm_config import GSM_SERIAL_PORT, GSM_BAUD_RATE, GSM_TIMEOUT


def send_at_command(ser, cmd: str, wait_secs: float = 0.5) -> str:
    """Send an AT command and return the decoded response."""
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait_secs)
    resp = ser.read(ser.in_waiting or 1024).decode(errors="replace").strip()
    return resp


def diagnose_gsm(port: str | None = None, test_phone: str | None = None) -> bool:
    import serial

    # Detect available USB serial ports
    usb_ports = sorted(glob.glob("/dev/ttyUSB*"))
    print("=" * 60)
    print("  FDAS GSM SIM7600 Diagnostic Tool")
    print("=" * 60)
    print(f"  Detected USB ports: {usb_ports if usb_ports else 'NONE FOUND'}")

    target_port = port or GSM_SERIAL_PORT
    print(f"  Attempting connection on: {target_port} ({GSM_BAUD_RATE} baud)")

    if not Path(target_port).exists():
        print(f"\n  [FAIL] Port {target_port} does not exist.")
        if usb_ports:
            print(f"         Try one of the detected ports: {usb_ports}")
        else:
            print("         Is the SIM7600 USB cable firmly plugged into the Pi?")
            print("         Check with: lsusb")
        return False

    try:
        ser = serial.Serial(target_port, GSM_BAUD_RATE, timeout=GSM_TIMEOUT)
    except Exception as e:
        print(f"\n  [FAIL] Could not open {target_port}: {e}")
        print("         Make sure no other process (like another script) is using the port.")
        return False

    try:
        # 1. Basic AT handshake
        resp = send_at_command(ser, "AT")
        if "OK" not in resp:
            print(f"  [FAIL] Module not responding to AT commands. (Got: {resp!r})")
            return False
        print("  [OK] AT Handshake: SUCCESS (Module responsive)")

        # 2. Check Module Identity / Model
        resp = send_at_command(ser, "AT+CGMM")
        model = [l for l in resp.splitlines() if l and "OK" not in l and "AT+" not in l]
        print(f"  [OK] Modem Model: {model[0] if model else 'SIMCOM'}")

        # 3. Check SIM Card Status
        resp = send_at_command(ser, "AT+CPIN?")
        if "READY" in resp:
            print("  [OK] SIM Card: READY (Detected and unlocked)")
        else:
            print(f"  [WARN] SIM Card status: {resp}")
            print("         Check if SIM card is inserted properly or requires a PIN.")

        # 4. Check Signal Quality (CSQ)
        resp = send_at_command(ser, "AT+CSQ")
        # Format: +CSQ: <rssi>,<ber>
        csq_val = None
        for line in resp.splitlines():
            if "+CSQ:" in line:
                try:
                    csq_val = int(line.split(":")[1].split(",")[0].strip())
                except Exception:
                    pass
        if csq_val is not None:
            if csq_val == 99:
                print("  [WARN] Signal Strength: 99 (Not known or not detectable — check antenna!)")
            elif csq_val < 10:
                print(f"  [WARN] Signal Strength: {csq_val}/31 (Weak signal)")
            else:
                print(f"  [OK] Signal Strength: {csq_val}/31 (Good signal)")
        else:
            print(f"  [OK] Signal response: {resp.replace(chr(10), ' ')}")

        # 5. Check Network Registration
        resp = send_at_command(ser, "AT+CREG?")
        # +CREG: <n>,<stat> (1=registered home, 5=registered roaming)
        registered = any(x in resp for x in ("0,1", "0,5", ",1", ",5"))
        if registered:
            print("  [OK] Cellular Network: REGISTERED")
        else:
            print(f"  [WARN] Cellular Network registration: {resp}")

        # 6. Check Operator Name
        resp = send_at_command(ser, 'AT+COPS?')
        for line in resp.splitlines():
            if "+COPS:" in line:
                print(f"  [OK] Operator: {line.strip()}")

        # 7. Optional: Send test SMS
        if test_phone:
            print(f"\n  [..] Sending test SMS to: {test_phone}...")
            # Set text mode
            send_at_command(ser, "AT+CMGF=1")
            ser.reset_input_buffer()
            ser.write(f'AT+CMGS="{test_phone}"\r'.encode())
            time.sleep(0.5)

            # Write message body + Ctrl+Z (\x1A)
            test_msg = "FDAS System Test: SIM7600 GSM module is working properly!"
            ser.write(test_msg.encode() + b"\x1A")
            print("  [..] Waiting for network confirmation...")
            time.sleep(5)

            sms_resp = ser.read(ser.in_waiting or 1024).decode(errors="replace")
            if "+CMGS:" in sms_resp:
                print(f"  [OK] SMS SENT SUCCESSFULLY to {test_phone}!")
            else:
                print(f"  [FAIL] SMS send failed. Response: {sms_resp}")
                return False

        print("\n" + "=" * 60)
        print("  GSM DIAGNOSTIC PASSED — Module is ready for live alerts!")
        print("=" * 60)
        return True

    finally:
        ser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FDAS GSM SIM7600 Diagnostic Tool")
    parser.add_argument("--port", default=None, help=f"Serial port (default: {GSM_SERIAL_PORT})")
    parser.add_argument("--phone", default=None, help="Send a real test SMS to this phone number (e.g. +91XXXXXXXXXX)")
    args = parser.parse_args()

    success = diagnose_gsm(port=args.port, test_phone=args.phone)
    sys.exit(0 if success else 1)
