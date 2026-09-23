"""
Canonical event object passed between pipeline stages.

Updated for the post-visit architecture: the LED is no longer the trigger
or the classifier. message_type now carries that role, produced by
cv/classify.py from the full-screen OCR text.

Frozen at the Week 4 interface checkpoint -- if you need to change this
shape, sync with whoever owns the module downstream of you first
(cv -> backend -> notify).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class DetectedEvent:
    """Output of the CV/OCR stage. Owned by Member 2."""
    device_code: str          # e.g. "L1/A053", already validated
    message_type: str = "unknown"  # "fire" | "fault" | "supervisory" | "normal" | "unknown"
    raw_text: str = ""        # full OCR'd screen text, kept for debugging/audit
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 0.0   # OCR confidence, 0-1
    frame_id: int = 0


@dataclass
class ResolvedEvent(DetectedEvent):
    """
    Output of the backend stage. Owned by Member 3.
    Adds everything notify/ needs to actually send an alert and route it
    correctly by message_type.
    """
    location_name: str = ""
    zone: str = ""
    device_type: str = ""
    contacts: list[str] = field(default_factory=list)   # full notify list (SMS)
    primary_contact: str = ""                            # who gets the voice call
    db_record_id: Optional[int] = None
