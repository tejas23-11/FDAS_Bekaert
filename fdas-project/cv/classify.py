"""
Classifies the OCR'd text from the Honeywell fire-alarm panel screen.

Owner: Member 2
"""

from __future__ import annotations

import re
import difflib

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
_VOCABULARY: dict[str, list[str]] = {
    "fire": [
        "fire",
        "first fire",
        "latest fire",
        "smoke",
        "heat",
        "manual call point",
        "mcp",
    ],
    "fault": [
        "fault",
        "system fault",
        "sounder fault",
        "supply fault",
        "earth fault",
        "trouble",
        "detector fault",
    ],
    "supervisory": [
        "disablement",
        "delayed mode",
        "sounders disabled",
        "fire tx disabled",
        "fire tx activated",
        "supervisory",
        "prealarm",
        "pre-alarm",
        "pre alarm",
        "bypassed",
        "disabled",
    ],
}

_FUZZY_THRESHOLD = 0.82

# ---------------------------------------------------------------------------
# Zero-count patterns: detect "Fire(0)", "Fire 0/0", "Fires (0)", etc.
# These appear on Morley-IAS / Honeywell idle status screens and should
# NOT be treated as active alarms.
# ---------------------------------------------------------------------------
_ZERO_COUNT_FIRE_RE = re.compile(
    r"\bfires?\s*[\(\[:]?\s*0(?:\s*[/\\]\s*0)?\s*[\)\]]?",
    re.IGNORECASE,
)
_ZERO_COUNT_FAULT_RE = re.compile(
    r"\bfaults?\s*[\(\[:]?\s*0(?:\s*[/\\]\s*0)?\s*[\)\]]?",
    re.IGNORECASE,
)


def _has_only_zero_count(text: str, category: str) -> bool:
    """
    Return True if every mention of 'fire' or 'fault' in the text is a
    zero-count status indicator (e.g. Fire(0), Faults 0/0).
    """
    if category == "fire":
        # Check if there is any mention of fire that is NOT zero-count
        zero_stripped = _ZERO_COUNT_FIRE_RE.sub("", text)
        # Also strip cabinet/panel branding so "fire alarm system" doesn't count
        zero_stripped = re.sub(r"\bfire\s+alarm\s+(?:system|panel)\b", "", zero_stripped, flags=re.IGNORECASE)
        zero_stripped = re.sub(r"\bfire\s+tx\b", "", zero_stripped, flags=re.IGNORECASE)
        zero_stripped = re.sub(r"\bfire\s+loop\b", "", zero_stripped, flags=re.IGNORECASE)
        # If after stripping zero-counts and branding, no "fire" remains, it's zero-only
        return not re.search(r"\bfire\b", zero_stripped, re.IGNORECASE)
    elif category == "fault":
        zero_stripped = _ZERO_COUNT_FAULT_RE.sub("", text)
        zero_stripped = re.sub(r"\bfire\s+tx\s+fault\b", "", zero_stripped, flags=re.IGNORECASE)
        return not re.search(r"\bfault\b", zero_stripped, re.IGNORECASE)
    return False


def classify_message(text: str) -> str:
    """
    Takes OCR'd raw text and returns one of:
    ``fire`` | ``fault`` | ``supervisory`` | ``normal`` | ``unknown``.
    
    Prioritizes Line 3 (the active event line on Morley-IAS LCD):
      - Line 3 with 'Fire X/Y' or 'Fire at' -> 'fire'
      - Line 3 with 'Fault X/Y' or 'Fault at' -> 'fault'
      - Historical 'First Fire' in banner is superseded by an active Fault on Line 3.
      - Full faceplate silkscreen rows without LCD alarm -> 'normal'
    """
    if not text or not text.strip():
        return "unknown"

    text_lower = text.lower().strip()

    # --- Guard: Prealarm is a supervisory warning, NOT a confirmed fire ---
    if any(kw in text_lower for kw in ("prealarm", "pre-alarm", "pre alarm")):
        return "supervisory"

    # --- Guard: Strip cabinet branding & panel title ---
    text_lower = re.sub(r"\bhoneywell\s+fire\s+alarm\s+system\b", "", text_lower)
    text_lower = re.sub(r"\bfire\s+alarm\s+panel\b", "", text_lower)
    text_lower = re.sub(r"\bhoneywell\b", "", text_lower)

    # -------------------------------------------------------------------------
    # 1. Line 3 Active Event Checks: Look for explicit event indicators
    # -------------------------------------------------------------------------
    # Active Fire pattern on Morley LCD: 'Fire 1/1 at ...', '1/1 Fire at ...', 'Fire 11 at ...', 'Fire at ...'
    has_active_fire = bool(
        re.search(r"\bfire\s*(?:[1-9]\d*[/\\ ]\d+|[1-9]\d*)\s*(?:at)?\s*\d{1,2}[:.]\d{2}\b", text_lower)
        or re.search(r"\b(?:[1-9]\d*[/\\ ]\d+)\s*fire\s*(?:at)?\s*\d{1,2}[:.]\d{2}\b", text_lower)
        or re.search(r"\bfire\s+[1-9]\d*[/\\ ]\d+\b", text_lower)
        or re.search(r"\bfire\s+at\s*\d{1,2}[:.]\d{2}\b", text_lower)
        or re.search(r"\b(?:smoke|heat)\s+detected\b", text_lower)
        or re.search(r"\bfire\s+evacuation\b", text_lower)
    )

    # Active Fault pattern on Morley LCD: 'Fault 1/6 at ...', 'Fault 1/1 at ...', 'Fault at ...', 'Compensation Warning'
    has_active_fault = bool(
        re.search(r"\bfault\s*(?:[1-9]\d*[/\\ ]\d+|[1-9]\d*)\s*(?:at)?\s*\d{1,2}[:.]\d{2}\b", text_lower)
        or re.search(r"\b(?:[1-9]\d*[/\\ ]\d+)\s*fault\s*(?:at)?\s*\d{1,2}[:.]\d{2}\b", text_lower)
        or re.search(r"\bfault\s+[1-9]\d*[/\\ ]\d+\b", text_lower)
        or re.search(r"\bfault\s+at\s*\d{1,2}[:.]\d{2}\b", text_lower)
        or "compensation warning" in text_lower
        or "detector fault" in text_lower
        or "fault in fire" in text_lower
    )

    # -------------------------------------------------------------------------
    # 1b. DUAL-GATE: Device code (bottom) + bare FAULT/FIRE keyword (Line 3)
    # -------------------------------------------------------------------------
    # On this Morley-IAS panel the screen layout is fixed:
    #   Line 3        -> active event type ("Fire 1/1 at ..." OR "Fault 1/2 at ...")
    #   Bottom lines  -> device code ("L1 A053", "MCP A103", "L1/53")
    #
    # When OCR degrades the structured timestamp (e.g. "Fault 1/8 at 13:26"
    # misread as "at ii8 M2 DOUB FAULT"), the timestamp regex above misses it.
    # But the bare FAULT/FIRE keyword is almost always legible.
    #
    # Rule: device-code-shaped text in OCR  +  bare FAULT keyword  =  fault
    #       device-code-shaped text in OCR  +  bare FIRE  keyword  =  fire
    # Zero-count idle screens ("Fault(0)", "[Status]") are explicitly excluded.
    _has_device_code = bool(
        re.search(r"\bl\d\s+[a-z]\d{2,3}\b", text_lower)         # "l1 a053"
        or re.search(r"\bl\d+[/\\]\d+\b", text_lower)              # "l1/53"
        or re.search(r"\bmcp\s+[a-z]?\d{2,3}\b", text_lower)       # "mcp a103"
        or re.search(r"\bdevice\b.*\bl\d\b", text_lower)           # "Device: ... L1"
    )
    if _has_device_code:
        # Bare FAULT keyword present — NOT an idle zero-count screen
        if (re.search(r"\bfault\b", text_lower)
                and not re.search(r"\bfaults?\s*[\(\[]\s*0", text_lower)
                and "[status]" not in text_lower):
            return "fault"
        # Bare FIRE keyword present — NOT an idle zero-count / banner-only screen
        if (re.search(r"\bfire\b", text_lower)
                and not _has_only_zero_count(text_lower, "fire")
                and not re.search(r"\bfires?\s*[\(\[]\s*0", text_lower)):
            return "fire"

    # Line 3 active event resolution (structured timestamp patterns matched above)
    if has_active_fault and not has_active_fire:
        return "fault"
    if has_active_fire and not has_active_fault:
        return "fire"
    if has_active_fire and has_active_fault:
        # Both present: Line 3 dictates the active event shown
        if re.search(r"\bfault\s*(?:[1-9]\d*[/\\ ]\d+|at\s*\d{1,2}[:.]\d{2})", text_lower) or "compensation warning" in text_lower:
            return "fault"
        return "fire"

    # Fallback for First Fire / Latest Fire banners without Fault
    if any(p in text_lower for p in ("first fire", "latest fire")):
        if "[status]" not in text_lower and not _has_only_zero_count(text_lower, "fire"):
            return "fire"

    # Supervisory checks (e.g. 'Disablement 1/1')
    if re.search(r"\bdisablement\s+[1-9]\d*[/\\ ]\d+", text_lower):
        return "supervisory"

    # Honeywell idle status menu: '[Status] 1Fires (0 ...'
    if "[status]" in text_lower or _has_only_zero_count(text_lower, "fire"):
        if re.search(r"faults?\s*[\(\[]\s*([1-9]\d*)", text_lower):
            return "fault"
        if re.search(r"disabled\s*[\(\[]\s*([1-9]\d*)", text_lower):
            return "supervisory"
        return "normal"

    # General normal indicators
    if any(k in text_lower for k in ("system normal", "all zones secure", "panel normal")):
        return "normal"

    # Faceplate button row detection:
    # If the text is just a concatenation of printed casing buttons, return normal
    bezel_button_names = [
        "fire", "fault", "disablement", "test", "buzzer muted", "buzzermuted",
        "system fault", "delayed mode", "fire tx activated", "sounders silenced",
        "sounder fault", "sounders disabled", "fire tx disabled", "power",
        "supply fault", "earth fault", "fire tx fault", "en54-2", "en54-4", "lpcb", "ce"
    ]
    bezel_hits = sum(1 for btn in bezel_button_names if btn in text_lower)
    if bezel_hits >= 3 and not re.search(r"\b(?:zone|device|at\s*\d|l\d|a\d)\b", text_lower):
        return "normal"

    # Pure cabinet branding check
    if re.match(r"^(?:honeywell\s+)?(?:fire\s+)?(?:alarm\s+)?(?:system|panel)?$", text_lower.strip()):
        return "normal"

    # Specific fault keywords (when on an alarm screen)
    fault_keywords = (
        "system fault", "sounder fault", "supply fault", "earth fault",
        "battery fault", "open circuit", "short circuit", "loop fault"
    )
    if any(k in text_lower for k in fault_keywords):
        return "fault"

    # Specific supervisory keywords
    if any(k in text_lower for k in ("disablement", "sounders disabled", "delayed mode")):
        return "supervisory"

    # --- Pass 2: fuzzy word match ---
    words = text_lower.split()
    best_category: str | None = None
    best_score = 0.0

    for category, keywords in _VOCABULARY.items():
        for keyword in keywords:
            kw_words = keyword.split()
            if len(kw_words) == 1:
                for word in words:
                    ratio = difflib.SequenceMatcher(None, keyword, word).ratio()
                    if ratio > best_score:
                        best_score = ratio
                        best_category = category
            else:
                for i in range(len(words) - len(kw_words) + 1):
                    phrase = " ".join(words[i : i + len(kw_words)])
                    ratio = difflib.SequenceMatcher(None, keyword, phrase).ratio()
                    if ratio > best_score:
                        best_score = ratio
                        best_category = category

    if best_category and best_score >= _FUZZY_THRESHOLD:
        # Guard: Don't return fire/fault if the only mentions are zero-count
        # status indicators (e.g. "Fire(0)", "Fault(0)", "Fires 0/0")
        if best_category in ("fire", "fault") and _has_only_zero_count(text_lower, best_category):
            return "normal"
        return best_category

    # --- Pass 3: normal / idle ---
    if any(tok in text_lower for tok in ("normal", "secure", "system normal", "all clear", "status")):
        return "normal"

    # Pure date/time / punctuation
    if re.match(r"^[\d\s:\/\.\-]+$", text_lower):
        return "normal"

    return "unknown"
