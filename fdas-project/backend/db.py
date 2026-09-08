"""DB connection + init helper. Owner: Member 3."""

import sqlite3
from pathlib import Path

DB_PATH = Path("backend/fdas_events.db")
SCHEMA_PATH = Path("backend/schema.sql")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Run once at startup (and safe to re-run — uses IF NOT EXISTS)."""
    conn = get_connection()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
