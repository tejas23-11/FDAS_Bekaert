"""
Seeds the device_map table and hardware/known_devices.txt from the real
Bekaert appliance location spreadsheet.

Source: C:\\Tejas\\Projects\\FDAS_bekaert\\Appliance_location.xlsx
        (113 devices across Loop 1 and Loop 2)

The Excel has columns: SR.NO, ADDRESS IN FIRE PANEL, LOCATION, BRIEF DESCRIPTION
Device codes are extracted from the ADDRESS column (e.g. "QA LAB RM HD L1/01" -> "L1 A001").
Device types are inferred from abbreviations in the address (HD, SD, MD, MCP, BS, BMS).

Contacts are placeholder for now — update via the Operator Dashboard
(/upload page) or edit _DEFAULT_CONTACTS below.

Run once after cloning / after wiping the DB:
    python3 -m hardware.seed_device_map
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from backend.db import get_connection, init_db

# ── Configuration ─────────────────────────────────────────────────────

# Path to the real Bekaert appliance location spreadsheet.
# On the Pi, copy this file or adjust the path.
EXCEL_PATH = Path(r"C:\Tejas\Projects\FDAS_bekaert\Appliance_location.xlsx")

# Placeholder contacts — update with real numbers before going live.
_DEFAULT_CONTACTS = ["+1234567890", "+0987654321"]

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
    """Extract canonical device code from panel address string.

    Examples:
        "QA LAB RM HD L1/01"    -> "L1 A001"
        "ADMIN OFF 1 SD L1 /23" -> "L1 A023"
        "MZ EPR C AF MD L2/01"  -> "L2 A001"
    """
    m = re.search(r'L(\d+)\s*/\s*(\d{2,3})', address)
    if not m:
        return None
    loop = m.group(1)
    num = m.group(2).zfill(3)
    return f"L{loop} A{num}"


def _extract_device_type(address: str) -> str:
    """Infer device type from abbreviation in the address string."""
    addr_upper = f" {address.upper()} "
    # Check longest abbreviations first to avoid partial matches
    for abbr in sorted(_DEVICE_TYPES.keys(), key=len, reverse=True):
        if f" {abbr} " in addr_upper or addr_upper.strip().endswith(f" {abbr}"):
            return _DEVICE_TYPES[abbr]
    return "Unknown"


def _parse_excel(excel_path: Path) -> list[dict]:
    """Parse the Bekaert appliance location spreadsheet into device records."""
    import openpyxl

    wb = openpyxl.load_workbook(str(excel_path), data_only=True)
    ws = wb.active

    devices = []
    seen_codes = set()  # Deduplicate

    for row in ws.iter_rows(min_row=2, values_only=True):
        # Columns: [None, SR.NO, ADDRESS, LOCATION, DESCRIPTION] and rows as well
        if len(row) < 5:
            continue

        sr_no = row[1]
        address = row[2]
        location = row[3]
        description = row[4]

        # Skip header rows and empty rows
        if address is None or str(address).strip() == "" or str(address).strip() == "ADDRESS IN FIRE PANEL":
            continue

        address = str(address).strip()
        location = str(location).strip() if location else "Unknown"
        description = str(description).strip() if description else ""

        # Extract device code
        code = _extract_device_code(address)
        if not code:
            print(f"  [skip] No device code in: {address!r}")
            continue

        # Deduplicate
        if code in seen_codes:
            print(f"  [skip] Duplicate code {code} in: {address!r}")
            continue
        seen_codes.add(code)

        # Build location name from LOCATION + DESCRIPTION
        if description and description != location:
            location_name = f"{location} - {description}"
        else:
            location_name = location

        device_type = _extract_device_type(address)

        devices.append({
            "device_code": code,
            "location_name": location_name,
            "zone": location,               # Use the LOCATION column as zone
            "device_type": device_type,
            "panel_address": address,        # Keep original for reference
            "contacts": _DEFAULT_CONTACTS,
        })

    wb.close()
    return devices


def seed() -> None:
    """Parse the Excel file and seed the database."""
    init_db()

    # Try to load from Excel
    if EXCEL_PATH.exists():
        print(f"  Loading from: {EXCEL_PATH}")
        devices = _parse_excel(EXCEL_PATH)
    else:
        # Fallback: check if Excel was copied to the project
        alt_path = Path("hardware/Appliance_location.xlsx")
        if alt_path.exists():
            print(f"  Loading from: {alt_path}")
            devices = _parse_excel(alt_path)
        else:
            print(f"  [!!] Excel not found at {EXCEL_PATH}")
            print(f"       Copy it to hardware/Appliance_location.xlsx or update EXCEL_PATH")
            print(f"       Falling back to hardcoded test devices...")
            devices = [
                {
                    "device_code": "L1 A053",
                    "location_name": "B Drawing Area - ABV B100 MC",
                    "zone": "B Drawing Area",
                    "device_type": "SD (smoke detector)",
                    "contacts": _DEFAULT_CONTACTS,
                },
                {
                    "device_code": "L2 A138",
                    "location_name": "Utility Room - BD - Zone 1",
                    "zone": "Zone 1",
                    "device_type": "MCP (manual call point)",
                    "contacts": _DEFAULT_CONTACTS,
                },
            ]

    # Supplemental devices: seen on the real panel photo but not in
    # the Appliance_location.xlsx spreadsheet (possibly added later
    # or from a different commissioning batch).
    _SUPPLEMENTAL = [
        {
            "device_code": "L2 A138",
            "location_name": "Utility Room - BD",
            "zone": "Utility Room",
            "device_type": "MCP (manual call point)",
            "contacts": _DEFAULT_CONTACTS,
        },
    ]
    existing_codes = {d["device_code"] for d in devices}
    for sup in _SUPPLEMENTAL:
        if sup["device_code"] not in existing_codes:
            devices.append(sup)
            print(f"  [+] Added supplemental device: {sup['device_code']}")

    # Seed the database
    conn = get_connection()
    for dev in devices:
        conn.execute(
            "INSERT OR REPLACE INTO device_map "
            "(device_code, location_name, zone, device_type, contacts) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                dev["device_code"],
                dev["location_name"],
                dev["zone"],
                dev["device_type"],
                json.dumps(dev["contacts"]),
            ),
        )
    conn.commit()
    conn.close()
    print(f"\n  Seeded {len(devices)} devices into device_map table.")

    # Write the known-devices file so cv/validate.py passes membership check
    kd_path = Path("hardware/known_devices.txt")
    kd_path.parent.mkdir(parents=True, exist_ok=True)
    with kd_path.open("w") as f:
        for dev in devices:
            f.write(dev["device_code"] + "\n")

    print(f"  known_devices.txt updated with {len(devices)} entries.")

    # Print summary by zone
    from collections import Counter
    zone_counts = Counter(d["zone"] for d in devices)
    type_counts = Counter(d["device_type"] for d in devices)
    print(f"\n  --- By Zone ---")
    for zone, count in zone_counts.most_common():
        print(f"    {zone}: {count} devices")
    print(f"\n  --- By Type ---")
    for dtype, count in type_counts.most_common():
        print(f"    {dtype}: {count}")


if __name__ == "__main__":
    seed()
