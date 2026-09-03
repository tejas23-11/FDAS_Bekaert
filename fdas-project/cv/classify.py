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

    # --- Pass 1: exact substring -----------------------------------------
    for category, keywords in _VOCABULARY.items():
        for keyword in keywords:
            if keyword in text_lower:
                return category

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
    if any(tok in text_lower for tok in ("normal", "secure", "system normal", "all clear")):
        return "normal"

    return "unknown"
