"""
False Alarm Button — GPIO push button that sends "false alarm" SMS to all contacts.

Wiring:
    - Connect a push button between GPIO 17 (pin 11) and GND (pin 9)
    - The script uses the internal pull-up resistor, so no external
      resistor is needed

    Pi GPIO Header:
        Pin 9  (GND)    ──── [Button] ──── Pin 11 (GPIO 17)

Usage:
    python3 -m hardware.false_alarm_button
    python3 -m hardware.false_alarm_button --dry-run     # test without sending SMS
    python3 -m hardware.false_alarm_button --gpio 27     # use a different GPIO pin

How it works:
    1. Monitors the GPIO pin for a button press (falling edge)
    2. Requires the button to be held for 2 seconds (prevents accidental presses)
    3. Sends "Previous SMS was a false alarm, please ignore it." to all contacts
    4. Contacts are read from:
       - notification_contacts table (global SMS list, if configured)
       - Falls back to all unique contacts across device_map
    5. 10-second cooldown between sends to prevent spam

Owner: Member 4 (Hardware / Notifications)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

# ── Configuration ─────────────────────────────────────────────────────
DEFAULT_GPIO_PIN = 17           # BCM pin number (physical pin 11)
HOLD_DURATION = 2.0             # Seconds the button must be held
COOLDOWN_SECONDS = 10           # Minimum seconds between sends
FALSE_ALARM_MESSAGE = "FDAS NOTICE: Previous SMS was a false alarm, please ignore it."


def _get_all_contacts() -> list[str]:
    """Get all contacts to notify.

    Priority:
      1. Global SMS contact list from notification_contacts table
      2. All unique contacts across device_map (fallback)
    """
    from backend.db import get_connection

    conn = get_connection()

    # Try global SMS list first
    row = conn.execute(
        "SELECT contacts FROM notification_contacts WHERE list_type = 'sms'"
    ).fetchone()
    if row:
        try:
            contacts = json.loads(row["contacts"])
            if contacts:
                conn.close()
                return contacts
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: collect all unique contacts from device_map
    rows = conn.execute("SELECT contacts FROM device_map").fetchall()
    conn.close()

    all_numbers = set()
    for r in rows:
        try:
            nums = json.loads(r["contacts"])
            all_numbers.update(nums)
        except (json.JSONDecodeError, TypeError):
            pass

    return list(all_numbers)


def _send_false_alarm(dry_run: bool = False) -> int:
    """Send the false alarm SMS to all contacts. Returns count sent."""
    from notify.sms_gateway import send_sms

    contacts = _get_all_contacts()
    if not contacts:
        print(f"  [!!] No contacts found in database — nothing to send")
        return 0

    print(f"  Sending to {len(contacts)} contact(s)...")
    sent = 0
    for number in contacts:
        ok = send_sms(number, FALSE_ALARM_MESSAGE, dry_run=dry_run)
        if ok:
            sent += 1
            label = "DRY-RUN" if dry_run else "SENT"
            print(f"    [{label}] {number}")
        else:
            print(f"    [FAIL] {number}")

    # Log to database
    try:
        from backend.db import get_connection
        conn = get_connection()
        conn.execute(
            "INSERT INTO events (device_code, message_type, raw_text, detected_at, "
            "confidence, location_name, sms_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "FALSE_ALARM_BTN",
                "false_alarm",
                FALSE_ALARM_MESSAGE,
                datetime.now(timezone.utc).isoformat(),
                1.0,
                "Manual button press",
                "sent" if sent > 0 else "failed",
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  [!!] DB log failed: {e}")

    return sent


def run_button_monitor(gpio_pin: int = DEFAULT_GPIO_PIN, dry_run: bool = False):
    """Main loop: monitor GPIO for button press, send SMS on confirmed press."""
    try:
        import RPi.GPIO as GPIO
    except ImportError:
        print("[!!] RPi.GPIO not available — are you running on a Raspberry Pi?")
        print("     Install with: sudo apt install python3-rpi.gpio")
        print("     Or: pip install RPi.GPIO")
        sys.exit(1)

    from backend.db import init_db
    init_db()

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"\n{'='*50}")
    print(f"  FDAS False Alarm Button Monitor")
    print(f"  GPIO: {gpio_pin} (BCM) | Mode: {mode}")
    print(f"  Hold button for {HOLD_DURATION}s to send")
    print(f"  Press Ctrl+C to stop")
    print(f"{'='*50}\n")

    last_send_time = 0

    try:
        while True:
            # Wait for button press (falling edge = button pressed to GND)
            GPIO.wait_for_edge(gpio_pin, GPIO.FALLING)

            # Debounce
            time.sleep(0.05)
            if GPIO.input(gpio_pin) == GPIO.HIGH:
                continue  # Noise, not a real press

            # Check if button is held for the required duration
            print(f"  [..] Button pressed — hold for {HOLD_DURATION}s to confirm...")
            press_start = time.time()
            confirmed = True

            while time.time() - press_start < HOLD_DURATION:
                if GPIO.input(gpio_pin) == GPIO.HIGH:
                    print(f"  [--] Released too early — cancelled")
                    confirmed = False
                    break
                time.sleep(0.1)

            if not confirmed:
                continue

            # Cooldown check
            now = time.time()
            if now - last_send_time < COOLDOWN_SECONDS:
                remaining = int(COOLDOWN_SECONDS - (now - last_send_time))
                print(f"  [--] Cooldown active — wait {remaining}s before pressing again")
                continue

            # Send the false alarm SMS
            print(f"\n  {'='*45}")
            print(f"  FALSE ALARM — Sending cancellation SMS")
            print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  {'='*45}")

            sent = _send_false_alarm(dry_run=dry_run)
            last_send_time = time.time()

            print(f"  Done — {sent} message(s) {'would be sent' if dry_run else 'sent'}")
            print()

    except KeyboardInterrupt:
        print("\n  Stopped.")
    finally:
        GPIO.cleanup(gpio_pin)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FDAS False Alarm Button Monitor")
    parser.add_argument(
        "--gpio", type=int, default=DEFAULT_GPIO_PIN,
        help=f"GPIO pin number in BCM mode (default: {DEFAULT_GPIO_PIN})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be sent without actually sending SMS"
    )
    args = parser.parse_args()

    run_button_monitor(gpio_pin=args.gpio, dry_run=args.dry_run)
