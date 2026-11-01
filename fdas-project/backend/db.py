"""DB connection + init helper. Owner: Member 3."""

import sqlite3
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
DB_PATH = _THIS_DIR / "fdas_events.db"
SCHEMA_PATH = _THIS_DIR / "schema.sql"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Run once at startup (and safe to re-run — uses IF NOT EXISTS)."""
    import json
    from datetime import datetime, timezone

    conn = get_connection()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    # Default emergency contacts (name + phone dict format)
    default_sms = [
        {"name": "Contact 1", "phone": "+919545202660"},
        {"name": "Contact 2", "phone": "+919730814745"},
        {"name": "Contact 3", "phone": "+919561515546"},
        {"name": "Contact 4", "phone": "+919172319233"},
    ]
    default_call = [{"name": "Contact 1", "phone": "+919545202660"}]

    # Convenience list of phone numbers (used for device_map seeding below)
    default_sms_phones = [c["phone"] for c in default_sms]

    # Ensure all default SMS recipients are in notification_contacts
    row = conn.execute("SELECT contacts FROM notification_contacts WHERE list_type = 'sms'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO notification_contacts (list_type, contacts, updated_at) VALUES ('sms', ?, ?)",
            (json.dumps(default_sms), datetime.now(timezone.utc).isoformat()),
        )
    else:
        try:
            contacts = json.loads(row["contacts"])
            # Build set of existing phones (handle both plain strings and dicts)
            existing_phones = set()
            for c in contacts:
                if isinstance(c, dict):
                    existing_phones.add(c.get("phone", ""))
                else:
                    existing_phones.add(str(c))
            updated = False
            for entry in default_sms:
                phone = entry["phone"] if isinstance(entry, dict) else entry
                if phone not in existing_phones:
                    contacts.append(entry)
                    updated = True
            if updated:
                conn.execute(
                    "UPDATE notification_contacts SET contacts = ?, updated_at = ? WHERE list_type = 'sms'",
                    (json.dumps(contacts), datetime.now(timezone.utc).isoformat()),
                )
        except Exception:
            pass

    # Call contact (primary number for voice call alerts)
    row = conn.execute("SELECT contacts FROM notification_contacts WHERE list_type = 'call'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO notification_contacts (list_type, contacts, updated_at) VALUES ('call', ?, ?)",
            (json.dumps(default_call), datetime.now(timezone.utc).isoformat()),
        )

    # Seed empty test contact lists if not present
    for test_type in ("test_sms", "test_call"):
        conn.execute(
            "INSERT OR IGNORE INTO notification_contacts (list_type, contacts, updated_at) VALUES (?, '[]', ?)",
            (test_type, datetime.now(timezone.utc).isoformat()),
        )

    # System config defaults (test_mode off by default)
    conn.execute(
        "INSERT OR IGNORE INTO system_config (key, value, updated_at) VALUES ('test_mode', 'off', ?)",
        (datetime.now(timezone.utc).isoformat(),)
    )

    # Seed default Bekaert device map if empty
    try:
        count_row = conn.execute("SELECT COUNT(*) as cnt FROM device_map").fetchone()
        if not count_row or count_row["cnt"] == 0:
            default_devices = [
                ("L1 A053", "B Drawing Area - ABV B100 MC", "B Drawing Area", "SD (smoke detector)", json.dumps(default_sms_phones)),
                ("L2 A138", "Utility Room - BD - Zone 1", "Zone 1", "MCP (manual call point)", json.dumps(default_sms_phones)),
                ("L1 A101", "1ST AID RM", "Zone 1", "MCP (manual call point)", json.dumps(default_sms_phones)),
                ("L1/101", "1ST AID RM", "Zone 1", "MCP (manual call point)", json.dumps(default_sms_phones)),
                ("L1/53", "B Drawing Area - ABV B100 MC", "B Drawing Area", "SD (smoke detector)", json.dumps(default_sms_phones)),
            ]
            conn.executemany(
                "INSERT OR IGNORE INTO device_map (device_code, location_name, zone, device_type, contacts) VALUES (?, ?, ?, ?, ?)",
                default_devices,
            )
    except Exception as e:
        print(f"  [warn] Could not auto-seed device_map: {e}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
