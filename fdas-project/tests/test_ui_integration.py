"""Integration tests for the FDAS Operator UI.

Uses Flask's test client to verify routes, auth, filtering, health
banner, and device map upload — all without starting a real server.
"""

import json
import os
import unittest
from pathlib import Path

import openpyxl

from backend.db import DB_PATH, get_connection, init_db
from hardware.seed_device_map import seed


def _create_app():
    """Create a test-configured Flask app."""
    from ui.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["FDAS_UI_PASSWORD_HASH"] = (
        # Pre-hashed "testpass" using werkzeug
        __import__("werkzeug.security", fromlist=["generate_password_hash"])
        .generate_password_hash("testpass")
    )
    return app


# Scratch dir for temp files
_SCRATCH = Path(__file__).parent / "_test_scratch"


def _make_xlsx(rows: list[list], filename: str = "upload.xlsx") -> Path:
    _SCRATCH.mkdir(exist_ok=True)
    path = _SCRATCH / filename
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    wb.save(str(path))
    return path


class TestUIIntegration(unittest.TestCase):

    def setUp(self):
        if DB_PATH.exists():
            os.remove(DB_PATH)
        init_db()
        seed()
        self.app = _create_app()
        self.client = self.app.test_client()

    def tearDown(self):
        if DB_PATH.exists():
            os.remove(DB_PATH)
        if _SCRATCH.exists():
            for f in _SCRATCH.iterdir():
                f.unlink()
            _SCRATCH.rmdir()

    def _login(self):
        """Helper: log in with the test password."""
        return self.client.post("/login", data={"password": "testpass"}, follow_redirects=True)

    # ---- Auth ----

    def test_unauthenticated_redirect(self):
        """GET / without login redirects to /login."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_login_success(self):
        """POST /login with correct password sets session and redirects to /."""
        resp = self.client.post("/login", data={"password": "testpass"})
        self.assertEqual(resp.status_code, 302)
        # After redirect, we should be able to access /
        resp2 = self.client.get("/")
        self.assertEqual(resp2.status_code, 200)

    def test_login_wrong_password(self):
        """POST /login with wrong password stays on login page."""
        resp = self.client.post("/login", data={"password": "wrong"}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Incorrect password", resp.data)

    def test_logout(self):
        """GET /logout clears session and redirects to /login."""
        self._login()
        resp = self.client.get("/logout")
        self.assertEqual(resp.status_code, 302)
        # After logout, / should redirect to login
        resp2 = self.client.get("/")
        self.assertEqual(resp2.status_code, 302)

    # ---- Dashboard ----

    def test_dashboard_no_health_data(self):
        """Dashboard shows 'unknown' banner when no health rows exist."""
        self._login()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Health Status Unknown", resp.data)

    def test_dashboard_healthy_banner(self):
        """Dashboard shows green banner when all checks are OK."""
        self._login()
        conn = get_connection()
        conn.execute(
            "INSERT INTO system_health (check_name, status, detail, checked_at) "
            "VALUES ('heartbeat', 'ok', NULL, '2026-09-05T10:00:00Z')"
        )
        conn.commit()
        conn.close()

        resp = self.client.get("/")
        self.assertIn(b"All Systems Normal", resp.data)

    def test_dashboard_fault_banner(self):
        """Dashboard shows red banner when a health check is in fault."""
        self._login()
        conn = get_connection()
        conn.execute(
            "INSERT INTO system_health (check_name, status, detail, checked_at) "
            "VALUES ('heartbeat', 'fault', 'Main pipeline heartbeat stale', '2026-09-05T10:00:00Z')"
        )
        conn.commit()
        conn.close()

        resp = self.client.get("/")
        self.assertIn(b"System Fault Detected", resp.data)
        self.assertIn(b"heartbeat stale", resp.data)

    # ---- Events ----

    def test_events_page_loads(self):
        """GET /events returns 200 with the events table."""
        self._login()
        resp = self.client.get("/events")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Event History", resp.data)

    def test_events_filter_by_type(self):
        """Filtering by message_type only returns matching events."""
        self._login()
        # Insert test events
        conn = get_connection()
        conn.execute(
            "INSERT INTO events (device_code, message_type, detected_at, status, sms_status, call_status) "
            "VALUES ('D1', 'fire', '2026-09-05T10:00:00Z', 'active', 'sent', 'placed')"
        )
        conn.execute(
            "INSERT INTO events (device_code, message_type, detected_at, status, sms_status, call_status) "
            "VALUES ('D2', 'fault', '2026-09-05T10:01:00Z', 'active', 'sent', 'not_applicable')"
        )
        conn.commit()
        conn.close()

        resp = self.client.get("/events?type=fire")
        self.assertIn(b"D1", resp.data)
        self.assertNotIn(b"D2", resp.data)

    def test_events_filter_by_status(self):
        """Filtering by status only returns matching events."""
        self._login()
        conn = get_connection()
        conn.execute(
            "INSERT INTO events (device_code, message_type, detected_at, status, sms_status, call_status) "
            "VALUES ('D1', 'fire', '2026-09-05T10:00:00Z', 'active', 'sent', 'placed')"
        )
        conn.execute(
            "INSERT INTO events (device_code, message_type, detected_at, status, sms_status, call_status) "
            "VALUES ('D2', 'fault', '2026-09-05T10:01:00Z', 'resolved', 'sent', 'not_applicable')"
        )
        conn.commit()
        conn.close()

        resp = self.client.get("/events?status=resolved")
        self.assertIn(b"D2", resp.data)
        self.assertNotIn(b"D1", resp.data)

    # ---- Upload ----

    def test_upload_page_loads(self):
        """GET /upload returns 200 with the current device map."""
        self._login()
        resp = self.client.get("/upload")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Device Map", resp.data)
        # Should show the seeded devices
        self.assertIn(b"L1 A053", resp.data)

    def test_upload_valid_xlsx(self):
        """Uploading a valid .xlsx updates device_map."""
        self._login()
        path = _make_xlsx([
            ["device_code", "location_name", "zone", "device_type", "contacts"],
            ["NEW001", "New Room", "Zone 9", "HD", '+999'],
        ])
        with open(path, "rb") as f:
            resp = self.client.post(
                "/upload",
                data={"file": (f, "test.xlsx")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"1 device(s) updated", resp.data)

        # Verify the device was inserted
        conn = get_connection()
        row = conn.execute("SELECT * FROM device_map WHERE device_code = 'NEW001'").fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["location_name"], "New Room")

    def test_upload_invalid_file(self):
        """Uploading a file without required columns shows an error."""
        self._login()
        path = _make_xlsx([
            ["device_code", "location_name"],  # missing columns
            ["D1", "Room 1"],
        ])
        with open(path, "rb") as f:
            resp = self.client.post(
                "/upload",
                data={"file": (f, "bad.xlsx")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Missing required column", resp.data)

    def test_upload_non_xlsx_rejected(self):
        """Uploading a non-.xlsx file shows an error."""
        self._login()
        _SCRATCH.mkdir(exist_ok=True)
        txt_path = _SCRATCH / "test.txt"
        txt_path.write_text("not a spreadsheet")
        with open(txt_path, "rb") as f:
            resp = self.client.post(
                "/upload",
                data={"file": (f, "test.txt")},
                content_type="multipart/form-data",
                follow_redirects=True,
            )

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Only .xlsx files", resp.data)


if __name__ == "__main__":
    unittest.main()
