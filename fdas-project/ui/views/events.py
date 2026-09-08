"""Event History page — filterable, paginated event log.

Queries the existing events table (ORDER BY detected_at DESC) with
optional filtering by message_type and status. Pagination at 25 rows
per page keeps the page responsive even after months of operation.
"""

from __future__ import annotations

from flask import Blueprint, render_template, request

from backend.db import get_connection
from ui.auth import login_required

events_bp = Blueprint("events", __name__)

ROWS_PER_PAGE = 25


@events_bp.route("/events")
@login_required
def index():
    # --- Filter params ---
    msg_type = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()
    page = max(1, request.args.get("page", 1, type=int))

    # --- Build query with optional filters ---
    conditions: list[str] = []
    params: list[str] = []

    if msg_type:
        conditions.append("message_type = ?")
        params.append(msg_type)
    if status:
        conditions.append("status = ?")
        params.append(status)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # --- Count for pagination ---
    conn = get_connection()
    total = conn.execute(
        f"SELECT COUNT(*) FROM events {where_clause}", params
    ).fetchone()[0]

    total_pages = max(1, (total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)
    page = min(page, total_pages)
    offset = (page - 1) * ROWS_PER_PAGE

    # --- Fetch page of events ---
    rows = conn.execute(
        f"SELECT * FROM events {where_clause} ORDER BY detected_at DESC LIMIT ? OFFSET ?",
        params + [ROWS_PER_PAGE, offset],
    ).fetchall()
    conn.close()

    events = [dict(r) for r in rows]

    return render_template(
        "events.html",
        events=events,
        current_type=msg_type,
        current_status=status,
        page=page,
        total_pages=total_pages,
        total=total,
    )
