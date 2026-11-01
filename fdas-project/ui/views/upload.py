"""Device Map upload page — Excel upload + validation + upsert.

Accepts a .xlsx file, validates it via excel_parser, upserts valid rows
into device_map, and shows a plain-English summary of what happened.

Also provides separate management of:
  - Global SMS and Call contact lists (name + phone format)
  - Test SMS and Call contact lists (used when test mode is active)
  - A test mode toggle (when on, notifications go to test contacts only)
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from backend.db import get_connection
from ui.auth import login_required
from ui.excel_parser import parse_device_map

upload_bp = Blueprint("upload", __name__)

_TEMPLATE_PATH = Path(__file__).parent.parent / "static" / "template.xlsx"


# ── Helpers ──────────────────────────────────────────────────────────

def _fetch_devices() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT device_code, location_name, zone, device_type, contacts FROM device_map ORDER BY device_code"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _fetch_contact_list(list_type: str) -> list[dict]:
    """Return contacts for a given list_type as list of dicts with 'name' and 'phone'.

    Handles both old format (plain string list) and new format (dict list)
    for backward compatibility.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT contacts FROM notification_contacts WHERE list_type = ?",
        (list_type,),
    ).fetchone()
    conn.close()
    if row:
        try:
            raw = json.loads(row["contacts"])
            if not isinstance(raw, list):
                return []
            result = []
            for item in raw:
                if isinstance(item, dict):
                    result.append({
                        "name": item.get("name", ""),
                        "phone": item.get("phone", ""),
                    })
                else:
                    # Migrate plain string to dict
                    result.append({"name": "", "phone": str(item)})
            return result
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _save_contact_list(list_type: str, contacts: list[dict]) -> None:
    """Upsert the contact list (name+phone dicts) for a given list_type."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO notification_contacts (list_type, contacts, updated_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(list_type) DO UPDATE SET contacts = excluded.contacts, updated_at = excluded.updated_at",
        (list_type, json.dumps(contacts), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def _parse_contacts(raw: str) -> list[dict]:
    """Parse a textarea of contacts into a list of {name, phone} dicts.

    Supported input formats (one per line or comma-separated):
        Name: +91XXXXXXXXXX
        Name, +91XXXXXXXXXX
        +91XXXXXXXXXX          (name left blank)
    """
    contacts = []
    for line in raw.replace("\r", "").splitlines():
        line = line.strip()
        if not line:
            continue
        name = ""
        phone_raw = line

        # Try "Name: +91..." or "Name, +91..."
        for sep in (":", ","):
            if sep in line:
                parts = line.split(sep, 1)
                candidate_name = parts[0].strip()
                candidate_phone = parts[1].strip()
                # Make sure right side looks like a phone number
                digits = [c for c in candidate_phone if c.isdigit()]
                if len(digits) >= 7:
                    name = candidate_name
                    phone_raw = candidate_phone
                    break

        phone = "".join(c for c in phone_raw if c.isdigit() or c == "+")
        if phone:
            contacts.append({"name": name, "phone": phone})
    return contacts


def _get_test_mode() -> str:
    """Return 'on' or 'off' from system_config."""
    try:
        conn = get_connection()
        row = conn.execute("SELECT value FROM system_config WHERE key = 'test_mode'").fetchone()
        conn.close()
        return row["value"] if row else "off"
    except Exception:
        return "off"


def _set_test_mode(value: str) -> None:
    """Set test_mode in system_config to 'on' or 'off'."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO system_config (key, value, updated_at) VALUES ('test_mode', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (value, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


# ── Routes ───────────────────────────────────────────────────────────

@upload_bp.route("/upload", methods=["GET"])
@login_required
def index():
    devices = _fetch_devices()
    sms_contacts = _fetch_contact_list("sms")
    call_contacts = _fetch_contact_list("call")
    test_sms_contacts = _fetch_contact_list("test_sms")
    test_call_contacts = _fetch_contact_list("test_call")
    test_mode = _get_test_mode()

    return render_template(
        "upload.html",
        devices=devices,
        sms_contacts=sms_contacts,
        call_contacts=call_contacts,
        test_sms_contacts=test_sms_contacts,
        test_call_contacts=test_call_contacts,
        test_mode=test_mode,
    )


@upload_bp.route("/upload", methods=["POST"])
@login_required
def upload():
    import csv
    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("upload.index"))

    filename = file.filename.lower()
    if not (filename.endswith(".csv") or filename.endswith(".xlsx")):
        flash("Only .xlsx files (or .csv files) are accepted.", "error")
        return redirect(url_for("upload.index"))

    # Save to a temp file for parser
    suffix = ".csv" if filename.endswith(".csv") else ".xlsx"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        file.save(tmp)
        tmp_path = tmp.name

    try:
        # Use current global SMS contact phones as default for new devices
        global_contacts_dicts = _fetch_contact_list("sms")
        global_phones = [c["phone"] for c in global_contacts_dicts] or \
                        ["+919545202660", "+919730814745", "+919561515546", "+919172319233"]
        result = parse_device_map(tmp_path, default_contacts=global_phones)
    except ValueError as e:
        flash(f"Invalid file: {e}", "error")
        return redirect(url_for("upload.index"))
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows file lock cleanup

    # Upsert valid rows into device_map
    updated = 0
    if result.valid_rows:
        conn = get_connection()
        import re
        for row in result.valid_rows:
            conn.execute(
                "INSERT OR REPLACE INTO device_map "
                "(device_code, location_name, zone, device_type, contacts) "
                "VALUES (?, ?, ?, ?, ?)",
                (row.device_code, row.location_name, row.zone,
                 row.device_type, json.dumps(row.contacts)),
            )
            updated += 1

            # Dual-index short slash format (e.g. L1/101 for L1 A101) so lookups always match
            m = re.match(r"^L(\d+)\s+[A-Za-z](\d{3})$", row.device_code)
            if m:
                short_code = f"L{m.group(1)}/{int(m.group(2))}"
                conn.execute(
                    "INSERT OR REPLACE INTO device_map "
                    "(device_code, location_name, zone, device_type, contacts) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (short_code, row.location_name, row.zone,
                     row.device_type, json.dumps(row.contacts)),
                )
        conn.commit()

        # Save an active copy to hardware/device_map.csv for template download & reference
        csv_out = Path(__file__).resolve().parent.parent.parent / "hardware" / "device_map.csv"
        csv_out.parent.mkdir(parents=True, exist_ok=True)
        all_canonical = conn.execute(
            "SELECT device_code, location_name FROM device_map WHERE device_code LIKE 'L% A%' ORDER BY device_code"
        ).fetchall()
        with open(str(csv_out), "w", encoding="utf-8", newline="") as cf:
            writer = csv.writer(cf)
            writer.writerow(["Sr. No.", "ID", "Location"])
            for idx, d in enumerate(all_canonical, start=1):
                writer.writerow([idx, d["device_code"], d["location_name"]])

        # Regenerate known_devices.txt so cv/validate.py recognizes all codes
        all_devices = conn.execute("SELECT device_code FROM device_map ORDER BY device_code").fetchall()
        conn.close()

        kd_path = Path(__file__).resolve().parent.parent.parent / "hardware" / "known_devices.txt"
        kd_path.parent.mkdir(parents=True, exist_ok=True)
        with kd_path.open("w", encoding="utf-8") as f:
            for d in all_devices:
                f.write(d["device_code"] + "\n")

        # Reload known devices in cv/validate.py cache
        try:
            import cv.validate as _v
            _v._known_devices = _v._load_known_devices()
        except Exception:
            pass

    # Build summary for template
    error_details = [
        f"Row {e.row_number}: {e.reason}" for e in result.errors
    ]

    return render_template(
        "upload.html",
        devices=_fetch_devices(),
        sms_contacts=_fetch_contact_list("sms"),
        call_contacts=_fetch_contact_list("call"),
        test_sms_contacts=_fetch_contact_list("test_sms"),
        test_call_contacts=_fetch_contact_list("test_call"),
        test_mode=_get_test_mode(),
        upload_done=True,
        updated=updated,
        errors=error_details,
    )


@upload_bp.route("/upload/template")
@login_required
def download_template():
    import csv
    csv_path = Path(__file__).resolve().parent.parent.parent / "hardware" / "device_map.csv"
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(csv_path), "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Sr. No.", "ID", "Location"])
            writer.writerow([1, "L1 A101", "1ST AID RM MCPL1/101, First aid room, Near by First aid room"])
            writer.writerow([2, "L2 A103", "MZ EPR-2 MCP L2/103, Mixing area (WWD)"])
            writer.writerow([3, "L1 A104", "WIRE RDST MCP L1/104, Coil unloading area"])
    return send_file(str(csv_path), as_attachment=True, download_name="device_map.csv", mimetype="text/csv")


@upload_bp.route("/upload/sms-contacts", methods=["POST"])
@login_required
def update_sms_contacts():
    """Save the global SMS notification contact list (production)."""
    raw = request.form.get("sms_contacts", "")
    contacts = _parse_contacts(raw)
    _save_contact_list("sms", contacts)
    flash(f"SMS contact list updated — {len(contacts)} number(s) saved.", "success")
    return redirect(url_for("upload.index"))


@upload_bp.route("/upload/call-contacts", methods=["POST"])
@login_required
def update_call_contacts():
    """Save the global Call notification contact list (production)."""
    raw = request.form.get("call_contacts", "")
    contacts = _parse_contacts(raw)
    _save_contact_list("call", contacts)
    flash(f"Call contact list updated — {len(contacts)} number(s) saved.", "success")
    return redirect(url_for("upload.index"))


@upload_bp.route("/upload/test-sms-contacts", methods=["POST"])
@login_required
def update_test_sms_contacts():
    """Save the test SMS contact list (used when test mode is active)."""
    raw = request.form.get("test_sms_contacts", "")
    contacts = _parse_contacts(raw)
    _save_contact_list("test_sms", contacts)
    flash(f"Test SMS contact list updated — {len(contacts)} number(s) saved.", "success")
    return redirect(url_for("upload.index"))


@upload_bp.route("/upload/test-call-contacts", methods=["POST"])
@login_required
def update_test_call_contacts():
    """Save the test Call contact list (used when test mode is active)."""
    raw = request.form.get("test_call_contacts", "")
    contacts = _parse_contacts(raw)
    _save_contact_list("test_call", contacts)
    flash(f"Test Call contact list updated — {len(contacts)} number(s) saved.", "success")
    return redirect(url_for("upload.index"))


@upload_bp.route("/upload/test-mode", methods=["POST"])
@login_required
def toggle_test_mode():
    """Toggle test mode on or off."""
    current = _get_test_mode()
    new_value = "off" if current == "on" else "on"
    _set_test_mode(new_value)
    if new_value == "on":
        flash("⚠️ TEST MODE ENABLED — Notifications will go to test contacts only.", "warning")
    else:
        flash("✅ Test mode disabled — Notifications going to production contacts.", "success")
    return redirect(url_for("upload.index"))
