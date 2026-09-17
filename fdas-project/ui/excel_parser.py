"""Excel parsing and validation for device map uploads.

Pure-logic module — no Flask dependency, fully unit-testable.

Expected columns: device_code, location_name, zone, device_type, contacts
- contacts can be a JSON array string (e.g. '["+1234567890"]') or
  comma-separated phone numbers (e.g. '+1234567890, +0987654321').
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedRow:
    """A validated device_map row ready for upserting."""
    device_code: str
    location_name: str
    zone: str
    device_type: str
    contacts: list[str]


@dataclass
class ParseError:
    """A row that was skipped and why."""
    row_number: int  # 1-based (header is row 1)
    reason: str


@dataclass
class ParseResult:
    """Complete result of parsing a device map spreadsheet."""
    valid_rows: list[ParsedRow] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{len(self.valid_rows)} device(s) ready to update"]
        if self.errors:
            parts.append(f"{len(self.errors)} row(s) skipped")
        return ", ".join(parts)


REQUIRED_COLUMNS = {"device_code", "location_name", "zone", "device_type", "contacts"}


def _parse_contacts(raw: str) -> list[str]:
    """Parse a contacts cell — accepts JSON array or comma-separated."""
    raw = raw.strip()
    if not raw:
        return []

    # Try JSON first
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(c).strip() for c in parsed if str(c).strip()]
        except json.JSONDecodeError:
            pass

    # Fallback: comma-separated
    return [c.strip() for c in raw.split(",") if c.strip()]


def parse_device_map(file_path: str | Path) -> ParseResult:
    """Parse a .xlsx file and return validated rows + errors.

    Raises ValueError if openpyxl can't open the file or required columns
    are missing from the header row.
    """
    import openpyxl

    wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            raise ValueError("Workbook has no active sheet")

        result = ParseResult()

        # Read header row
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if header_row is None:
            raise ValueError("Spreadsheet is empty — no header row found")

        headers = [str(h).strip().lower() if h else "" for h in header_row]

        # Validate required columns exist
        missing = REQUIRED_COLUMNS - set(headers)
        if missing:
            raise ValueError(f"Missing required column(s): {', '.join(sorted(missing))}")

        col_idx = {name: i for i, name in enumerate(headers)}

        # Parse data rows
        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            try:
                raw = {col: str(row[col_idx[col]]).strip() if row[col_idx[col]] is not None else ""
                       for col in REQUIRED_COLUMNS}

                # Validate required fields are non-empty
                for field_name in ("device_code", "location_name", "zone", "device_type"):
                    if not raw[field_name]:
                        raise ValueError(f"missing {field_name}")

                contacts = _parse_contacts(raw["contacts"])
                if not contacts:
                    raise ValueError("contacts list is empty")

                result.valid_rows.append(ParsedRow(
                    device_code=raw["device_code"],
                    location_name=raw["location_name"],
                    zone=raw["zone"],
                    device_type=raw["device_type"],
                    contacts=contacts,
                ))
            except (ValueError, IndexError, TypeError) as e:
                result.errors.append(ParseError(row_number=row_num, reason=str(e)))

        return result
    finally:
        wb.close()

