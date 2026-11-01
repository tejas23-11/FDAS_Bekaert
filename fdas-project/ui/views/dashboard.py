"""Dashboard landing page — system health banner + recent events.

Reads the latest system_health row per check_name to build the status
banner. Auto-refreshes every 10 seconds via a meta tag so a problem
shows up without manual reloading.

Feature 2: Recent events table now shows only Time, Device ID, Location
           (full detail still available on /events).
Feature 3: Passes test_mode to template so a warning banner is shown
           when test mode is active.
Feature 5: GSM signal health is automatically included via the health
           checks query — no extra code needed.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import Blueprint, render_template, redirect, url_for, flash, request

from backend.db import get_connection
from ui.auth import login_required

dashboard_bp = Blueprint("dashboard", __name__)


def _get_health_status() -> list[dict]:
    """Return the latest health row per check_name, with parsed extras."""
    import re
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT h.check_name, h.status, h.detail, h.checked_at
        FROM system_health h
        INNER JOIN (
            SELECT check_name, MAX(checked_at) AS latest
            FROM system_health
            GROUP BY check_name
        ) latest_checks
        ON h.check_name = latest_checks.check_name
           AND h.checked_at = latest_checks.latest
        ORDER BY h.check_name
        """
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        # Parse RSSI value from GSM detail string for signal bar rendering
        if d["check_name"] == "gsm_signal" and d.get("detail"):
            m = re.search(r"(\d+)/31", d["detail"])
            d["gsm_rssi"] = int(m.group(1)) if m else None
        else:
            d["gsm_rssi"] = None
        result.append(d)
    return result


def _get_recent_events(limit: int = 10) -> list[dict]:
    """Return the most recent events for the dashboard quick view.
    Only fetches columns needed for the simplified 3-column table.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT detected_at, device_code, location_name FROM events ORDER BY detected_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_test_mode() -> str:
    """Return 'on' or 'off' from system_config."""
    try:
        conn = get_connection()
        row = conn.execute("SELECT value FROM system_config WHERE key = 'test_mode'").fetchone()
        conn.close()
        return row["value"] if row else "off"
    except Exception:
        return "off"


@dashboard_bp.route("/")
@login_required
def index():
    health_checks = _get_health_status()
    recent_events = _get_recent_events()
    test_mode = _get_test_mode()

    # Determine the overall banner state.
    faults = [h for h in health_checks if h["status"] == "fault"]
    if faults:
        banner = "fault"
        banner_detail = "; ".join(f["detail"] or f["check_name"] for f in faults)
    elif not health_checks:
        banner = "unknown"
        banner_detail = "No health data yet — watchdog may not be running"
    else:
        banner = "healthy"
        banner_detail = "All systems operating normally"

    return render_template(
        "dashboard.html",
        health_checks=health_checks,
        recent_events=recent_events,
        banner=banner,
        banner_detail=banner_detail,
        test_mode=test_mode,
    )


@dashboard_bp.route("/shutdown", methods=["POST"])
@login_required
def shutdown():
    """Stop the Flask web UI only. Pipeline and watchdog keep running."""
    flash("Web UI is shutting down. Pipeline and watchdog continue running.", "success")

    # Shut down the Flask server only
    func = request.environ.get("werkzeug.server.shutdown")
    if func is not None:
        func()
    else:
        # For newer Werkzeug versions, use os._exit
        os._exit(0)

    return redirect(url_for("dashboard.index"))
