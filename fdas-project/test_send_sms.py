"""
Direct GSM SMS send test script.
Run on Pi: python3 test_send_sms.py
"""
import time
import serial

PORT = "/dev/ttyUSB2"
BAUD = 115200
RECIPIENT = "+919172319233"
MESSAGE = "FDAS Test Alert from Raspberry Pi SIM7600"

print(f"Connecting to {PORT}...")
try:
    ser = serial.Serial(PORT, BAUD, timeout=5)
except Exception as e:
    print(f"Could not open {PORT}: {e}")
    exit(1)

def send_cmd(cmd, wait=0.5):
    ser.write((cmd + "\r\n").encode())
    time.sleep(wait)
    res = ser.read(ser.in_waiting).decode(errors="replace").strip()
    print(f"[{cmd}] -> {repr(res)}")
    return res

try:
    print("--- 1. Checking Modem Health ---")
    send_cmd("AT")
    send_cmd("AT+CSQ")
    send_cmd("AT+CREG?")
    send_cmd("AT+CSCA?")

    print("\n--- 2. Setting Up SMS Parameters ---")
    # Clean up full SMS memory so buffer is free
    send_cmd("AT+CMGD=1,4")
    # Text mode
    send_cmd("AT+CMGF=1")
    # Standard GSM
    send_cmd("AT+CSCS=\"GSM\"")
    # Routing domain: CS (Circuit-Switched)
    send_cmd("AT+CGSMS=1")

    print(f"\n--- 3. Sending SMS to {RECIPIENT} ---")
    ser.reset_input_buffer()
    ser.write(f'AT+CMGS="{RECIPIENT}"\r'.encode())

    # Wait up to 3 seconds for '>' prompt
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
        print(f"ERROR: Modem did not provide '>' prompt! Output: {buf.decode(errors='replace')}")
        send_cmd("AT+CEER")
        exit(1)

    print("Got '>' prompt from modem! Sending body + Ctrl+Z...")
    ser.write(MESSAGE.encode("ascii", errors="ignore") + b"\x1A")

    # Wait for result
    resp_buf = b""
    start_t = time.time()
    while time.time() - start_t < 15.0:
        if ser.in_waiting:
            resp_buf += ser.read(ser.in_waiting)
            if b"+CMGS:" in resp_buf or b"ERROR" in resp_buf:
                break
        time.sleep(0.1)

    result = resp_buf.decode(errors="replace").strip()
    print(f"\n--- 4. Result ---\n{result}")

    if "+CMGS:" in result:
        print("\nSUCCESS: SMS was accepted by the cellular tower!")
    else:
        print("\nFAILED: Checking extended carrier error reason...")
        send_cmd("AT+CEER")

finally:
    ser.close()
