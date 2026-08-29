# FDAS Alarm Notification System

Camera-based OCR reading of the fire alarm panel's full display, with
automatic SMS + voice call notification and permanent event logging.
Supplementary layer only — never modifies, interfaces with, or replaces
the certified FDAS panel, hooters, or sirens.

**Architecture updated after the industry site visit**: the panel's LED
can't be relied on as a trigger or classifier. The system now continuously
reads and interprets the full screen text, classifying each message as
fire, fault, supervisory, or normal, and routes notification accordingly:
SMS goes out immediately to the resolved contact group, and for **fire**
messages specifically, a blank voice call follows immediately after to a
single primary contact — the ring itself is the alert, no audio/TTS needed.
Confirmed GSM-only for both SMS and the call (no cloud gateway).

See `docs/proposal.pdf` and `docs/project_charter.docx` for the original
design and delivery plan (note: some details, particularly the LED trigger
and single-code detection, are superseded by this update).

## Repo layout

```
hardware/   Calibration config, mounting notes, screen ROI setup       (Member 1)
cv/         Capture, change detection, OCR, classify, extract code     (Member 2)
backend/    Debounce, dedupe, location lookup, routing, DB + log       (Member 3)
notify/     SMS dispatch, voice call, resolution tracking              (Member 4)
watchdog/   Health monitoring + systemd deployment                     (Member 5)
docs/       Proposal, charter, as-built documentation                  (Member 6)
tests/      Test rig footage, test plans, integration tests            (Member 6)
```

## Pipeline (current)

1. **Capture** — ~1 fps
2. **Change detection** (`cv/change_detect.py`) — replaces the old LED
   trigger. Compares each frame's screen region to the last; only runs
   OCR when the content actually changed, to keep the Pi's CPU/power draw
   low for 24/7 operation.
3. **Full-screen OCR** (`cv/ocr.py`) — reads the whole message area, not
   a small fixed code box.
4. **Classify** (`cv/classify.py`) — determines message type: fire,
   fault, supervisory, or normal/unknown. **Uses common fire-panel
   vocabulary with fuzzy matching** since we don't yet have this panel's
   exact wording — see the note in `cv/classify.py` and
   `hardware/CALIBRATION.md` for the follow-up needed to tighten this.
5. **Extract code** (`cv/validate.py`) — searches the OCR'd text for a
   device/zone code, then validates format + known-device-list membership.
6. **Debounce + dedupe** (`backend/debounce.py`) — requires 2+ consistent
   reads before accepting, and suppresses repeat notifications for a
   message that's still on screen. **Keyed on `(device_code, message_type)`**,
   not just device code — a device going from fault to fire is a distinct,
   more urgent event and must not be suppressed as a "duplicate."
7. **Resolve location + log** (`backend/location.py`) — always logged to
   the DB before any notification is attempted.
8. **Route** (`backend/routing.py`) — a small config table deciding, per
   message type, whether to SMS and/or place a call. Currently: fire →
   SMS + call; fault/supervisory → SMS only.
9. **Notify** — `notify/sms_gateway.py` sends SMS immediately;
   `notify/voice_call.py` places the blank call right after, for routes
   that call for one.
10. **Resolution tracking** (`notify/resolve.py`) — clears and re-arms
    when the message stops showing.

## Data contract (frozen at Week 4 checkpoint)

See `cv/event.py` for the canonical `DetectedEvent` / `ResolvedEvent`
shapes. Key addition since the original design: `message_type` and
`raw_text` now travel with every event.

## Getting started

Runnable end-to-end right now, against a synthetic test panel, with zero
real hardware:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 1. Generate synthetic test footage (fire / fault / supervisory / normal screens)
python3 -m tests.generate_test_footage

# 2. Seed the commissioning-time device map with the test device
python3 -m hardware.seed_device_map

# 3. Run the full test suite
python3 -m unittest discover -s tests -p "test_*.py" -v

# 4. Or run the CV pipeline standalone against one message type
python3 -m cv.capture --source tests/sample_footage/fire --dry-run
```

All 34 tests should pass. This exercises real logic end to end — OCR via
Tesseract, change detection, keyword+fuzzy classification, composite-key
debounce/dedupe, SQLite logging, message-type routing, and SMS/call
dispatch in dry-run mode. Nothing here is mocked-out scaffolding.

### Swapping in real hardware later
- **Camera**: point `--source` at a camera index (e.g. `0`) instead of a
  footage folder.
- **Calibration**: Member 1 replaces `hardware/calibration.json`'s
  `screen_roi` with the real site's pixel coordinates.
- **Classifier vocabulary**: once you have the real panel's exact
  wording (see `hardware/CALIBRATION.md`), tighten `cv/classify.py`'s
  keyword lists from inferred terms to the confirmed phrases.
- **Device map**: replace the entries in `hardware/seed_device_map.py`
  with the real commissioning-time device list.
- **GSM**: `notify/sms_gateway.py` and `notify/voice_call.py` both have a
  `dry_run` flag and a clearly marked spot for the real pyserial/AT-command
  implementation once the SIM7600 hardware is in hand.
- **PaddleOCR**: `cv/ocr.py` tries PaddleOCR first, falls back to
  Tesseract automatically — installing `paddleocr` on the Pi activates it
  with no code changes.

## Status

Track progress on the team Kanban board (one column per folder above).
The core plumbing works end-to-end against synthetic data as of this
commit, including the new classify/route/call logic. Remaining work per
module is real-hardware validation, the real panel vocabulary, and the
`TODO`s left in each file — not building the pipeline from scratch.
