import unittest
from backend.debounce import Debouncer, ActiveEventRegistry, process_new_detection
from cv.event import DetectedEvent

class TestDebounce(unittest.TestCase):
    def setUp(self):
        self.debouncer = Debouncer(required_consecutive=2, window_seconds=1.0)
        self.registry = ActiveEventRegistry()

    def test_debounce_requires_two(self):
        event = DetectedEvent(device_code="L1/A053", message_type="fire")
        
        # First one should be False
        self.assertFalse(process_new_detection(event, self.debouncer, self.registry))
        
        # Second one should be True
        self.assertTrue(process_new_detection(event, self.debouncer, self.registry))
        
        # Third one should be False (already active)
        self.assertFalse(process_new_detection(event, self.debouncer, self.registry))

    def test_dedupe_different_message(self):
        event1 = DetectedEvent(device_code="L1/A053", message_type="fault")
        event2 = DetectedEvent(device_code="L1/A053", message_type="fire")
        
        # Debounce event 1
        self.debouncer.confirm(event1)
        self.assertTrue(process_new_detection(event1, self.debouncer, self.registry))
        
        # Event 1 is active, should return False
        self.assertFalse(process_new_detection(event1, self.debouncer, self.registry))
        
        # Event 2 should still process because message_type is different
        self.debouncer.confirm(event2)
        self.assertTrue(process_new_detection(event2, self.debouncer, self.registry))

if __name__ == '__main__':
    unittest.main()
