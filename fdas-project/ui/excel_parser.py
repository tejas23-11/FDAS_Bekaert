"""Excel parsing and validation for device map uploads.

Pure-logic module — no Flask dependency, fully unit-testable.

Supports TWO upload formats:
  1. Standard FDAS format (columns: device_code, location_name, zone, device_type, contacts)
  2. Bekaert Appliance Location format (columns: SR.NO, ADDRESS IN FIRE PANEL, LOCATION, BRIEF DESCRIPTION)
     — contacts default to the global emergency contact list already in the DB.

The format is auto-detected from the header row.
"""

from __future__ import annotations

import json
import re
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

# Bekaert Excel column names (case-insensitive)
_BEKAERT_HEADERS = {"sr.no", "address in fire panel", "location", "brief description"}

# Device type abbreviation -> full name mapping (from seed_device_map)
_DEVICE_TYPES = {
    "HD":  "HD (heat detector)",
    "SD":  "SD (smoke detector)",
    "MD":  "MD (multi-detector)",
    "MCP": "MCP (manual call point)",
    "BS":  "BS (beam smoke detector)",
    "BMS": "BMS (building management system)",
    "SB":  "SB (sounder beacon)",
}


def _extract_device_code(address: str) -> str | None:
    """Extract canonical device code from Bekaert panel address string.
    e.g. 'QA LAB RM HD L1/01' -> 'L1 A001'
    """
    m = re.search(r'L(\d+)\s*/\s*(\d{2,3})', address)
    if not m:
        return None
    loop = m.group(1)
    num = m.group(2).zfill(3)
    return f"L{loop} A{num}"


def _extract_device_type(address: str) -> str:
    """Infer device type from abbreviation in the Bekaert address string."""
    addr_upper = f" {address.upper()} "
    for abbr in sorted(_DEVICE_TYPES.keys(), key=len, reverse=True):
        if f" {abbr} " in addr_upper or addr_upper.strip().endswith(f" {abbr}"):
            return _DEVICE_TYPES[abbr]
    return "Unknown"


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


def _parse_bekaert_format(ws, default_contacts: list[str]) -> ParseResult:
    """Parse the real Bekaert Appliance_location.xlsx format.

    Columns: [None/empty, SR.NO, ADDRESS IN FIRE PANEL, LOCATION, BRIEF DESCRIPTION]
    """
    result = ParseResult()
    seen_codes: set[str] = set()

    for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if len(row) < 4:
            continue

        # Handle both 4-col and 5-col layouts (some sheets have a leading blank col)
        if len(row) >= 5 and row[0] is None:
            address = row[2]
            location = row[3]
            description = row[4] if len(row) > 4 else None
        else:
            address = row[1]
            location = row[2]
            description = row[3] if len(row) > 3 else None

        if address is None or str(address).strip() == "" or str(address).strip() == "ADDRESS IN FIRE PANEL":
            continue

        address_str = str(address).strip()
        location_str = str(location).strip() if location else "Unknown"
        description_str = str(description).strip() if description else ""

        code = _extract_device_code(address_str)
        if not code:
            result.errors.append(ParseError(row_number=row_num, reason=f"No device code in address: {address_str!r}"))
            continue

        if code in seen_codes:
            continue
        seen_codes.add(code)

        if description_str and description_str != location_str:
            location_name = f"{location_str} - {description_str}"
        else:
            location_name = location_str

        device_type = _extract_device_type(address_str)

        result.valid_rows.append(ParsedRow(
            device_code=code,
            location_name=location_name,
            zone=location_str,
            device_type=device_type,
            contacts=default_contacts,
        ))

    return result


def parse_device_map(file_path: str | Path, default_contacts: list[str] | None = None) -> ParseResult:
    """Parse a .xlsx file and return validated rows + errors.

    Auto-detects format:
    - If header contains 'address in fire panel' → Bekaert format
    - Otherwise → standard FDAS format (device_code, location_name, zone, device_type, contacts)

    Raises ValueError if openpyxl can't open the file or required columns are missing.
    """
    import openpyxl

    if default_contacts is None:
        default_contacts = ["+919545202660", "+919730814745", "+919561515546", "+919172319233"]

    wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            raise ValueError("Workbook has no active sheet")

        # Read header row
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if header_row is None:
            raise ValueError("Spreadsheet is empty — no header row found")

        headers_lower = {str(h).strip().lower() for h in header_row if h}

        # Auto-detect format
        if "address in fire panel" in headers_lower:
            # Bekaert format
            return _parse_bekaert_format(ws, default_contacts)

        # Standard FDAS format
        headers = [str(h).strip().lower() if h else "" for h in header_row]
        missing = REQUIRED_COLUMNS - set(headers)
        if missing:
            raise ValueError(
                f"Missing required column(s): {', '.join(sorted(missing))}. "
                f"Either use the standard template (columns: device_code, location_name, zone, device_type, contacts) "
                f"or upload the Bekaert 'Appliance_location.xlsx' directly."
            )

        col_idx = {name: i for i, name in enumerate(headers)}
        result = ParseResult()

        for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            try:
                raw = {col: str(row[col_idx[col]]).strip() if row[col_idx[col]] is not None else ""
                       for col in REQUIRED_COLUMNS}

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
