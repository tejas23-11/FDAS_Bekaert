"""
Seeds the device_map table and hardware/known_devices.txt with the test
device observed on the real Honeywell panel photo (Bekaert site, 2026-08).

Device code canonical form: "L1 A053"  (loop 1, detector A053)
Also seeds the short-form alias "L1 A053" from the OCR normalisation in
cv/validate.py so both formats resolve to the same DB row.

Run once before tests / after wiping the DB:
    python3 -m hardware.seed_device_map
"""

import json
from backend.db import get_connection, init_db
from pathlib import Path


# ---------------------------------------------------------------------------
# Test devices (replace / extend with the full commissioning list later)
# ---------------------------------------------------------------------------
_DEVICES = [
    {
        "device_code":   "L1 A053",
        "location_name": "Server Room - Zone 1",
        "zone":          "Zone 1",
        "device_type":   "OPT (optical smoke detector)",
        "contacts":      ["+1234567890", "+0987654321"],
    },
    {
        "device_code":   "L2 A138",
        "location_name": "Utility Room - BD - Zone 1",
        "zone":          "Zone 1",
        "device_type":   "MCP (manual call point)",
        "contacts":      ["+1234567890", "+0987654321"],
    },
]


def seed() -> None:
    init_db()
    conn = get_connection()

    for dev in _DEVICES:
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
        print(f"  Seeded {dev['device_code']} -> {dev['location_name']}")

    conn.commit()
    conn.close()

    # Write the known-devices file so cv/validate.py passes membership check
    kd_path = Path("hardware/known_devices.txt")
    kd_path.parent.mkdir(parents=True, exist_ok=True)
    with kd_path.open("w") as f:
        for dev in _DEVICES:
            f.write(dev["device_code"] + "\n")

    print("known_devices.txt updated.")


if __name__ == "__main__":
    seed()
