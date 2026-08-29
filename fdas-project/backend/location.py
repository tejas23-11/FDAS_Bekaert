"""Location resolution and event logging. Owner: Member 3."""

from __future__ import annotations

import json

from cv.event import DetectedEvent, ResolvedEvent
from backend.db import get_connection


def resolve_location(event: DetectedEvent) -> ResolvedEvent | None:
    """
    Cross-reference the confirmed device code against the commissioning-
    time mapping table (backend/schema.sql: device_map). The first entry
    in the contacts list is used as the primary_contact for a voice call
    (fire messages only -- see backend/routing.py).

    Returns None if the device code isn't in the mapping table.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT location_name, zone, device_type, contacts FROM device_map WHERE device_code = ?",
        (event.device_code,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    contacts = json.loads(row["contacts"])

    return ResolvedEvent(
        device_code=event.device_code,
        message_type=event.message_type,
        raw_text=event.raw_text,
        timestamp=event.timestamp,
        confidence=event.confidence,
        frame_id=event.frame_id,
        location_name=row["location_name"],
        zone=row["zone"],
        device_type=row["device_type"],
        contacts=contacts,
        primary_contact=contacts[0] if contacts else "",
    )


def log_event(event: ResolvedEvent) -> int:
    """
    Commit the structured event record BEFORE any notification attempt,
    so the audit trail never depends on SMS/call success. Returns the new
    row id, which notify/ uses to update sms_status/call_status later.
    """
    conn = get_connection()
    cur = conn.execute(
        """
        INSERT INTO events (device_code, message_type, raw_text, detected_at, confidence,
                             location_name, zone, device_type, contacts, primary_contact,
                             status, sms_status, call_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 'pending', ?)
        """,
        (
            event.device_code,
            event.message_type,
            event.raw_text,
            event.timestamp.isoformat(),
            event.confidence,
            event.location_name,
            event.zone,
            event.device_type,
            json.dumps(event.contacts),
            event.primary_contact,
            "pending" if event.message_type == "fire" else "not_applicable",
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()

    event.db_record_id = row_id
    return row_id
