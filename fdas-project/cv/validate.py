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

OCR correction (two layers):
  1. Text normalization: fix common LCD OCR misreads BEFORE regex matching
     (e.g. 'Li' -> 'L1', 'Alia' -> 'A11a' -> digits corrected)
  2. Prefix correction: all Bekaert devices use 'A' prefix; if a different
     letter is found, try 'A' and check against known_devices.

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


# ── OCR text normalization ────────────────────────────────────────────
# Common Tesseract misreads on blue LCD panel screens.
# These substitutions are applied ONLY around device-code patterns.

# Characters that OCR commonly confuses between letters and digits
_LETTER_TO_DIGIT = str.maketrans({
    "i": "1", "I": "1", "l": "1",  # very common
    "o": "0", "O": "0",
    "s": "5", "S": "5",
    "a": "4",                       # 'a' misread for '4' in LCD fonts
    "b": "6", "B": "8",
    "g": "9", "q": "9",
    "z": "2", "Z": "2",
    "t": "1", "T": "7",
})


def _normalize_ocr_text(text: str) -> str:
    """
    Fix common OCR misreads specifically around device code patterns.
    
    Works on each line independently. Looks for patterns like:
      - "Li Alia"   -> "L1 A114"
      - "L1 Ri38"   -> "L1 R138"
      - "Ll A053"   -> "L1 A053"
      - "L1/i4"     -> "L1/14"
    """
    lines = text.split("\n")
    fixed_lines = []
    
    for line in lines:
        # Pattern 1: Fix "Li", "Ll", "LI", "Lo" -> "L1", "L0" etc. (loop number)
        line = re.sub(
            r'\bL([iIlLoOsS])',
            lambda m: f"L{m.group(1).translate(_LETTER_TO_DIGIT)}",
            line
        )
        
        # Pattern 2: After "L<digit> " or "L<digit>/", fix the code portion
        def fix_code_portion(m):
            prefix = m.group(1)    # "L1 " or "L1/"
            code_part = m.group(2) # "Alia" or "i4"
            if prefix.endswith("/"):
                # Short form: everything after / should be digits
                fixed = code_part.translate(_LETTER_TO_DIGIT)
            else:
                # Long form: first char is letter prefix (A), rest should be digits
                if len(code_part) > 1:
                    fixed = code_part[0].upper() + code_part[1:].translate(_LETTER_TO_DIGIT)
                else:
                    fixed = code_part
            return prefix + fixed
        
        line = re.sub(
            r'(L\d+[\s/])([A-Za-z][A-Za-z0-9]{1,3})',
            fix_code_portion,
            line
        )
        
        fixed_lines.append(line)
    
    return "\n".join(fixed_lines)





def _normalise(text: str) -> str | None:
    """Return the canonical 'L<n> <alpha><ddd>' form, or None.
    
    Tries the raw text first, then applies OCR normalization if no match.
    """
    upper = text.upper()
    
    # Try raw text first
    m = _CODE_LONG.search(upper)
    if m:
        return f"L{m.group(1)} {m.group(2)}"
    m = _CODE_SHORT.search(upper)
    if m:
        det = m.group(2).zfill(3)
        return f"L{m.group(1)} A{det}"
    
    # Try with OCR normalization
    normalized = _normalize_ocr_text(text)
    upper_norm = normalized.upper()
    
    if upper_norm != upper:
        m = _CODE_LONG.search(upper_norm)
        if m:
            code = f"L{m.group(1)} {m.group(2)}"
            print(f"  [OCR-FIX] Normalized text to find code: '{code}'")
            return code
        m = _CODE_SHORT.search(upper_norm)
        if m:
            det = m.group(2).zfill(3)
            code = f"L{m.group(1)} A{det}"
            print(f"  [OCR-FIX] Normalized text to find code: '{code}'")
            return code
    
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
    # If exact match in known devices, return immediately
    if _known_devices and code in _known_devices:
        return code
    # Try OCR prefix correction (A/R/P/H confusion)
    if _known_devices:
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
