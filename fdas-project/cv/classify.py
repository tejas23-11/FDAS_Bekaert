"""
Classifies the OCR'd text from the Honeywell fire-alarm panel screen.

Vocabulary updated from the real panel photo (Bekaert site, 2026-08):
  Fire state    → "Fire", "First Fire", "Latest Fire"
  Fault state   → "Fault", "System Fault", "Sounder Fault", "Supply Fault",
                  "Earth Fault"
  Supervisory   → "Disablement", "Delayed Mode", "Sounders Disabled",
                  "Fire TX Disabled"
  Normal/idle   → no alarm/fault keywords present

Keywords are lower-case strings.  Direct substring match is tried first
(exact wording wins immediately); fuzzy matching is the fallback for OCR
noise or minor formatting differences.  The threshold (0.82) and keyword
lists are easy to tighten once real panel wording is fully catalogued --
see hardware/CALIBRATION.md.

Owner: Member 2
"""

from __future__ import annotations

import difflib

# ---------------------------------------------------------------------------
# Vocabulary (tighten when real panel wording is confirmed for every state)
# ---------------------------------------------------------------------------
_VOCABULARY: dict[str, list[str]] = {
    "fire": [
        # Confirmed from site photo
        "fire",
        "first fire",
        "latest fire",
        # Generic / inferred backups
        "smoke",
        "heat",
        "manual call point",
        "mcp",
    ],
    "fault": [
        # Confirmed from site photo button labels
        "fault",
        "system fault",
        "sounder fault",
        "supply fault",
        "earth fault",
        # Generic backups
        "trouble",
        "detector fault",
    ],
    "supervisory": [
        # Confirmed from site photo button labels
        "disablement",
        "delayed mode",
        "sounders disabled",
        "fire tx disabled",
        "fire tx activated",
        # Generic backups
        "supervisory",
        "prealarm",
        "pre-alarm",
        "pre alarm",
        "bypassed",
        "disabled",
    ],
}

_FUZZY_THRESHOLD = 0.82   # raise toward 0.9 once vocabulary is final


def classify_message(text: str) -> str:
    """
    Takes OCR'd raw text and returns one of:
    ``fire`` | ``fault`` | ``supervisory`` | ``normal`` | ``unknown``.

    Strategy:
      1. Exact substring match (fastest, wins immediately).
      2. Fuzzy word-level match via difflib SequenceMatcher.
      3. "normal" / "secure" / "system normal" fallback.
      4. Default to ``unknown``.
    """
    if not text:
        return "unknown"

    text_lower = text.lower()

    import re

    # --- Guard: Strip static plastic faceplate labels & cabinet branding ---
    # The words "FIRE FAULT..." printed below or on the LCD bezel are plastic labels, not fire!
    faceplate_patterns = [
        r"\bfire\s+fault\s+(?:disablement\s+)?buzzer\s+muted.*",
        r"\bfire\s+fault\s+buzzer\s+muted.*",
        r"\b(?:system\s+fault\s+)?delayed\s+mode\s+sounders\s+silenced.*",
        r"\bfire\s+alarm\s+control\s+panel\b",
        r"\bfire\s+alarm\s+system\b",
        r"\bhoneywell\s+fire\b",
        r"\bhoneywell\b",
        r"\bintelligent\s+fire\b",
        r"\bfire\s+protection\b",
    ]
    for pat in faceplate_patterns:
        text_lower = re.sub(pat, "", text_lower).strip()

    # If all detected text was just static faceplate labels, it's normal / idle
    if not text_lower:
        return "normal"

    # --- Guard: Prealarm is a supervisory warning, NOT a confirmed fire ---
    # e.g. "Prealarm Zone1 1/1 at 20:29 Device: OPT L1 A053..."
    if any(kw in text_lower for kw in ("prealarm", "pre-alarm", "pre alarm")):
        return "supervisory"

    # --- Step 1: Confirmed Active Fire Alarm Banner ----------------------
    # Active fire event indicators that definitively signify an active fire
    active_fire_patterns = (
        "first fire",
        "latest fire",
        "fire 1/",
        "fire 2/",
        "fire 3/",
        "fire 4/",
        "fire at",
        "smoke detected",
        "heat detected",
        "fire alarm active",
        "fire evacuation",
    )
    if any(p in text_lower for p in active_fire_patterns):
        return "fire"

    has_active_fire_count = re.search(r"fires?\s*[\(\[]\s*([1-9]\d*)\s*[\)\]]", text_lower)
    if has_active_fire_count:
        return "fire"

    # --- Step 2: Honeywell idle / status menu ----------------------------
    # If the screen is the Honeywell status menu ([Status] 1 Fires (0) 2 Faults (0) 3 Disabled (0)...)
    if "[status]" in text_lower or re.search(r"fires?\s*[\(\[]\s*0\b", text_lower):
        has_active_fault = re.search(r"faults?\s*[\(\[]\s*([1-9]\d*)\s*[\)\]]", text_lower)
        if has_active_fault:
            return "fault"
        has_active_dis = re.search(r"disabled\s*[\(\[]\s*([1-9]\d*)\s*[\)\]]", text_lower)
        if has_active_dis:
            return "supervisory"
        return "normal"

    # --- Step 3: Confirmed Fault Indicators ------------------------------
    # Even if "fire" appears as part of a device/loop name ("Fire Loop 1 Fault",
    # "Honeywell Fire Panel Fault"), presence of fault keywords means it's a FAULT, not a fire!
    fault_keywords = (
        "system fault",
        "sounder fault",
        "supply fault",
        "earth fault",
        "detector fault",
        "loop fault",
        "power fault",
        "battery fault",
        "open circuit",
        "short circuit",
        "fault 1/",
        "fault 2/",
        "fault at",
        "trouble",
    )
    if any(kw in text_lower for kw in fault_keywords):
        return "fault"

    # Single-word "fault" or "faults" check
    if re.search(r"\bfaults?\b", text_lower):
        return "fault"

    # --- Step 4: Supervisory / Disablement -------------------------------
    supervisory_keywords = (
        "disablement",
        "delayed mode",
        "sounders disabled",
        "fire tx disabled",
        "fire tx activated",
        "supervisory",
        "bypassed",
        "disabled",
    )
    if any(kw in text_lower for kw in supervisory_keywords):
        return "supervisory"

    # --- Step 5: Isolated fire keywords ----------------------------------
    if re.search(r"\b(fire|smoke|heat|mcp|manual call point)\b", text_lower):
        return "fire"

    # --- Pass 2: fuzzy word match ----------------------------------------
    words = text_lower.split()
    best_category: str | None = None
    best_score = 0.0

    for category, keywords in _VOCABULARY.items():
        for keyword in keywords:
            kw_words = keyword.split()
            # Single-word keyword: compare against every word in OCR text
            if len(kw_words) == 1:
                for word in words:
                    ratio = difflib.SequenceMatcher(None, keyword, word).ratio()
                    if ratio > best_score:
                        best_score = ratio
                        best_category = category
            else:
                # Multi-word keyword: compare as a phrase against a sliding window
                for i in range(len(words) - len(kw_words) + 1):
                    phrase = " ".join(words[i : i + len(kw_words)])
                    ratio = difflib.SequenceMatcher(None, keyword, phrase).ratio()
                    if ratio > best_score:
                        best_score = ratio
                        best_category = category

    if best_category and best_score >= _FUZZY_THRESHOLD:
        return best_category

    # --- Pass 3: normal / idle -------------------------------------------
    if any(tok in text_lower for tok in ("normal", "secure", "system normal", "all clear", "status")):
        return "normal"

    return "unknown"
