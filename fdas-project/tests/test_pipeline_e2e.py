import unittest
import os
from pathlib import Path

from backend.db import get_connection, DB_PATH
from backend.debounce import Debouncer, ActiveEventRegistry
from cv.event import DetectedEvent
from hardware.seed_device_map import seed


class TestPipelineE2E(unittest.TestCase):

    def setUp(self):
        if DB_PATH.exists():
            os.remove(DB_PATH)
        seed()

        # Reset global debounce/registry state for each test
        import backend.pipeline as pipeline
        pipeline.debouncer = Debouncer(required_consecutive=2, window_seconds=1.0)
        pipeline.registry  = ActiveEventRegistry()

    def tearDown(self):
        if DB_PATH.exists():
            os.remove(DB_PATH)

    # ------------------------------------------------------------------
    def test_fire_event_debounced_first(self):
        """First detection must be debounced -- nothing logged yet."""
        from backend.pipeline import handle_detected_event
        event = DetectedEvent(device_code="L1 A053", message_type="fire")
        handle_detected_event(event)

        conn = get_connection()
        rows = conn.execute("SELECT * FROM events").fetchall()
        conn.close()
        self.assertEqual(len(rows), 0, "Debounced event should not be logged")

    def test_fire_event_confirmed(self):
        """Second detection passes debounce → logged + SMS + call in dry-run."""
        from backend.pipeline import handle_detected_event
        e1 = DetectedEvent(device_code="L1 A053", message_type="fire")
        e2 = DetectedEvent(device_code="L1 A053", message_type="fire")
        handle_detected_event(e1)
        handle_detected_event(e2)

        conn = get_connection()
        rows = conn.execute("SELECT * FROM events").fetchall()
        conn.close()

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["device_code"],   "L1 A053")
        self.assertEqual(row["message_type"],   "fire")
        self.assertEqual(row["location_name"],  "Server Room - Zone 1")
        self.assertEqual(row["sms_status"],     "sent")
        self.assertEqual(row["call_status"],    "placed")

    def test_fault_event_confirmed(self):
        """Fault → SMS only (no call)."""
        from backend.pipeline import handle_detected_event
        e1 = DetectedEvent(device_code="L1 A053", message_type="fault")
        e2 = DetectedEvent(device_code="L1 A053", message_type="fault")
        handle_detected_event(e1)
        handle_detected_event(e2)

        conn = get_connection()
        row = conn.execute("SELECT * FROM events").fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["message_type"],  "fault")
        self.assertEqual(row["sms_status"],    "sent")
        self.assertEqual(row["call_status"],   "not_applicable")

    def test_dedupe_same_state_suppressed(self):
        """Third+ detections of the same (device, type) must not create new rows."""
        from backend.pipeline import handle_detected_event
        for _ in range(5):
            handle_detected_event(DetectedEvent(device_code="L1 A053", message_type="fire"))

        conn = get_connection()
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_fault_then_fire_creates_two_records(self):
        """Upgrade from fault → fire is a distinct event (composite key)."""
        from backend.pipeline import handle_detected_event
        # Confirm the fault
        handle_detected_event(DetectedEvent(device_code="L1 A053", message_type="fault"))
        handle_detected_event(DetectedEvent(device_code="L1 A053", message_type="fault"))
        # Confirm the fire
        handle_detected_event(DetectedEvent(device_code="L1 A053", message_type="fire"))
        handle_detected_event(DetectedEvent(device_code="L1 A053", message_type="fire"))

        conn = get_connection()
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
