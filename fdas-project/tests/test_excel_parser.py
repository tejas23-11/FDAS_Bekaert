"""Unit tests for ui/excel_parser.py.

Tests the pure-logic Excel parsing and validation independently of Flask.
"""

import json
import os
import unittest
from pathlib import Path

import openpyxl

from ui.excel_parser import parse_device_map, ParseResult


# All temp files go in a scratch directory next to this test file.
_SCRATCH = Path(__file__).parent / "_test_scratch"


def _make_xlsx(rows: list[list], filename: str = "test.xlsx") -> Path:
    """Helper: create a .xlsx file with the given rows (first row = header)."""
    _SCRATCH.mkdir(exist_ok=True)
    path = _SCRATCH / filename
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(str(path))
    return path


class TestExcelParser(unittest.TestCase):

    def tearDown(self):
        # Clean up scratch files after each test.
        if _SCRATCH.exists():
            for f in _SCRATCH.iterdir():
                try:
                    f.unlink()
                except PermissionError:
                    pass  # Windows: file may still be locked by openpyxl
            try:
                _SCRATCH.rmdir()
            except OSError:
                pass

    # ----- Happy path -----

    def test_valid_spreadsheet(self):
        """A well-formed spreadsheet produces correct parsed rows."""
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type", "contacts"],
            ["L1 A053", "Server Room", "Zone 1", "OPT", '["+1234567890"]'],
            ["L2 A138", "Utility Room", "Zone 2", "MCP", "+111, +222"],
        ])
        result = parse_device_map(path)

        self.assertEqual(len(result.valid_rows), 2)
        self.assertEqual(len(result.errors), 0)
        self.assertEqual(result.valid_rows[0].device_code, "L1 A053")
        self.assertEqual(result.valid_rows[0].contacts, ["+1234567890"])
        self.assertEqual(result.valid_rows[1].contacts, ["+111", "+222"])

    def test_contacts_json_array(self):
        """Contacts column parsed as a JSON array."""
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type", "contacts"],
            ["D001", "Lobby", "Z1", "SD", '["+111", "+222"]'],
        ])
        result = parse_device_map(path)

        self.assertEqual(len(result.valid_rows), 1)
        self.assertEqual(result.valid_rows[0].contacts, ["+111", "+222"])

    def test_contacts_comma_separated(self):
        """Contacts column parsed as comma-separated values."""
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type", "contacts"],
            ["D001", "Lobby", "Z1", "SD", "+111, +222, +333"],
        ])
        result = parse_device_map(path)

        self.assertEqual(len(result.valid_rows), 1)
        self.assertEqual(result.valid_rows[0].contacts, ["+111", "+222", "+333"])

    # ----- Error cases -----

    def test_missing_required_column(self):
        """Spreadsheet without a required column raises ValueError."""
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type"],  # no contacts
            ["L1 A053", "Server Room", "Zone 1", "OPT"],
        ])
        with self.assertRaises(ValueError) as ctx:
            parse_device_map(path)
        self.assertIn("contacts", str(ctx.exception))

    def test_empty_spreadsheet(self):
        """Spreadsheet with no header row raises ValueError."""
        path = _make_xlsx([])
        with self.assertRaises(ValueError):
            parse_device_map(path)

    def test_row_with_blank_zone_skipped(self):
        """A row with a blank required field is skipped with an error."""
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type", "contacts"],
            ["L1 A053", "Server Room", "Zone 1", "OPT", '["+111"]'],
            ["L2 A138", "Utility Room", "", "MCP", '["+222"]'],   # blank zone
            ["L3 B200", "Office", "Zone 3", "HD", '["+333"]'],
        ])
        result = parse_device_map(path)

        self.assertEqual(len(result.valid_rows), 2)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].row_number, 3)
        self.assertIn("zone", result.errors[0].reason.lower())

    def test_row_with_empty_contacts_skipped(self):
        """A row with an empty contacts field is skipped."""
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type", "contacts"],
            ["L1 A053", "Server Room", "Zone 1", "OPT", ""],
        ])
        result = parse_device_map(path)

        self.assertEqual(len(result.valid_rows), 0)
        self.assertEqual(len(result.errors), 1)

    def test_duplicate_device_code_both_kept(self):
        """Duplicate device_codes produce two valid rows (upsert is the view's job)."""
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type", "contacts"],
            ["L1 A053", "Server Room", "Zone 1", "OPT", '["+111"]'],
            ["L1 A053", "New Location", "Zone 2", "OPT", '["+222"]'],
        ])
        result = parse_device_map(path)

        # Parser returns both — the view/DB handles dedup via INSERT OR REPLACE.
        self.assertEqual(len(result.valid_rows), 2)
        self.assertEqual(len(result.errors), 0)

    def test_summary_message(self):
        """ParseResult.summary produces a human-readable string."""
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type", "contacts"],
            ["D1", "Room 1", "Z1", "SD", "+111"],
            ["D2", "", "Z2", "SD", "+222"],  # missing location
        ])
        result = parse_device_map(path)

        self.assertIn("1 device", result.summary)
        self.assertIn("1 row", result.summary)


if __name__ == "__main__":
    unittest.main()
