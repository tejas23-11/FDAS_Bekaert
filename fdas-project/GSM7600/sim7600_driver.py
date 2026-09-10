"""
SIM7600-H Hardware Serial Driver & Diagnostic Utility.

Provides robust serial port auto-detection, persistent port connection management,
and AT-command execution with line-by-line documentation for on-site debugging.

Owner: Member 4 (GSM Hardware Subsystem Lead)
"""

import sys
import time
from pathlib import Path
from typing import Tuple, Optional

# List of serial ports to probe automatically across Linux (Raspberry Pi) and Windows
CANDIDATE_PORTS = [
    "/dev/ttyUSB2",  # Standard primary AT command port on Raspberry Pi for SIM7600
    "/dev/ttyUSB1",  # Secondary AT port fallback on Raspberry Pi
    "/dev/ttyUSB0",  # Diagnostic port fallback
    "/dev/ttyS0",    # Raspberry Pi GPIO UART header fallback
    "/dev/ttyAMA0",  # Raspberry Pi alternative UART header
    "COM3",          # Windows dev environment testing port
    "COM4",          # Windows dev environment testing port
    "COM5",          # Windows dev environment testing port
]

_serial_instance = None  # Global singleton serial connection handle


def get_sim7600_serial(
    port_override: Optional[str] = None,
    baudrate: int = 115200,
    timeout: float = 3.0
):
    """
    Returns an open serial connection object for the SIM7600-H modem.
    
    If port_override is specified, uses that exact port. Otherwise, probes
    CANDIDATE_PORTS to find the active AT command interface.
    Reuses the connection if already open.
    """
    global _serial_instance

    # Return existing open connection if healthy
    if _serial_instance is not None and getattr(_serial_instance, "is_open", False):
        try:
            _serial_instance.write(b"AT\r\n")
            time.sleep(0.1)
            resp = _serial_instance.read_all().decode("utf-8", errors="ignore")
            if "OK" in resp:
                return _serial_instance
        except Exception:
            _serial_instance = None  # Port broke, force reconnect

    import serial  # Lazy import pyserial

    ports_to_try = [port_override] if port_override else CANDIDATE_PORTS

    for port in ports_to_try:
        if port is None:
            continue
        # Skip non-existent Linux device paths
        if port.startswith("/dev/") and not Path(port).exists():
            continue

        try:
            ser = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
            # Send basic AT test command to verify modem responsiveness
            ser.write(b"AT\r\n")
            time.sleep(0.2)
            response = ser.read_all().decode("utf-8", errors="ignore")

            if "OK" in response:
                print(f"[sim7600_driver] Successfully connected to SIM7600-H on {port}")
                _serial_instance = ser
                return ser
            ser.close()
        except Exception:
            continue

    raise RuntimeError(
        "Failed to communicate with SIM7600-H module. "
        "Check USB cable connection, 5V power LED, and antenna."
    )


def send_at_command(
    cmd: str,
    expected_response: str = "OK",
    wait_time: float = 0.5,
    port_override: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Sends a raw AT command string to the SIM7600-H modem and reads the output.
    
    Args:
        cmd: AT command (e.g., "AT+CSQ")
        expected_response: Substring expected in response for success (e.g. "OK")
        wait_time: Seconds to sleep before reading modem response buffer
        port_override: Optional explicit serial port path
        
    Returns:
        (success_bool, raw_response_string)
    """
    ser = get_sim7600_serial(port_override=port_override)
    
    # Ensure command ends with carriage return and line feed
    formatted_cmd = cmd.strip() + "\r\n"
    ser.write(formatted_cmd.encode("utf-8"))
    
    time.sleep(wait_time)
    raw_bytes = ser.read_all()
    response_text = raw_bytes.decode("utf-8", errors="ignore")
    
    is_success = expected_response in response_text
    return is_success, response_text


def check_modem_health(port_override: Optional[str] = None) -> dict:
    """
    Executes full hardware diagnostic routine for SIM7600-H:
      1. AT command communication check
      2. SIM card state check (AT+CPIN?)
      3. Signal quality check (AT+CSQ)
      4. 4G network registration check (AT+CEREG?)
      5. Carrier operator name (AT+COPS?)
      
    Returns a dictionary summarizing hardware status.
    """
    print("\n--- Running SIM7600-H Modem Health Check ---")
    results = {}

    # Check 1: Modem responsiveness
    ok, resp = send_at_command("AT", port_override=port_override)
    results["modem_responsive"] = ok
    print(f"1. Modem Communication (AT): {'PASSED' if ok else 'FAILED'}")

    # Check 2: SIM Card Presence
    ok, resp = send_at_command("AT+CPIN?", expected_response="READY", port_override=port_override)
    results["sim_ready"] = ok
    print(f"2. SIM Card Status (AT+CPIN?): {'READY' if ok else 'NOT READY / MISSING'}")

    # Check 3: Signal Quality
    ok, resp = send_at_command("AT+CSQ", port_override=port_override)
    results["signal_raw"] = resp.strip()
    print(f"3. Signal Quality (AT+CSQ):\n   {resp.strip()}")

    # Check 4: Network Registration
    ok, resp = send_at_command("AT+CEREG?", port_override=port_override)
    results["network_registered"] = ("0,1" in resp or "0,5" in resp or "1,1" in resp or "1,5" in resp)
    print(f"4. 4G Network Registration (AT+CEREG?):\n   {resp.strip()}")

    # Check 5: Carrier Name
    ok, resp = send_at_command("AT+COPS?", port_override=port_override)
    results["carrier_raw"] = resp.strip()
    print(f"5. Carrier Identification (AT+COPS?):\n   {resp.strip()}")

    print("-------------------------------------------\n")
    return results


if __name__ == "__main__":
    # If run directly as a script, execute hardware diagnostics
    try:
        check_modem_health()
    except Exception as err:
        print(f"[ERROR] Health check failed: {err}")
