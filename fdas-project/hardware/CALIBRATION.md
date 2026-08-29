# Hardware & Calibration Checklist (Member 1)

## Physical setup
- [ ] Mount camera on fixed bracket, framing the full panel display
- [ ] Attach anti-glare hood / polarizing filter, check for reflection under
      normal site lighting (test at different times of day if possible)
- [ ] Confirm manual focus is locked and sharp across the WHOLE display,
      not just one spot -- we now read the entire message area, not a
      single small code region
- [ ] Route and secure camera adapter cable

## Calibration
- [ ] Capture a still frame with the panel in its normal (idle) state
- [ ] Identify pixel coordinates of the FULL text display area -> fill in
      `screen_roi` in `calibration.json` (this replaced the old
      `led_region` + `code_roi` split -- there's no LED trigger anymore)
- [ ] Trigger a test alarm and, separately, a test fault condition if
      possible (coordinate with site staff / fire safety technician) --
      confirm both are visible and readable within the `screen_roi`
- [ ] Check `change_threshold` in `calibration.json` against real
      lighting conditions -- too low triggers on lighting flicker/noise,
      too high misses real state changes. Start around 8.0 and tune from
      test footage.

## Critical follow-up: exact panel wording
The classifier (`cv/classify.py`) currently uses common fire-panel
vocabulary (FIRE, TROUBLE, SUPERVISORY, etc.) since we don't have this
specific Honeywell panel's exact wording yet. **Getting the real message
text is the highest-value follow-up from here:**
- [ ] Photos or notes of the exact fire alarm message text
- [ ] Photos or notes of the exact fault/trouble message text
- [ ] Photos or notes of the exact supervisory message text (if
      applicable to this panel model)
- [ ] Confirm whether multiple simultaneous alarms scroll/cycle on the
      display, or show simultaneously -- affects debounce timing

## Handoff to Member 2 (CV/OCR)
- [ ] `calibration.json` committed (or shared securely if it contains
      site-identifying info)
- [ ] Sample frames/clips of normal, fire, and fault states shared to
      `tests/sample_footage/` for development and regression testing
- [ ] Real panel wording (above) handed off as soon as available, so
      `cv/classify.py`'s keyword lists can be tightened from inferred
      vocabulary to the panel's actual phrasing
