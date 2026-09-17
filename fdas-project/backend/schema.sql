-- FDAS event log schema. Owner: Member 3.
-- SQLite-compatible; swap AUTOINCREMENT/types if moving to PostgreSQL.

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_code     TEXT NOT NULL,
    message_type    TEXT NOT NULL DEFAULT 'unknown',  -- 'fire' | 'fault' | 'supervisory'
    raw_text        TEXT,                    -- full OCR'd screen text, for audit/debugging
    detected_at     TEXT NOT NULL,          -- ISO 8601 UTC
    confidence      REAL,
    location_name   TEXT,
    zone            TEXT,
    device_type     TEXT,
    contacts        TEXT,                   -- JSON array, resolved SMS contact group
    primary_contact TEXT,                   -- who gets the voice call (fire only)
    status          TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'resolved'
    resolved_at     TEXT,
    sms_status      TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'sent' | 'failed' | 'escalated'
    sms_attempts    INTEGER NOT NULL DEFAULT 0,
    call_status     TEXT NOT NULL DEFAULT 'not_applicable'  -- 'not_applicable' | 'pending' | 'placed' | 'failed'
);

CREATE INDEX IF NOT EXISTS idx_events_device_status ON events(device_code, status);

-- Commissioning-time mapping table (step 9: Location Resolution).
-- Populated once during install, editable as zone/contact assignments change.
CREATE TABLE IF NOT EXISTS device_map (
    device_code     TEXT PRIMARY KEY,
    location_name   TEXT NOT NULL,
    zone            TEXT NOT NULL,
    device_type     TEXT NOT NULL,
    contacts        TEXT NOT NULL           -- JSON array of phone numbers
);

-- System-health checks logged by the watchdog (step 14: Operator UI).
-- The dashboard reads the latest row per check_name to build the status banner.
CREATE TABLE IF NOT EXISTS system_health (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    check_name   TEXT NOT NULL,             -- 'heartbeat' | 'camera' | 'process'
    status       TEXT NOT NULL,             -- 'ok' | 'fault'
    detail       TEXT,                      -- human-readable reason when status='fault'
    checked_at   TEXT NOT NULL              -- ISO 8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_health_check ON system_health(check_name, checked_at);
