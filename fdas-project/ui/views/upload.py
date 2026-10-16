"""Device Map upload page — Excel upload + validation + upsert.

Accepts a .xlsx file, validates it via excel_parser, upserts valid rows
into device_map, and shows a plain-English summary of what happened.

Also provides separate management of global SMS and Call contact lists,
stored in the notification_contacts table.
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


def _fetch_contact_list(list_type: str) -> list[str]:
    """Return the phone numbers for a given list_type ('sms' or 'call')."""
    conn = get_connection()
    row = conn.execute(
        "SELECT contacts FROM notification_contacts WHERE list_type = ?",
        (list_type,),
    ).fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["contacts"])
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _save_contact_list(list_type: str, contacts: list[str]) -> None:
    """Upsert the phone number list for SMS or Call."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO notification_contacts (list_type, contacts, updated_at) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(list_type) DO UPDATE SET contacts = excluded.contacts, updated_at = excluded.updated_at",
        (list_type, json.dumps(contacts), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()


def _parse_phone_numbers(raw: str) -> list[str]:
    """Parse a textarea of phone numbers (one per line or comma-separated)."""
    numbers = []
    for line in raw.replace(",", "\n").splitlines():
        num = "".join(c for c in line.strip() if c.isdigit() or c == "+")
        if num:
            numbers.append(num)
    return numbers


# ── Routes ───────────────────────────────────────────────────────────

@upload_bp.route("/upload", methods=["GET"])
@login_required
def index():
    # Fetch the current device map for display.
    devices = _fetch_devices()
    sms_contacts = _fetch_contact_list("sms")
    call_contacts = _fetch_contact_list("call")

    return render_template(
        "upload.html",
        devices=devices,
        sms_contacts=sms_contacts,
        call_contacts=call_contacts,
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
        # Use current global SMS contacts as default for new devices
        global_contacts = _fetch_contact_list("sms") or ["+919545202660", "+919730814745", "+919561515546", "+919172319233"]
        result = parse_device_map(tmp_path, default_contacts=global_contacts)
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
        all_canonical = conn.execute("SELECT device_code, location_name FROM device_map WHERE device_code LIKE 'L% A%' ORDER BY device_code").fetchall()
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
    """Save the global SMS notification contact list."""
    raw = request.form.get("sms_contacts", "")
    numbers = _parse_phone_numbers(raw)
    _save_contact_list("sms", numbers)
    flash(f"SMS contact list updated — {len(numbers)} number(s) saved.", "success")
    return redirect(url_for("upload.index"))


@upload_bp.route("/upload/call-contacts", methods=["POST"])
@login_required
def update_call_contacts():
    """Save the global Call notification contact list."""
    raw = request.form.get("call_contacts", "")
    numbers = _parse_phone_numbers(raw)
    _save_contact_list("call", numbers)
    flash(f"Call contact list updated — {len(numbers)} number(s) saved.", "success")
    return redirect(url_for("upload.index"))
