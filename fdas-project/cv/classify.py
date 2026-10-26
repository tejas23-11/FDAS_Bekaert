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


def classify_message(text: str) -> str:
    """
    Takes OCR'd raw text and returns one of:
    ``fire`` | ``fault`` | ``supervisory`` | ``normal`` | ``unknown``.
    """
    if not text or not text.strip():
        return "unknown"

    text_lower = text.lower().strip()

    # --- Guard: Strip static cabinet branding & painted faceplate labels ---
    faceplate_patterns = [
        r"\bfire\s+fault\s+(?:disablement\s+)?buzzer\s+muted.*",
        r"\bfire\s+fault\s+buzzer\s+muted.*",
        r"\b(?:system\s+fault\s+)?delayed\s+mode\s+sounders\s+silenced.*",
        r"\bfire\s+fault\s+(?:power|test|areal)?\b",
        r"\bfire\s+fault\b",
        r"\bfire\s+alarm\s+control\s+panel\b",
        r"\bfire\s+alarm\s+system\b",
        r"\bhoneywell\s+fire\b",
        r"\bhoneywell\b",
        r"\bintelligent\s+fire\b",
        r"\bfire\s+protection\b",
    ]
    for pat in faceplate_patterns:
        text_lower = re.sub(pat, "", text_lower).strip(" -:\t\r\n")

    # If all detected text was just static faceplate labels, it's normal / idle
    if not text_lower:
        return "normal"

    # Single isolated static word check (e.g. only 'fire' or 'fault' or 'power' on bezel)
    if re.match(r"^(?:fire|fault|power|test|buzzer|muted)$", text_lower):
        return "normal"

    # --- Guard: Prealarm is a supervisory warning, NOT a confirmed fire ---
    if any(kw in text_lower for kw in ("prealarm", "pre-alarm", "pre alarm")):
        return "supervisory"

    # --- Step 1: Confirmed Active Fire Alarm Banner (Definitive) ----------
    definitive_fire = (
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
    if any(p in text_lower for p in definitive_fire):
        return "fire"

    if re.search(r"fires?\s*[\(\[]\s*([1-9]\d*)\s*[\)\]]", text_lower):
        return "fire"

    # --- Step 2: Confirmed Fault Banners (e.g. 'Fault 1/1', 'Detector Fault in Fire Zone') ---
    explicit_fault_banners = (
        "fault 1/", "fault 2/", "fault 3/", "fault at",
        "detector fault", "fault in fire", "loop fault",
        "sounder fault", "supply fault", "earth fault",
        "battery fault", "open circuit", "short circuit"
    )
    if any(kw in text_lower for kw in explicit_fault_banners):
        return "fault"

    # --- Step 3: Active Fire Context (Fire + Zone, or Fire + Timestamp, or Fire + Device) ---
    if re.search(r"\bfire\s+zone\b", text_lower) or re.search(r"\bfire\b.*\bzone\s*[:#-]?\s*\d+", text_lower):
        return "fire"
    if re.search(r"\bfire\b.*\b(?:at\s*)?\d{1,2}:\d{2}\b", text_lower):
        return "fire"
    if re.search(r"\bfire\b.*\b(opt|mcp|sd|l\d|a\d{2,3})\b", text_lower):
        return "fire"

    # --- Step 4: Honeywell idle / status menu ----------------------------
    if "[status]" in text_lower or re.search(r"fires?\s*[\(\[]\s*0\b", text_lower):
        has_active_fault = re.search(r"faults?\s*[\(\[]\s*([1-9]\d*)", text_lower)
        if has_active_fault:
            return "fault"
        has_active_dis = re.search(r"disabled\s*[\(\[]\s*([1-9]\d*)", text_lower)
        if has_active_dis:
            return "supervisory"
        return "normal"

    # --- Step 5: Remaining Fault Keywords --------------------------------
    if "system fault" in text_lower or "trouble" in text_lower:
        return "fault"
    if re.search(r"\bfaults?\b", text_lower):
        return "fault"

    # --- Step 6: Supervisory / Disablement -------------------------------
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

    # --- Step 7: Isolated fire keywords ----------------------------------
    if re.search(r"\b(fire|smoke|heat|mcp|manual call point)\b", text_lower):
        return "fire"

    # --- Pass 2: fuzzy word match ----------------------------------------
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
        return best_category

    # --- Pass 3: normal / idle -------------------------------------------
    if any(tok in text_lower for tok in ("normal", "secure", "system normal", "all clear", "status")):
        return "normal"

    # Pure date/time / punctuation
    if re.match(r"^[\d\s:\/\.\-]+$", text_lower):
        return "normal"

    return "unknown"
