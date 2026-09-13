"""
Extracts a device/zone code from the full OCR'd screen text, and validates
it against format + the known-device list.

Real Honeywell panel format (confirmed from site photo):
  - Line "Device: OPT    ABV B100 MC SD L1/53"  -> short form  "L1/53"
  - Line "       L1 A053"                        -> long form   "L1 A053"

Both are normalised to the canonical form "L1 A053" for storage/lookup.
The regex handles:
  - "L1 A053"   (space-separated, from the device detail line)
  - "L1/53"     (slash short-form, from the description line -- expanded on lookup)

OCR correction:
  All Bekaert devices use the "A" prefix (e.g. A053, A138). When Tesseract
  misreads the prefix letter (A->R, A->P, A->H -- common on blue LCD screens),
  the code is corrected to "A" if the corrected version exists in known_devices.

Owner: Member 2 (works with Member 1 on the real device-code format and list).
"""

from __future__ import annotations

import re
from pathlib import Path

_KNOWN_DEVICES_PATH = Path("hardware/known_devices.txt")

# Real panel formats confirmed from site photo (2026-08 visit):
#   Long form:  "L1 A053"  (letter-prefix loop, space, alpha+3digits)
#   Short form: "L1/53"    (loop/detector-number only, no alpha prefix letter visible)
#
# We match both and normalise to the long form for DB lookup.
_CODE_LONG  = re.compile(r"\bL(\d+)\s+([A-Z]\d{3})\b")   # "L1 A053"
_CODE_SHORT = re.compile(r"\bL(\d+)/(\d{2,3})\b")          # "L1/53"


def _load_known_devices() -> set[str]:
    if not _KNOWN_DEVICES_PATH.exists():
        return set()
    return {line.strip() for line in _KNOWN_DEVICES_PATH.read_text().splitlines() if line.strip()}


_known_devices = _load_known_devices()


def _normalise(text: str) -> str | None:
    """Return the canonical 'L<n> <alpha><ddd>' form, or None."""
    upper = text.upper()
    m = _CODE_LONG.search(upper)
    if m:
        return f"L{m.group(1)} {m.group(2)}"
    m = _CODE_SHORT.search(upper)
    if m:
        # Short form "L1/53" -- we store as "L1 A053" (A-prefix assumed from Bekaert panel)
        det = m.group(2).zfill(3)
        return f"L{m.group(1)} A{det}"
    return None


def _try_fix_prefix(code: str) -> str | None:
    """
    OCR sometimes misreads the prefix letter on LCD screens
    (e.g. 'A' -> 'R', 'A' -> 'P', 'A' -> 'H').

    All Bekaert devices use the 'A' prefix, so if the extracted code
    doesn't match a known device, try replacing the prefix with 'A'.
    Returns the corrected code if found, otherwise None.
    """
    # Parse: "L2 R138" -> loop="2", prefix="R", num="138"
    m = re.match(r"^L(\d+)\s+([A-Z])(\d{3})$", code)
    if not m:
        return None
    loop, prefix, num = m.group(1), m.group(2), m.group(3)
    if prefix == "A":
        return None  # Already correct prefix, nothing to fix
    corrected = f"L{loop} A{num}"
    if corrected in _known_devices:
        print(f"  [OCR-FIX] Corrected '{code}' -> '{corrected}' (prefix '{prefix}'->'A')")
        return corrected
    return None


def extract_code(text: str) -> str | None:
    """Searches the full screen text for a device code in either format
    and returns the canonical 'L<n> <alpha><ddd>' form, or None."""
    code = _normalise(text)
    if code is None:
        return None
    # If the code isn't in known devices, try OCR prefix correction
    if _known_devices and code not in _known_devices:
        corrected = _try_fix_prefix(code)
        if corrected:
            return corrected
    return code


def validate_code(code: str | None) -> bool:
    """
    (a) format already enforced by extract_code's normalisation, so this
    mainly checks (b) membership in the known-device list. Kept as a
    separate step so debounce/retry logic in capture.py can distinguish
    'no code-shaped text found' from 'found a code but it is not a real
    device' -- useful for diagnosing OCR/vocabulary issues later.
    """
    if not code:
        return False
    if _known_devices and code not in _known_devices:
        return False
    return True
