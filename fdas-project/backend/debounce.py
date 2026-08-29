"""Debounce/Confirmation and Event Deduplication. Owner: Member 3.

Keyed on (device_code, message_type) rather than device_code alone -- a
device going from "fault" to "fire" is a real, new, more urgent event and
must NOT be suppressed as a duplicate of the fault that's still nominally
active for that device.
"""

from __future__ import annotations

import time
from collections import defaultdict

from cv.event import DetectedEvent


def _key(device_code: str, message_type: str) -> str:
    return f"{device_code}:{message_type}"


class Debouncer:
    """
    A (device_code, message_type) pair must recur across N consecutive
    detections within a short window before being accepted, filtering
    transient glare/reflection/OCR-noise misreads.
    """

    def __init__(self, required_consecutive: int = 3, window_seconds: float = 5.0):
        self.required = required_consecutive
        self.window = window_seconds
        self._history: dict[str, list[float]] = defaultdict(list)

    def confirm(self, event: DetectedEvent) -> bool:
        key = _key(event.device_code, event.message_type)
        now = time.time()
        hist = [t for t in self._history[key] if now - t <= self.window]
        hist.append(now)
        self._history[key] = hist
        return len(hist) >= self.required

    def reset(self, device_code: str, message_type: str):
        self._history.pop(_key(device_code, message_type), None)


class ActiveEventRegistry:
    """
    In-memory registry of currently-active (device, message_type) states.
    Prevents repeated notifications for a message that remains displayed;
    only new/state-changed events proceed to notification.
    """

    def __init__(self):
        self._active: set[str] = set()

    def is_active(self, device_code: str, message_type: str) -> bool:
        return _key(device_code, message_type) in self._active

    def mark_active(self, device_code: str, message_type: str):
        self._active.add(_key(device_code, message_type))

    def mark_resolved(self, device_code: str, message_type: str):
        """Called by resolution tracking once the message clears."""
        self._active.discard(_key(device_code, message_type))

    def active_types_for(self, device_code: str) -> list[str]:
        """All message types currently active for a given device -- used
        by resolution tracking to know what might need clearing."""
        prefix = f"{device_code}:"
        return [k[len(prefix):] for k in self._active if k.startswith(prefix)]


def process_new_detection(
    event: DetectedEvent, debouncer: Debouncer, registry: ActiveEventRegistry
) -> bool:
    """
    Returns True if this event should proceed to location resolution +
    logging, False if it should be dropped -- either not yet debounced,
    or already an active/known (device, message_type) pair.
    """
    if registry.is_active(event.device_code, event.message_type):
        return False

    if not debouncer.confirm(event):
        return False

    registry.mark_active(event.device_code, event.message_type)
    debouncer.reset(event.device_code, event.message_type)
    return True
