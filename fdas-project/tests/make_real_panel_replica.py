"""
Generates pixel-accurate synthetic replicas of BOTH real panel photos
observed at the Bekaert site (2026-08 / 2026-09).

Image 1: L1 A053 / OPT  (optical detector, Server Room)
Image 2: L2 A138 / MCP  (manual call point, Utility Room BD)  ← new

Run:
    python3 -m tests.make_real_panel_replica
"""

from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H   = 860, 270
BG     = (43,  90, 155)
FG     = (220, 240, 255)
FG_YEL = (255, 255, 180)
BAR    = (20,  50,  100)
LINE_H = 40
MX, MY = 18, 14

try:
    FONT = ImageFont.truetype("cour.ttf", 22)
    BOLD = ImageFont.truetype("courbd.ttf", 22)
except OSError:
    FONT = BOLD = ImageFont.load_default()


def _render(lines: list[tuple[str, object, bool]], path: Path) -> None:
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    for i, (text, fnt, hi) in enumerate(lines):
        y = MY + i * LINE_H
        if hi:
            draw.rectangle([(0, y - 3), (W, y + LINE_H - 5)], fill=BAR)
            draw.text((MX, y), text, font=fnt, fill=FG_YEL)
        else:
            draw.text((MX, y), text, font=fnt, fill=FG)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))
    print(f"  Saved: {path}")


IMAGES = {
    # ── Image 1: L1 A053, OPT Smoke Detector, Server Room ─────────────────
    "tests/real_panel_replica.png": [
        ("First Fire  Zone 1          08:10 | #Zones", FONT, False),
        ("Latest Fire  Zone 1         08:10 |    1",   FONT, False),
        ("Fire   1/1   at 08:10             << >>",    BOLD, True),
        ("Zone  : 1",                                  FONT, False),
        ("Device: OPT     ABV B100 MC SD L1/53",       FONT, False),
        ("        L1 A053",                             FONT, False),
    ],

    # ── Image 2: L2 A138, MCP Manual Call Point, Utility Room BD ──────────
    "tests/panel_image2.png": [
        ("First Fire  Zone 1          10:01 |#Zones",  FONT, False),
        ("Latest Fire Zone 1          10:01 |  1",     FONT, False),
        ("Fire   1/1   at 10:01            << >>",     BOLD, True),
        ("Zone  : 1",                                  FONT, False),
        ("Device: MCP          UTILITY R BD L2/138",   FONT, False),
        ("       L2 A138",                              FONT, False),
    ],
}


def generate():
    for out, lines in IMAGES.items():
        _render(lines, Path(out))
    print("Done.")


if __name__ == "__main__":
    generate()
