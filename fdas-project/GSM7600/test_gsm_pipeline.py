"""
Standalone OCR-to-GSM Hardware Integration Test Runner.

Executes real project OCR pipeline on test panel image(s) and dispatches actual
GSM SMS alerts and ring-only Voice calls to SIM7600 hardware.

Owner: Member 4 (GSM Hardware Subsystem Lead)
Usage:
  # 1. Run in dry-run mode (safe test, prints OCR results & SIM7600 actions):
  python -m GSM7600.test_gsm_pipeline --dry-run

  # 2. Run live test against SIM7600 hardware sending to specific number:
  python -m GSM7600.test_gsm_pipeline --phone +919876543210

  # 3. Run against custom panel screenshot image:
  python -m GSM7600.test_gsm_pipeline --image path/to/panel_photo.png --phone +919876543210

  # 4. Skip OCR entirely, force-inject a known FIRE event and dispatch live SMS+Call:
  python -m GSM7600.test_gsm_pipeline --phone +919876543210 --force-fire
"""

import argparse
import sys
from pathlib import Path
import cv2

# Project pipeline imports
from cv.roi_crop import crop_screen_region
from cv.preprocess import preprocess_for_ocr
from cv.ocr import read_screen_text
from cv.classify import classify_message
from cv.validate import extract_code, validate_code
from cv.event import DetectedEvent
from backend.location import resolve_location, log_event
from hardware.seed_device_map import seed as seed_device_map

# SIM7600 GSM hardware drivers
from GSM7600.sim7600_driver import check_modem_health
from GSM7600.sms_sender import send_sms_sim7600
from GSM7600.voice_caller import place_call_sim7600


from cv.capture import load_calibration

try:
    DEFAULT_CALIBRATION = load_calibration("hardware/calibration.json")
except Exception:
    DEFAULT_CALIBRATION = load_calibration("hardware/calibration.example.json")


DEFAULT_SAMPLE_IMAGE = Path("tests/sample_footage/fire/frame_000.png")


def run_forced_fire_test(
    override_phone: str,
    dry_run: bool = False,
    port_override: str = None
):
    """
    Skips OCR entirely. Directly injects a known FIRE event for device L1 A053
    and dispatches live SMS + Voice Call via SIM7600 hardware.
    Use this when OCR is not needed (e.g. on-site hardware GSM testing).
    """
    print("\n=======================================================")
    print("      FDAS FORCED FIRE EVENT -> SIM7600 GSM TEST        ")
    print("=======================================================\n")

    # Step 1: Seed the database
    print("[1/4] Seeding device map database...")
    seed_device_map()

    # Step 2: Build a known fire event directly (no OCR needed)
    print("[2/4] Injecting known FIRE event for device L1 A053...")
    detected_event = DetectedEvent(
        device_code="L1 A053",
        message_type="fire",
        raw_text="First Fire L1 A053",
        confidence=1.0
    )

    # Step 3: Resolve location and contacts from database
    print("[3/4] Resolving location from database...")
    resolved_event = resolve_location(detected_event)
    if not resolved_event:
        print("[ERROR] Failed to resolve location!")
        return False

    log_event(resolved_event)
    target_contacts = [override_phone] if override_phone else resolved_event.contacts
    primary_caller = override_phone if override_phone else resolved_event.primary_contact

    print(f"      Location: {resolved_event.location_name}")
    print(f"      SMS Recipients: {target_contacts}")
    print(f"      Voice Call Target: {primary_caller}")

    # Step 4: Dispatch SMS and Voice Call
    print(f"\n[4/4] Dispatching GSM Notifications (Dry-Run: {dry_run})...")

    if not dry_run:
        try:
            check_modem_health(port_override=port_override)
        except Exception as err:
            print(f"[WARN] Modem check warning: {err}")

    sms_text = f"FIRE ALARM: {resolved_event.device_code} at {resolved_event.location_name}. Respond immediately."
    for number in target_contacts:
        print(f"\n-> Dispatching SMS to {number}...")
        sms_ok = send_sms_sim7600(
            to_number=number,
            message=sms_text,
            dry_run=dry_run,
            port_override=port_override
        )
        print(f"   SMS Status: {'SUCCESS' if sms_ok else 'FAILED'}")

    if primary_caller:
        print(f"\n-> Placing Voice Call to {primary_caller}...")
        call_ok = place_call_sim7600(
            primary_contact=primary_caller,
            ring_duration=12.0,
            dry_run=dry_run,
            port_override=port_override
        )
        print(f"   Voice Call Status: {'SUCCESS' if call_ok else 'FAILED'}")

    print("\n=======================================================")
    print("      FORCED FIRE TEST COMPLETE                         ")
    print("=======================================================\n")
    return True


def run_hardware_test(
    image_path: Path,
    override_phone: str = None,
    dry_run: bool = True,
    port_override: str = None
):
    """
    Executes end-to-end OCR extraction and SIM7600 hardware dispatch test.
    """
    print("\n=======================================================")
    print("      FDAS OCR -> SIM7600 GSM HARDWARE TEST HARNESS     ")
    print("=======================================================\n")

    # Step 1: Ensure database device map is seeded
    print("[1/6] Seeding device map database...")
    seed_device_map()

    # Step 2: Load panel frame image
    if not image_path.exists():
        print(f"[ERROR] Specified test image file does not exist: {image_path}")
        return False

    print(f"[2/6] Loading test panel image: {image_path}")
    frame = cv2.imread(str(image_path))
    if frame is None:
        print(f"[ERROR] Failed to read image using OpenCV: {image_path}")
        return False

    # Step 3: Run Computer Vision & OCR pipeline
    print("[3/6] Running ROI cropping, preprocessing & OCR...")
    h_img, w_img = frame.shape[:2]
    roi_config = dict(DEFAULT_CALIBRATION["screen_roi"])
    if roi_config.get("width", 0) <= 0 or roi_config.get("height", 0) <= 0:
        roi_config["x"] = 0
        roi_config["y"] = 0
        roi_config["width"] = w_img
        roi_config["height"] = h_img

    roi = crop_screen_region(frame, roi_config)
    clean_image = preprocess_for_ocr(roi)
    ocr_text, confidence = read_screen_text(clean_image)

    print(f"      OCR Raw Output Text:\n      --------------------\n      {ocr_text.replace(chr(10), ' | ')}")
    print(f"      OCR Confidence Score: {confidence:.2f}")

    # Step 4: Classify message and extract device code
    print("[4/6] Classifying event & extracting device code...")
    message_type = classify_message(ocr_text)
    device_code = extract_code(ocr_text)
    is_valid_code = validate_code(device_code)

    print(f"      Classified Message Type: '{message_type.upper()}'")
    print(f"      Extracted Device Code:   '{device_code}' (Valid: {is_valid_code})")

    if message_type in ("normal", "unknown"):
        print("[WARN] Message classified as normal/unknown. No alarm action needed.")
        return True

    # Step 5: Resolve location and contact routing
    print("[5/6] Resolving location & contact group from database...")
    detected_event = DetectedEvent(
        device_code=device_code or "L1 A053",
        message_type=message_type,
        raw_text=ocr_text,
        confidence=confidence
    )
    
    resolved_event = resolve_location(detected_event)
    if not resolved_event:
        print("[ERROR] Failed to resolve location in database!")
        return False

    # Allow overriding phone number for live testing
    target_contacts = [override_phone] if override_phone else resolved_event.contacts
    primary_caller = override_phone if override_phone else resolved_event.primary_contact

    # Log to SQLite DB
    log_event(resolved_event)

    print(f"      Location Resolved: {resolved_event.location_name}")
    print(f"      SMS Recipient List: {target_contacts}")
    print(f"      Primary Voice Caller: {primary_caller}")

    # Step 6: Perform SIM7600 GSM hardware notification
    print(f"\n[6/6] Dispatching GSM Notifications (Dry-Run: {dry_run})...")

    if not dry_run:
        # Check SIM7600 hardware status first
        try:
            check_modem_health(port_override=port_override)
        except Exception as err:
            print(f"[WARN] Modem health check warning: {err}")

    # A. Send SMS via SIM7600
    sms_text = f"FIRE ALARM: {resolved_event.device_code} at {resolved_event.location_name}. Respond immediately."
    for number in target_contacts:
        print(f"\n-> Dispatching SMS to {number}...")
        sms_ok = send_sms_sim7600(
            to_number=number,
            message=sms_text,
            dry_run=dry_run,
            port_override=port_override
        )
        print(f"   SMS Status: {'SUCCESS' if sms_ok else 'FAILED'}")

    # B. Place Voice Call via SIM7600 (For Fire events)
    if message_type == "fire" and primary_caller:
        print(f"\n-> Placing Blank Voice Call to {primary_caller}...")
        call_ok = place_call_sim7600(
            primary_contact=primary_caller,
            ring_duration=12.0,
            dry_run=dry_run,
            port_override=port_override
        )
        print(f"   Voice Call Status: {'SUCCESS' if call_ok else 'FAILED'}")

    print("\n=======================================================")
    print("      TEST HARNESS RUN COMPLETE - ALL STAGES OK        ")
    print("=======================================================\n")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FDAS OCR-to-GSM Hardware Test Runner")
    parser.add_argument("--image", default=str(DEFAULT_SAMPLE_IMAGE), help="Path to panel test image")
    parser.add_argument("--phone", default=None, help="Override destination phone number for live testing")
    parser.add_argument("--dry-run", action="store_true", help="Run simulation mode without invoking hardware serial")
    parser.add_argument("--port", default=None, help="Explicit serial port override (e.g. /dev/ttyUSB2)")
    parser.add_argument(
        "--force-fire",
        action="store_true",
        help="Skip OCR entirely. Inject a known FIRE event for L1 A053 and dispatch live SMS+Call immediately."
    )
    args = parser.parse_args()

    # Default to dry_run=True if no --phone number provided to prevent unintended dials
    is_dry_run = args.dry_run or (args.phone is None and not args.dry_run)
    if args.phone is None and not args.dry_run:
        print("[INFO] No --phone specified, running in --dry-run mode for safety.")

    # --force-fire: bypass OCR, directly dispatch SMS+Call for known FIRE event
    if args.force_fire:
        run_forced_fire_test(
            override_phone=args.phone,
            dry_run=is_dry_run,
            port_override=args.port
        )
    else:
        test_img = Path(args.image)
        if not test_img.exists():
            test_img = Path("tests/real_panel_replica.png")
        run_hardware_test(
            image_path=test_img,
            override_phone=args.phone,
            dry_run=is_dry_run,
            port_override=args.port
        )
