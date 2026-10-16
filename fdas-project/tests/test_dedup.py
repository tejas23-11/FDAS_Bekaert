import unittest
import json
from pathlib import Path

from run_live import (
    is_duplicate_alert,
    mark_alert_active,
    clear_active_alert,
    _load_alert_state,
    _ALERT_STATE_FILE,
)
from backend.routing import get_route
from cv.classify import classify_message


class TestDeduplication(unittest.TestCase):

    def setUp(self):
        clear_active_alert()

    def tearDown(self):
        clear_active_alert()

    def test_dedup_initial_alert_allowed(self):
        # First time alert arrives -> not duplicate
        self.assertFalse(is_duplicate_alert("fire", "Zone 1"))

    def test_dedup_consecutive_same_alert_suppressed(self):
        # Simulate active fire in Zone 1
        mark_alert_active("fire", "Zone 1", "First Fire Zone 1 08:10")
        
        # Next frame sees the same fire in Zone 1 -> must be suppressed!
        self.assertTrue(is_duplicate_alert("fire", "Zone 1"))

    def test_dedup_different_zone_not_suppressed(self):
        # Active fire in Zone 1
        mark_alert_active("fire", "Zone 1", "First Fire Zone 1")

        # New fire in Zone 2 is a separate new event -> not suppressed
        self.assertFalse(is_duplicate_alert("fire", "Zone 2"))

    def test_dedup_different_message_type_not_suppressed(self):
        # Active fault
        mark_alert_active("fault", "Zone 1", "Fault in Zone 1")

        # Escalation to Fire -> must NOT be suppressed by the prior fault!
        self.assertFalse(is_duplicate_alert("fire", "Zone 1"))

    def test_dedup_cleared_on_normal(self):
        mark_alert_active("fire", "Zone 1", "First Fire Zone 1")
        self.assertTrue(is_duplicate_alert("fire", "Zone 1"))

        # Panel returns to normal
        clear_active_alert()

        # If a fire arrives again later, it must be allowed
        self.assertFalse(is_duplicate_alert("fire", "Zone 1"))

    def test_fault_routing_never_places_call(self):
        route = get_route("fault")
        self.assertTrue(route.send_sms, "Fault must send SMS")
        self.assertFalse(route.place_call, "Fault must NEVER place voice call")

    def test_fire_routing_places_call_and_sms(self):
        route = get_route("fire")
        self.assertTrue(route.send_sms)
        self.assertTrue(route.place_call)

    def test_honeywell_panel_fault_not_classified_as_fire(self):
        # Real-world Honeywell panel screens with fault text and branding
        self.assertEqual(classify_message("Fault 1/1 at 08:10 MCP L1 A012 Fire Panel"), "fault")
        self.assertEqual(classify_message("System Fault - Honeywell Fire Alarm System"), "fault")
        self.assertEqual(classify_message("Zone 1 Sounder Fault"), "fault")


if __name__ == "__main__":
    unittest.main()
