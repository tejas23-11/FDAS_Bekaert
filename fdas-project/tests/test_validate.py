"""
Tests for cv/validate.py — device code extraction and validation.

Uses the real panel formats confirmed from the Bekaert site photo (2026-08):
  Long form:   "L1 A053"
  Short form:  "L1/53"
Both should normalise to canonical "L1 A053".
"""

import unittest
from cv.validate import extract_code, validate_code


class TestExtractCode(unittest.TestCase):

    def test_long_form_space_separated(self):
        """Canonical long form as it appears on the Device detail line."""
        code = extract_code("        L1 A053")
        self.assertEqual(code, "L1 A053")

    def test_short_form_slash(self):
        """Short form from the description line, normalised to long form."""
        code = extract_code("Device: OPT     ABV B100 MC SD L1/53")
        self.assertEqual(code, "L1 A053")

    def test_full_fire_screen_text(self):
        """Full multi-line OCR output from a fire screen."""
        text = (
            "First Fire  Zone 1          08:10 | #Zones\n"
            "Latest Fire  Zone 1         08:10 |    1\n"
            "Fire    1/1   at 08:10            << >>\n"
            "Zone  : 1\n"
            "Device: OPT     ABV B100 MC SD L1/53\n"
            "        L1 A053\n"
        )
        code = extract_code(text)
        self.assertEqual(code, "L1 A053")

    def test_returns_none_for_random_text(self):
        self.assertIsNone(extract_code("System Normal All Zones Secure"))

    def test_returns_none_for_empty(self):
        self.assertIsNone(extract_code(""))

    def test_case_insensitive(self):
        """OCR may return mixed case."""
        self.assertEqual(extract_code("l1 a053"), "L1 A053")


class TestValidateCode(unittest.TestCase):

    def test_none_is_invalid(self):
        self.assertFalse(validate_code(None))

    def test_empty_string_is_invalid(self):
        self.assertFalse(validate_code(""))

    def test_valid_when_no_known_list(self):
        """If known_devices.txt is empty/absent, any formatted code passes."""
        # Temporarily patch _known_devices to empty set
        import cv.validate as v
        orig = v._known_devices
        v._known_devices = set()
        try:
            self.assertTrue(validate_code("L1 A053"))
        finally:
            v._known_devices = orig

    def test_invalid_when_not_in_known_list(self):
        import cv.validate as v
        orig = v._known_devices
        v._known_devices = {"L1 A053"}
        try:
            self.assertFalse(validate_code("L9 Z999"))
        finally:
            v._known_devices = orig

    def test_valid_when_in_known_list(self):
        import cv.validate as v
        orig = v._known_devices
        v._known_devices = {"L1 A053"}
        try:
            self.assertTrue(validate_code("L1 A053"))
        finally:
            v._known_devices = orig


if __name__ == "__main__":
    unittest.main()
