import unittest
from cv.classify import classify_message


class TestClassify(unittest.TestCase):

    # --- fire ---
    def test_classify_fire_direct(self):
        # Exact wording from highlighted row on real panel
        self.assertEqual(classify_message("Fire    1/1   at 08:10"), "fire")

    def test_classify_first_fire(self):
        self.assertEqual(classify_message("First Fire  Zone 1   08:10 | #Zones"), "fire")

    def test_classify_latest_fire(self):
        self.assertEqual(classify_message("Latest Fire  Zone 1  08:10 |  1"), "fire")

    def test_classify_smoke(self):
        self.assertEqual(classify_message("smoke detected in zone"), "fire")

    # --- fault ---
    def test_classify_fault_direct(self):
        self.assertEqual(classify_message("Fault   1/1   at 08:10"), "fault")

    def test_classify_system_fault(self):
        self.assertEqual(classify_message("System Fault"), "fault")

    def test_classify_supply_fault(self):
        self.assertEqual(classify_message("Supply Fault"), "fault")

    def test_classify_earth_fault(self):
        self.assertEqual(classify_message("Earth Fault"), "fault")

    def test_classify_sounder_fault(self):
        self.assertEqual(classify_message("Sounder Fault"), "fault")

    # --- supervisory ---
    def test_classify_disablement(self):
        self.assertEqual(classify_message("Disablement   1/1"), "supervisory")

    def test_classify_sounders_disabled(self):
        self.assertEqual(classify_message("Sounders Disabled"), "supervisory")

    def test_classify_delayed_mode(self):
        self.assertEqual(classify_message("Delayed Mode"), "supervisory")

    # --- normal ---
    def test_classify_normal(self):
        self.assertEqual(classify_message("System Normal"), "normal")

    def test_classify_all_zones_secure(self):
        self.assertEqual(classify_message("All Zones Secure"), "normal")

    # --- unknown ---
    def test_classify_empty(self):
        self.assertEqual(classify_message(""), "unknown")

    def test_classify_random(self):
        self.assertEqual(classify_message("zzz random noise qqq"), "unknown")


if __name__ == "__main__":
    unittest.main()
