"""Excel and CSV parsing for device map uploads.

Pure-logic module — no Flask dependency, fully unit-testable.

Supports:
  1. Simple 2-column CSV or Excel (ID/Code, Location) — recommended & simplest format!
  2. Standard 5-column FDAS template (device_code, location_name, zone, device_type, contacts)
  3. Bekaert multi-sheet Appliance Location format
"""

from __future__ import annotations

import csv
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
    """Complete result of parsing a device map spreadsheet or CSV."""
    valid_rows: list[ParsedRow] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)

    @property
    def summary(self) -> str:
        parts = [f"{len(self.valid_rows)} device(s) ready to update"]
        if self.errors:
            parts.append(f"{len(self.errors)} row(s) skipped")
        return ", ".join(parts)


REQUIRED_COLUMNS = {"device_code", "location_name", "zone", "device_type", "contacts"}

# Device type abbreviation -> full name mapping
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
    """Extract canonical device code (e.g. 'L1 A101') from panel address string.

    Handles:
      - 'L1/101', 'L1 / 101', 'L1/01', 'L1/1'
      - 'MCPL1/101', 'SDL1/53' (attached prefixes)
      - 'L1A101', 'L1 A101', 'L1 A053'
      - 'L1-101', 'L1 - 101'
    """
    if not address:
        return None
    addr = str(address).strip()

    # 1. Match L<loop> / <num> or L<loop> - <num> (e.g. L1/101, MCPL1/101, L1-101)
    m = re.search(r'L(\d+)\s*[/\\-]\s*([A-Za-z]?\s*\d{1,3})\b', addr, re.IGNORECASE)
    if m:
        loop = m.group(1)
        raw_num = re.sub(r'^[A-Za-z\s]+', '', m.group(2))
        if raw_num.isdigit():
            return f"L{loop} A{raw_num.zfill(3)}"

    # 2. Match canonical L<loop> A<num> or L<loop><alpha><num> (e.g. L1A101, L1 A101)
    m = re.search(r'L(\d+)\s*([A-Za-z])\s*(\d{1,3})\b', addr, re.IGNORECASE)
    if m:
        loop = m.group(1)
        num = m.group(3).zfill(3)
        return f"L{loop} A{num}"

    # 3. Match address with loop and 2-3 digit number separated by space
    m = re.search(r'\bL(\d+)\s+(\d{1,3})\b', addr, re.IGNORECASE)
    if m:
        loop = m.group(1)
        num = m.group(2).zfill(3)
        return f"L{loop} A{num}"

    return None


def _extract_device_type(address: str) -> str:
    """Infer device type from abbreviation in the address string."""
    addr_upper = f" {str(address).upper()} "
    for abbr in sorted(_DEVICE_TYPES.keys(), key=len, reverse=True):
        if f" {abbr} " in addr_upper or addr_upper.strip().endswith(f" {abbr}"):
            return _DEVICE_TYPES[abbr]
    return "Unknown"


def _parse_contacts(raw: str) -> list[str]:
    """Parse a contacts cell — accepts JSON array or comma-separated."""
    raw = str(raw).strip()
    if not raw:
        return []

    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return ["".join(c for c in str(item).strip() if c.isdigit() or c == "+") for item in parsed if item]
        except json.JSONDecodeError:
            pass

    numbers = []
    for c in raw.split(","):
        cleaned = "".join(ch for ch in c.strip() if ch.isdigit() or ch == "+")
        if cleaned:
            numbers.append(cleaned)
    return numbers


def _parse_2col_data(rows: list[list[str]], default_contacts: list[str]) -> ParseResult:
    """Parse simple 2-column data [Code/ID, Location]."""
    result = ParseResult()
    if not rows:
        return result

    header = [c.strip().lower() for c in rows[0]]
    start_row = 1 if any(h in ("id", "code", "device", "device_code", "address", "location", "sensor") for h in header) else 0

    seen = set()
    for row_num, row in enumerate(rows[start_row:], start=start_row + 1):
        if len(row) < 2:
            continue
        raw_code = str(row[0]).strip()
        raw_loc = str(row[1]).strip()
        if not raw_code:
            continue

        canon_code = _extract_device_code(raw_code) or raw_code.upper()
        if canon_code in seen:
            continue
        seen.add(canon_code)

        device_type = _extract_device_type(raw_code)
        zone = str(row[2]).strip() if len(row) > 2 and str(row[2]).strip() else raw_loc

        result.valid_rows.append(ParsedRow(
            device_code=canon_code,
            location_name=raw_loc or "Unknown location",
            zone=zone or "Unknown zone",
            device_type=device_type,
            contacts=default_contacts,
        ))

    return result


def _parse_csv_file(file_path: Path | str, default_contacts: list[str]) -> ParseResult:
    """Parse a CSV file (auto-detects 2-column or standard 5-column format)."""
    with open(str(file_path), "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        rows = [row for row in reader if row and any(str(c).strip() for c in row)]

    if not rows:
        raise ValueError("CSV file is empty")

    header = [str(c).strip().lower() for c in rows[0]]

    # If it has the standard 5 columns
    if REQUIRED_COLUMNS.issubset(set(header)):
        col_idx = {name: header.index(name) for name in REQUIRED_COLUMNS}
        result = ParseResult()
        for row_num, row in enumerate(rows[1:], start=2):
            try:
                raw = {col: str(row[col_idx[col]]).strip() if col_idx[col] < len(row) else "" for col in REQUIRED_COLUMNS}
                for fld in ("device_code", "location_name", "zone", "device_type"):
                    if not raw[fld]:
                        raise ValueError(f"missing {fld}")
                contacts = _parse_contacts(raw["contacts"])
                if not contacts:
                    raise ValueError("contacts list is empty")
                canon_code = _extract_device_code(raw["device_code"]) or raw["device_code"].upper()
                result.valid_rows.append(ParsedRow(
                    device_code=canon_code,
                    location_name=raw["location_name"],
                    zone=raw["zone"],
                    device_type=raw["device_type"],
                    contacts=contacts,
                ))
            except Exception as e:
                result.errors.append(ParseError(row_number=row_num, reason=str(e)))
        return result

    # Otherwise, treat as simple 2-column format (Code, Location)
    return _parse_2col_data(rows, default_contacts)


def parse_device_map(file_path: str | Path, default_contacts: list[str] | None = None) -> ParseResult:
    """Parse a .csv or .xlsx file and return validated rows + errors.

    Supports:
      - 2-column CSV/Excel (ID, Location)
      - Standard 5-column FDAS template
      - Bekaert Appliance_location format
    """
    path = Path(file_path)
    if default_contacts is None:
        default_contacts = ["+919545202660", "+919730814745", "+919561515546", "+919172319233"]

    if path.suffix.lower() == ".csv":
        return _parse_csv_file(path, default_contacts)

    # Excel (.xlsx) parsing
    import openpyxl

    wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
    try:
        ws = wb.active
        if ws is None:
            raise ValueError("Workbook has no active sheet")

        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if header_row is None:
            raise ValueError("Spreadsheet is empty — no header row found")

        headers = [str(h).strip().lower() if h else "" for h in header_row]

        # 1. Standard 5-column format
        if "device_code" in headers:
            missing = REQUIRED_COLUMNS - set(headers)
            if missing:
                raise ValueError(f"Missing required column(s): {', '.join(sorted(missing))}")

            col_idx = {name: i for i, name in enumerate(headers)}
            result = ParseResult()
            for row_num, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                try:
                    raw = {col: str(row[col_idx[col]]).strip() if col_idx[col] < len(row) and row[col_idx[col]] is not None else ""
                           for col in REQUIRED_COLUMNS}
                    for fld in ("device_code", "location_name", "zone", "device_type"):
                        if not raw[fld]:
                            raise ValueError(f"missing {fld}")
                    contacts = _parse_contacts(raw["contacts"])
                    if not contacts:
                        raise ValueError("contacts list is empty")
                    canon_code = _extract_device_code(raw["device_code"]) or raw["device_code"].upper()
                    result.valid_rows.append(ParsedRow(
                        device_code=canon_code,
                        location_name=raw["location_name"],
                        zone=raw["zone"],
                        device_type=raw["device_type"],
                        contacts=contacts,
                    ))
                except Exception as e:
                    result.errors.append(ParseError(row_number=row_num, reason=str(e)))
            return result

        # 2. Simple 2-column Excel (ID, Location) or Bekaert format
        rows = []
        for r in ws.iter_rows(values_only=True):
            if r and any(c is not None and str(c).strip() for c in r):
                rows.append([str(c).strip() if c is not None else "" for c in r])

        if not rows:
            raise ValueError("Spreadsheet has no data")

        # If it's Bekaert format with 'address in fire panel'
        if any("address in fire panel" in str(c).lower() for c in rows[0]):
            result = ParseResult()
            seen_codes = set()
            for row_num, row in enumerate(rows[1:], start=2):
                if len(row) < 3:
                    continue
                # Handle layout
                addr = row[2] if len(row) >= 5 and not row[0] else row[1]
                loc = row[3] if len(row) >= 5 and not row[0] else row[2]
                desc = row[4] if len(row) >= 5 and not row[0] else (row[3] if len(row) > 3 else "")

                if not addr or "address in fire panel" in addr.lower():
                    continue
                code = _extract_device_code(addr)
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                loc_name = f"{loc} - {desc}" if desc and desc != loc else loc
                result.valid_rows.append(ParsedRow(
                    device_code=code,
                    location_name=loc_name or "Unknown location",
                    zone=loc or "Unknown zone",
                    device_type=_extract_device_type(addr),
                    contacts=default_contacts,
                ))
            return result

        # Simple 2-column fallback
        return _parse_2col_data(rows, default_contacts)
    finally:
        wb.close()
