#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# FDAS Desktop Icon Installer
#
# Run this once after cloning the repo to place the FDAS toggle icon
# on the Raspberry Pi desktop.
#
# Usage:
#   chmod +x install_desktop_icon.sh
#   ./install_desktop_icon.sh
#
# Requirements: zenity (pre-installed on Raspberry Pi OS with desktop)
# ──────────────────────────────────────────────────────────────────────

set -e

FDAS_DIR="$HOME/FDAS_Bekaert/fdas-project"
DESKTOP_FILE="$FDAS_DIR/fdas-system.desktop"
TOGGLE_SCRIPT="$FDAS_DIR/fdas_toggle.sh"
ICON_PATH="$FDAS_DIR/ui/static/fdas_icon.png"

echo "============================================="
echo "  FDAS Desktop Icon Installer"
echo "============================================="

# Check FDAS dir exists
if [ ! -d "$FDAS_DIR" ]; then
    echo "[ERROR] FDAS project directory not found: $FDAS_DIR"
    echo "        Update FDAS_DIR at the top of this script to match your install path."
    exit 1
fi

# Make toggle script executable
chmod +x "$TOGGLE_SCRIPT"
echo "[OK] Toggle script made executable: $TOGGLE_SCRIPT"

# Generate a simple icon if one doesn't exist yet
if [ ! -f "$ICON_PATH" ]; then
    echo "[INFO] No icon found at $ICON_PATH"
    # Try to create a simple PNG icon using Python + Pillow (if available)
    python3 - <<'PYEOF' 2>/dev/null && echo "[OK] Icon generated." || echo "[WARN] Could not auto-generate icon — using system default. Install Pillow with: pip install Pillow"
from PIL import Image, ImageDraw, ImageFont
import os

size = 128
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Dark industrial background circle
draw.ellipse([4, 4, size-4, size-4], fill=(30, 30, 40, 255))

# Red flame emoji alternative — draw a simple flame shape
flame_color = (220, 50, 30, 255)
draw.polygon([
    (64, 20), (80, 50), (90, 38), (85, 70),
    (100, 58), (88, 90), (64, 108),
    (40, 90), (28, 58), (43, 70),
    (38, 38), (48, 50)
], fill=flame_color)

# Bright center
draw.ellipse([52, 68, 76, 92], fill=(255, 200, 50, 220))

out = os.path.expanduser("~/FDAS_Bekaert/fdas-project/ui/static/fdas_icon.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
img.save(out)
PYEOF
fi

# Update the .desktop file with the correct absolute path
sed -i "s|/home/pi/FDAS_Bekaert/fdas-project|$FDAS_DIR|g" "$DESKTOP_FILE"
echo "[OK] Updated paths in .desktop file."

# Copy to desktop
DESKTOP_DIR="$HOME/Desktop"
mkdir -p "$DESKTOP_DIR"
cp "$DESKTOP_FILE" "$DESKTOP_DIR/fdas-system.desktop"
chmod +x "$DESKTOP_DIR/fdas-system.desktop"
echo "[OK] Desktop icon installed at: $DESKTOP_DIR/fdas-system.desktop"

# Trust the desktop file (LXDE/PIXEL on Raspberry Pi OS)
if command -v gio &>/dev/null; then
    gio set "$DESKTOP_DIR/fdas-system.desktop" metadata::trusted true 2>/dev/null && \
        echo "[OK] Desktop file trusted (gio)." || true
fi

# Also install to application menu
APP_DIR="$HOME/.local/share/applications"
mkdir -p "$APP_DIR"
cp "$DESKTOP_FILE" "$APP_DIR/fdas-system.desktop"
echo "[OK] Application menu entry installed."

echo ""
echo "============================================="
echo "  Installation complete!"
echo ""
echo "  ✅ Double-click the FDAS icon on your desktop"
echo "     to start or stop the system."
echo ""
echo "  💡 Tip: You can also run directly:"
echo "     $TOGGLE_SCRIPT"
echo "============================================="

