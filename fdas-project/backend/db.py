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

    # Default emergency contacts
    default_sms = ["+919545202660", "+919730814745", "+919561515546", "+919172319233"]
    default_call = ["+919545202660"]

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
            updated = False
            for num in default_sms:
                if num not in contacts:
                    contacts.append(num)
                    updated = True
            if updated:
                conn.execute(
                    "UPDATE notification_contacts SET contacts = ?, updated_at = ? WHERE list_type = 'sms'",
                    (json.dumps(contacts), datetime.now(timezone.utc).isoformat()),
                )
        except Exception:
            pass

    # Call contact (Sir's primary number for voice call alerts)
    row = conn.execute("SELECT contacts FROM notification_contacts WHERE list_type = 'call'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO notification_contacts (list_type, contacts, updated_at) VALUES ('call', ?, ?)",
            (json.dumps(default_call), datetime.now(timezone.utc).isoformat()),
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
