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
        num = line.strip()
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
    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("upload.index"))

    if not file.filename.lower().endswith(".xlsx"):
        flash("Only .xlsx files are accepted.", "error")
        return redirect(url_for("upload.index"))

    # Save to a temp file for openpyxl to read.
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        file.save(tmp)
        tmp_path = tmp.name

    try:
        result = parse_device_map(tmp_path)
    except ValueError as e:
        flash(f"Invalid spreadsheet: {e}", "error")
        return redirect(url_for("upload.index"))
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows: file handle not yet released; OS cleans up temp dir

    # Upsert valid rows into device_map.
    updated = 0
    if result.valid_rows:
        conn = get_connection()
        for row in result.valid_rows:
            conn.execute(
                "INSERT OR REPLACE INTO device_map "
                "(device_code, location_name, zone, device_type, contacts) "
                "VALUES (?, ?, ?, ?, ?)",
                (row.device_code, row.location_name, row.zone,
                 row.device_type, json.dumps(row.contacts)),
            )
            updated += 1
        conn.commit()
        conn.close()

    # Build summary for the template.
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
    return send_file(str(_TEMPLATE_PATH), as_attachment=True, download_name="device_map_template.xlsx")


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
