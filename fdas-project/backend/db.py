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

    # Set default emergency contact if not already configured
    default_phone = ["+919545202660"]
    for list_type in ("sms", "call"):
        row = conn.execute("SELECT contacts FROM notification_contacts WHERE list_type = ?", (list_type,)).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO notification_contacts (list_type, contacts, updated_at) VALUES (?, ?, ?)",
                (list_type, json.dumps(default_phone), datetime.now(timezone.utc).isoformat()),
            )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
