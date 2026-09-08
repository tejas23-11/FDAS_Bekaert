"""Dashboard landing page — system health banner + recent events.

Reads the latest system_health row per check_name to build the status
banner. Auto-refreshes every 10 seconds via a meta tag so a problem
shows up without manual reloading.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from backend.db import get_connection
from ui.auth import login_required

dashboard_bp = Blueprint("dashboard", __name__)


def _get_health_status() -> list[dict]:
    """Return the latest health row per check_name."""
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
    return [dict(r) for r in rows]


def _get_recent_events(limit: int = 10) -> list[dict]:
    """Return the most recent events for the dashboard quick view."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM events ORDER BY detected_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@dashboard_bp.route("/")
@login_required
def index():
    health_checks = _get_health_status()
    recent_events = _get_recent_events()

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
    )
