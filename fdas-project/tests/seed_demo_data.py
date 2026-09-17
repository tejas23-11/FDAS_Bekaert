"""Seed the database with realistic demo data for the dashboard demo.

Creates:
- Device map entries
- Several events (fire, fault, supervisory) across different times
- Health check records (mix of ok and fault)

Run: python -m tests.seed_demo_data
"""

import json
from datetime import datetime, timezone, timedelta
from backend.db import get_connection, init_db
from hardware.seed_device_map import seed as seed_devices


def seed_demo():
    # 1. Init DB + seed device map
    init_db()
    seed_devices()

    conn = get_connection()

    # 2. Add more devices for a realistic map
    extra_devices = [
        ("L1 B210", "Warehouse - Bay 3", "Zone 2", "HD (heat detector)", ["+1234567890"]),
        ("L3 A077", "Reception Lobby", "Zone 3", "OPT (optical smoke detector)", ["+1234567890", "+0987654321"]),
        ("L2 C045", "Electrical Room", "Zone 1", "MCP (manual call point)", ["+1112223333"]),
    ]
    for code, loc, zone, dtype, contacts in extra_devices:
        conn.execute(
            "INSERT OR REPLACE INTO device_map (device_code, location_name, zone, device_type, contacts) "
            "VALUES (?, ?, ?, ?, ?)",
            (code, loc, zone, dtype, json.dumps(contacts)),
        )

    # 3. Simulate events across the last 48 hours
    now = datetime.now(timezone.utc)
    events = [
        # Resolved fire event 2 days ago
        ("L2 A138", "fire", now - timedelta(hours=47), "Utility Room - BD - Zone 1", "Zone 1",
         "MCP (manual call point)", ["+1234567890", "+0987654321"], "+1234567890",
         "resolved", (now - timedelta(hours=46)).isoformat(), "sent", 1, "placed"),
        # Resolved fault event yesterday
        ("L1 B210", "fault", now - timedelta(hours=30), "Warehouse - Bay 3", "Zone 2",
         "HD (heat detector)", ["+1234567890"], "+1234567890",
         "resolved", (now - timedelta(hours=28)).isoformat(), "sent", 1, "not_applicable"),
        # Active supervisory from 6 hours ago
        ("L3 A077", "supervisory", now - timedelta(hours=6), "Reception Lobby", "Zone 3",
         "OPT (optical smoke detector)", ["+1234567890", "+0987654321"], "+1234567890",
         "active", None, "sent", 1, "not_applicable"),
        # Active fire alarm 1 hour ago
        ("L1 A053", "fire", now - timedelta(hours=1), "Server Room - Zone 1", "Zone 1",
         "OPT (optical smoke detector)", ["+1234567890", "+0987654321"], "+1234567890",
         "active", None, "sent", 1, "placed"),
        # Recent fault 20 minutes ago
        ("L2 C045", "fault", now - timedelta(minutes=20), "Electrical Room", "Zone 1",
         "MCP (manual call point)", ["+1112223333"], "+1112223333",
         "active", None, "sent", 1, "not_applicable"),
    ]

    for (code, mtype, ts, loc, zone, dtype, contacts, primary,
         status, resolved_at, sms, sms_attempts, call) in events:
        conn.execute(
            """INSERT INTO events (device_code, message_type, raw_text, detected_at, confidence,
                                   location_name, zone, device_type, contacts, primary_contact,
                                   status, resolved_at, sms_status, sms_attempts, call_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, mtype, f"Simulated {mtype} screen text for {code}", ts.isoformat(), 0.92,
             loc, zone, dtype, json.dumps(contacts), primary,
             status, resolved_at, sms, sms_attempts, call),
        )

    # 4. Seed health check data
    health_checks = [
        # Healthy heartbeat checks over the last hour
        ("heartbeat", "ok", None, (now - timedelta(minutes=30)).isoformat()),
        ("heartbeat", "ok", None, (now - timedelta(minutes=25)).isoformat()),
        ("heartbeat", "ok", None, (now - timedelta(minutes=20)).isoformat()),
        ("heartbeat", "ok", None, (now - timedelta(minutes=15)).isoformat()),
        ("heartbeat", "ok", None, (now - timedelta(minutes=10)).isoformat()),
        ("heartbeat", "ok", None, (now - timedelta(minutes=5)).isoformat()),
        ("heartbeat", "ok", None, now.isoformat()),
        # Camera checks
        ("camera", "ok", None, (now - timedelta(minutes=10)).isoformat()),
        ("camera", "ok", None, now.isoformat()),
        # Process checks
        ("process", "ok", None, (now - timedelta(minutes=10)).isoformat()),
        ("process", "ok", None, now.isoformat()),
    ]

    for check_name, status, detail, checked_at in health_checks:
        conn.execute(
            "INSERT INTO system_health (check_name, status, detail, checked_at) VALUES (?, ?, ?, ?)",
            (check_name, status, detail, checked_at),
        )

    conn.commit()
    conn.close()
    print("[OK] Demo data seeded successfully!")
    print(f"   - 5 devices in device_map")
    print(f"   - 5 events (2 resolved, 3 active)")
    print(f"   - 11 health check records (all healthy)")
    print(f"\nStart the dashboard:  python -m ui.app")
    print(f"Visit:  http://localhost:5000  (password: fdas)")


if __name__ == "__main__":
    seed_demo()
