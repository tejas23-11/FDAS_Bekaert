"""
Central GSM (SIM7600) serial port configuration.

All GSM-related modules (sms_gateway.py, voice_call.py) import from here
so the serial port is configured in exactly one place.

On the Pi, run `ls /dev/ttyUSB*` to find the right port.
The AT command port is usually /dev/ttyUSB2 for the SIM7600.

Owner: Member 4
"""

from __future__ import annotations

# ── Serial port settings ─────────────────────────────────────────────
GSM_SERIAL_PORT = "/dev/ttyUSB2"   # Change if your SIM7600 is on a different port
GSM_BAUD_RATE = 115200
GSM_TIMEOUT = 5                     # seconds

# ── Voice call settings ──────────────────────────────────────────────
CALL_RING_SECONDS = 15              # How long to let the phone ring before hanging up


def get_serial_connection():
    """Open and return a serial connection to the SIM7600 GSM module."""
    import serial
    return serial.Serial(GSM_SERIAL_PORT, GSM_BAUD_RATE, timeout=GSM_TIMEOUT)
