"""
Extracts a device/zone code from the full OCR'd screen text, and validates
it against format + the known-device list.

Previously the code was the only thing in a tightly cropped ROI, so OCR
output *was* the code. Now the code is somewhere inside a larger message
(e.g. "FIRE ALARM\nZONE L1/A053"), so extraction is now a search rather
than an assumption.

Owner: Member 2 (works with Member 1 on the real device-code format and list).
"""

from __future__ import annotations

import re
from pathlib import Path

_KNOWN_DEVICES_PATH = Path("hardware/known_devices.txt")

# TODO(Member 1/2): confirm the real device code format from the site visit.
# This pattern (e.g. "L1/A053") is what the proposal document used as an
# example -- update it if the real panel format differs.
_CODE_PATTERN = re.compile(r"\bL\d+/[A-Z]\d{3}\b")


def _load_known_devices() -> set[str]:
    if not _KNOWN_DEVICES_PATH.exists():
        return set()
    return {line.strip() for line in _KNOWN_DEVICES_PATH.read_text().splitlines() if line.strip()}


_known_devices = _load_known_devices()


def extract_code(text: str) -> str | None:
    """Searches the full screen text for something matching the device
    code pattern. Returns the first match, or None if nothing matches."""
    match = _CODE_PATTERN.search(text.upper())
    return match.group(0) if match else None


def validate_code(code: str | None) -> bool:
    """
    (a) format already enforced by extract_code's regex, so this mainly
    checks (b) membership in the known-device list. Kept as a separate
    step (rather than folding into extract_code) so debounce/retry logic
    in capture.py can distinguish "no code-shaped text found" from
    "found a code-shaped string but it's not a real device" -- useful for
    diagnosing OCR/vocabulary issues later.
    """
    if not code:
        return False
    if _known_devices and code not in _known_devices:
        return False
    return True
