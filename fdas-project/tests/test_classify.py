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

    def test_classify_prealarm(self):
        # Exact real-world string from Bekaert Honeywell panel
        sample = "Prealarm Zone1 1/1 at20:29 Device: OPT L1 A053 ABV B100 MC SD L1/53 FIRE FAULT DISABLEMENT BUZZER MUTED SYSTEM FAULT DELAYED MODE SOUNDERS SILENCED SOUNDER FAULT SOUNDERS DISABLED EARTH FAULT POWER SUPPLY FAULT"
        self.assertEqual(classify_message(sample), "supervisory")

    # --- normal ---
    def test_classify_normal(self):
        self.assertEqual(classify_message("System Normal"), "normal")

    def test_classify_all_zones_secure(self):
        self.assertEqual(classify_message("All Zones Secure"), "normal")

    def test_classify_idle_status_menu_zero_fires(self):
        # Exact string from real panel idle screen that previously false-alarmed
        sample = "[Status] 1Fires (0 Fri 02/10/2026 15:06:17 3 Disabled 0 2Faults 4) 5: Actions 4 In Test 0 FIRE FAULT BUZZER MUTED SYSTEM FAULT DELAVED SOUNDERS SILENCED SOUNDER FAULT SUPPLY FAULT AREAL POWER"
        self.assertEqual(classify_message(sample), "normal")

    def test_classify_faceplate_only(self):
        # Faceplate painted row with no LCD alarm
        sample = "FIRE FAULT DISABLEMENT BUZZER MUTED SYSTEM FAULT DELAYED MODE SOUNDERS SILENCED"
        self.assertEqual(classify_message(sample), "normal")

    def test_classify_cabinet_branding(self):
        # Cabinet branding title without alarm
        self.assertEqual(classify_message("HONEYWELL FIRE ALARM SYSTEM"), "normal")

    # --- unknown ---
    def test_classify_empty(self):
        self.assertEqual(classify_message(""), "unknown")

    def test_classify_random(self):
        self.assertEqual(classify_message("zzz random noise qqq"), "unknown")


if __name__ == "__main__":
    unittest.main()
