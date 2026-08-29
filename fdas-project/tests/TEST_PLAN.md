# Test Plan (Member 6)

## Test rig (Week 1 — before hardware arrives)
- [ ] Record or source footage of an LED going OFF -> RED next to printed
      sample device codes, saved to `tests/sample_footage/`
- [ ] Include edge cases: glare/reflection, partial obstruction, code text
      at an angle, low light

## Unit-level (per module, as they land)
- [ ] `cv.led_detect` — correctly classifies RED vs OFF across sample frames
- [ ] `cv.validate` — rejects malformed codes and codes not in the known list
- [ ] `backend.debounce` — requires N consecutive detections; rejects single flickers
- [ ] `backend.debounce.ActiveEventRegistry` — dedupes a sustained alarm correctly
- [ ] `notify.sms_gateway` — retries on failure, escalates after max retries

## Integration (Week 5-6)
- [ ] Full pipeline: simulated alarm -> SMS received -> event logged -> resolved on clear
- [ ] False trigger: brief glare does NOT produce a notification
- [ ] Sustained alarm: only ONE notification sent, not one per frame
- [ ] SMS failure: retry/escalation path exercised (mock the gateway to fail)
- [ ] Watchdog: kill the main pipeline process, confirm fault alert fires
- [ ] Watchdog: cover the camera, confirm blank-frame fault alert fires

## Soak test (Week 7)
- [ ] Run continuously 48-72h against looped test footage or live panel
- [ ] Confirm no missed heartbeats, no duplicate notifications, no memory growth
