"""Location resolution and event logging. Owner: Member 3."""

from __future__ import annotations

import json

from cv.event import DetectedEvent, ResolvedEvent
from backend.db import get_connection


def _get_global_contacts(list_type: str) -> list[str]:
    """Fetch the global contact list from notification_contacts table.
    
    Returns an empty list if no global list is configured, so the
    per-device contacts from device_map are used as fallback.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT contacts FROM notification_contacts WHERE list_type = ?",
        (list_type,),
    ).fetchone()
    conn.close()
    if row:
        try:
            contacts = json.loads(row["contacts"])
            if contacts:  # Only use if non-empty
                return contacts
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def resolve_zone_location(code_or_zone: str) -> str:
    """Resolve a physical plant location for a Zone or unmapped device."""
    import re
    import sqlite3
    try:
        conn = get_connection()
        # 1. Check exact match in device_map
        row = conn.execute(
            "SELECT location_name FROM device_map WHERE device_code = ? OR zone = ? LIMIT 1",
            (code_or_zone, code_or_zone),
        ).fetchone()
        if row and row["location_name"]:
            conn.close()
            return row["location_name"]

        # 2. Check if a zone number is mentioned, e.g. "Zone 1"
        zm = re.search(r'\b(?:Zone\s*)?(\d+)\b', code_or_zone, re.IGNORECASE)
        if zm:
            z_num = zm.group(1)
            row = conn.execute(
                "SELECT location_name FROM device_map WHERE device_code = ? OR zone LIKE ? LIMIT 1",
                (f"Zone {z_num}", f"%Zone {z_num}%"),
            ).fetchone()
            if row and row["location_name"]:
                conn.close()
                return row["location_name"]

            conn.close()
            if z_num == "1":
                return "Production Plant / First Aid (Loop 1)"
            elif z_num == "2":
                return "Mixing Area / Utility / Mezzanine (Loop 2)"
            return f"Zone {z_num} Area"

        conn.close()
    except (sqlite3.OperationalError, Exception):
        pass

    zm = re.search(r'\b(?:Zone\s*)?(\d+)\b', code_or_zone, re.IGNORECASE)
    if zm:
        z_num = zm.group(1)
        if z_num == "1":
            return "Production Plant / First Aid (Loop 1)"
        elif z_num == "2":
            return "Mixing Area / Utility / Mezzanine (Loop 2)"
        return f"Zone {z_num} Area"

    return "Plant Area (Check Panel)"


def resolve_location(event: DetectedEvent) -> ResolvedEvent | None:
    """
    Cross-reference the confirmed device code against the commissioning-
    time mapping table (backend/schema.sql: device_map).

    Contact resolution priority:
      1. Global notification_contacts table (if configured via the dashboard)
      2. Per-device contacts from device_map (fallback)

    The first entry in the SMS contacts list is used as the primary_contact
    for a voice call (fire messages only -- see backend/routing.py), unless
    a separate global call contact list is configured.

    Returns None if the device code isn't in the mapping table.
    """
    code = event.device_code
    candidates = [code]

    import re
    # If L1/101 -> also try L1 A101
    m_slash = re.search(r'L(\d+)\s*[/\\-]\s*(\d{1,3})', code, re.IGNORECASE)
    if m_slash:
        loop, num = m_slash.group(1), m_slash.group(2)
        candidates.append(f"L{loop} A{num.zfill(3)}")
        candidates.append(f"L{loop}/{int(num)}")

    # If L1 A101 or L1A101 -> also try L1/101
    m_space = re.search(r'L(\d+)\s*([A-Za-z])\s*(\d{1,3})', code, re.IGNORECASE)
    if m_space:
        loop, prefix, num = m_space.group(1), m_space.group(2), m_space.group(3)
        candidates.append(f"L{loop} {prefix.upper()}{num.zfill(3)}")
        candidates.append(f"L{loop}/{int(num)}")

    conn = get_connection()
    row = None
    for cand in candidates:
        row = conn.execute(
            "SELECT location_name, zone, device_type, contacts FROM device_map WHERE device_code = ?",
            (cand,),
        ).fetchone()
        if row:
            break
    conn.close()

    if row is None:
        return None

    # Resolve contacts: global list takes priority over per-device
    global_sms = _get_global_contacts("sms")
    global_call = _get_global_contacts("call")
    device_contacts = json.loads(row["contacts"])

    contacts = global_sms if global_sms else device_contacts
    primary_contact = (global_call[0] if global_call
                       else contacts[0] if contacts
                       else "")

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
        primary_contact=primary_contact,
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
