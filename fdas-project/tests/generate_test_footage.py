"""
Generates synthetic Honeywell-panel-style screen images for the CV pipeline
test rig.  Text and layout are modelled on the real panel photo taken at the
Bekaert site (2026-08).

Uses Pillow (already installed) instead of cv2 to avoid the numpy 1.26 /
Python 3.13 MINGW access-violation crash on Windows.  cv2 is still used by
the pipeline itself at runtime; the test image files just need to be PNGs on
disk, which Pillow handles fine.

Produces 5 PNG frames per state under tests/sample_footage/<state>/.

Usage:
    python3 -m tests.generate_test_footage
"""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Design constants (match real panel LCD appearance)
# ---------------------------------------------------------------------------
IMG_W, IMG_H = 1280, 480
BG_BLUE   = (43,  90, 139)   # RGB – approximates the Honeywell panel's blue LCD
FG_WHITE  = (255, 255, 255)
FG_YELLOW = (220, 220,   0)  # highlighted / active row
LINE_H    = 52
MARGIN_X  = 30
MARGIN_Y  = 40

try:
    # Monospaced font makes it look like a real character LCD
    _FONT = ImageFont.truetype("cour.ttf", 26)
except OSError:
    _FONT = ImageFont.load_default()


# ---------------------------------------------------------------------------
# Scenario definitions – text copied verbatim from the real site photo
# ---------------------------------------------------------------------------
_SCENARIOS: dict[str, list[tuple[str, tuple[int, int, int]]]] = {
    "fire": [
        ("First Fire  Zone 1          08:10 | #Zones", FG_WHITE),
        ("Latest Fire  Zone 1         08:10 |    1",   FG_WHITE),
        ("Fire    1/1   at 08:10            << >>",    FG_YELLOW),
        ("Zone  : 1",                                  FG_WHITE),
        ("Device: OPT     ABV B100 MC SD L1/53",       FG_WHITE),
        ("        L1 A053",                             FG_WHITE),
    ],
    "fault": [
        ("Fault   1/1   at 08:10            << >>",    FG_YELLOW),
        ("Zone  : 1",                                  FG_WHITE),
        ("Device: OPT     ABV B100 MC SD L1/53",       FG_WHITE),
        ("        L1 A053",                             FG_WHITE),
        ("System Fault",                                FG_WHITE),
    ],
    "supervisory": [
        ("Disablement   1/1",                           FG_YELLOW),
        ("Zone  : 1",                                   FG_WHITE),
        ("Device: OPT     ABV B100 MC SD L1/53",        FG_WHITE),
        ("        L1 A053",                              FG_WHITE),
        ("Sounders Disabled",                           FG_WHITE),
    ],
    "normal": [
        ("System Normal",                               FG_WHITE),
        ("All Zones Secure",                            FG_WHITE),
        ("                                   08:10",   FG_WHITE),
    ],
}


def _make_frame(lines: list[tuple[str, tuple[int, int, int]]]) -> Image.Image:
    img  = Image.new("RGB", (IMG_W, IMG_H), BG_BLUE)
    draw = ImageDraw.Draw(img)
    for i, (text, colour) in enumerate(lines):
        y = MARGIN_Y + i * LINE_H
        draw.text((MARGIN_X, y), text, font=_FONT, fill=colour)
    return img


def generate() -> None:
    for state, lines in _SCENARIOS.items():
        out_dir = Path(f"tests/sample_footage/{state}")
        out_dir.mkdir(parents=True, exist_ok=True)
        frame = _make_frame(lines)
        for i in range(5):
            frame.save(str(out_dir / f"frame_{i:03d}.png"))
        print(f"  {state}: 5 frames -> {out_dir}")

    print("Done.  Footage in tests/sample_footage/")


if __name__ == "__main__":
    generate()

