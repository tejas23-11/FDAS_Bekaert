import unittest
from backend.routing import get_route

class TestRouting(unittest.TestCase):
    def test_route_fire(self):
        route = get_route("fire")
        self.assertTrue(route.send_sms)
        self.assertTrue(route.place_call)

    def test_route_fault(self):
        route = get_route("fault")
        self.assertTrue(route.send_sms)
        self.assertFalse(route.place_call)

    def test_route_supervisory(self):
        route = get_route("supervisory")
        self.assertFalse(route.send_sms)
        self.assertFalse(route.place_call)

    def test_route_normal(self):
        route = get_route("normal")
        self.assertFalse(route.send_sms)
        self.assertFalse(route.place_call)

    def test_clean_panel_ocr_for_sms(self):
        from notify.sms_gateway import clean_panel_ocr_for_sms
        sample = "Fire 1/1 at 16:07 Zone 1 Device: L1 A110 QA LAB RM HD L1/110 FIRE FAULT DISABLEMENT BUZZER MUTED SYSTEM FAULT DELAYED MODE SOUNDERS SILENCED"
        cleaned = clean_panel_ocr_for_sms(sample)
        self.assertIn("Fire 1/1 at 16:07", cleaned)
        self.assertIn("L1 A110", cleaned)
        self.assertIn("QA LAB RM", cleaned)
        self.assertNotIn("BUZZER MUTED", cleaned)
        self.assertNotIn("SOUNDERS SILENCED", cleaned)


if __name__ == '__main__':
    unittest.main()
