"""Device Map upload page — Excel upload + validation + upsert.

Accepts a .xlsx file, validates it via excel_parser, upserts valid rows
into device_map, and shows a plain-English summary of what happened.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for

from backend.db import get_connection
from ui.auth import login_required
from ui.excel_parser import parse_device_map

upload_bp = Blueprint("upload", __name__)

_TEMPLATE_PATH = Path(__file__).parent.parent / "static" / "template.xlsx"


@upload_bp.route("/upload", methods=["GET"])
@login_required
def index():
    # Fetch the current device map for display.
    conn = get_connection()
    devices = conn.execute(
        "SELECT device_code, location_name, zone, device_type, contacts FROM device_map ORDER BY device_code"
    ).fetchall()
    conn.close()

    return render_template("upload.html", devices=[dict(d) for d in devices])


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
        upload_done=True,
        updated=updated,
        errors=error_details,
    )


@upload_bp.route("/upload/template")
@login_required
def download_template():
    return send_file(str(_TEMPLATE_PATH), as_attachment=True, download_name="device_map_template.xlsx")


def _fetch_devices() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT device_code, location_name, zone, device_type, contacts FROM device_map ORDER BY device_code"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
