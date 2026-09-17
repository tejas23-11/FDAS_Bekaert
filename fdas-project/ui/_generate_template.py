"""Generate the downloadable device map template spreadsheet.

Run once during development:
    python -m ui._generate_template
"""

import openpyxl
from pathlib import Path


def generate():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Device Map"

    headers = ["device_code", "location_name", "zone", "device_type", "contacts"]
    ws.append(headers)

    # Example row
    ws.append([
        "L1 A053",
        "Server Room - Zone 1",
        "Zone 1",
        "OPT (optical smoke detector)",
        '["+1234567890", "+0987654321"]',
    ])

    # Adjust column widths for readability
    widths = [15, 30, 12, 32, 35]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    out = Path(__file__).parent / "static" / "template.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    print(f"Template saved to {out}")


if __name__ == "__main__":
    generate()
