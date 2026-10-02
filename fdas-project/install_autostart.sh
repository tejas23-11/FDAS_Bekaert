#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# FDAS Installation Script — sets up autostart + desktop icon on Pi
#
# Run this ONCE on the Raspberry Pi after cloning the project:
#     chmod +x install_autostart.sh
#     ./install_autostart.sh
#
# What it does:
#   1. Creates the log directory
#   2. Installs systemd services for pipeline, watchdog, and web UI
#   3. Enables them to start on boot
#   4. Creates a desktop shortcut icon
#   5. Opens the browser to the dashboard on login (via autostart)
#
# Owner: Member 1
# ──────────────────────────────────────────────────────────────────────

set -e

FDAS_DIR="$HOME/FDAS_Bekaert/fdas-project"
SYSTEMD_DIR="$FDAS_DIR/systemd"
USER_SYSTEMD="$HOME/.config/systemd/user"
DESKTOP_DIR="$HOME/Desktop"
AUTOSTART_DIR="$HOME/.config/autostart"

echo ""
echo "============================================="
echo "  FDAS — Autostart Installation"
echo "============================================="
echo ""

# ── Pre-flight checks ────────────────────────────────────────────────
if [ ! -d "$FDAS_DIR" ]; then
    echo "[FAIL] Project directory not found: $FDAS_DIR"
    exit 1
fi

# ── 1. Create directories ────────────────────────────────────────────
echo "[1/5] Creating directories..."
mkdir -p "$FDAS_DIR/logs"
mkdir -p "$FDAS_DIR/.pids"
mkdir -p "$FDAS_DIR/panel_inbox"
mkdir -p "$DESKTOP_DIR"
mkdir -p "$AUTOSTART_DIR"
echo "  Done."

# ── 2. Install systemd services ──────────────────────────────────────
echo "[2/5] Installing systemd services..."

# Copy service files to system directory
sudo cp "$SYSTEMD_DIR/fdas-pipeline.service" /etc/systemd/system/
sudo cp "$SYSTEMD_DIR/fdas-watchdog.service" /etc/systemd/system/
sudo cp "$SYSTEMD_DIR/fdas-ui.service" /etc/systemd/system/

# Update the User field in case it's not 'pi'
CURRENT_USER=$(whoami)
if [ "$CURRENT_USER" != "pi" ]; then
    echo "  Updating service user to: $CURRENT_USER"
    sudo sed -i "s/User=pi/User=$CURRENT_USER/g" /etc/systemd/system/fdas-*.service
    sudo sed -i "s|/home/pi/|/home/$CURRENT_USER/|g" /etc/systemd/system/fdas-*.service
fi

sudo systemctl daemon-reload
echo "  Service files installed."

# ── 3. Enable autostart on boot ──────────────────────────────────────
echo "[3/5] Enabling autostart on boot..."
sudo systemctl enable fdas-pipeline.service
sudo systemctl enable fdas-watchdog.service
sudo systemctl enable fdas-ui.service
echo "  All 3 services enabled."

# ── 4. Create desktop shortcut ────────────────────────────────────────
echo "[4/5] Creating desktop shortcut..."

cat > "$DESKTOP_DIR/FDAS.desktop" << EOF
[Desktop Entry]
Type=Application
Name=FDAS Monitor
Comment=Fire Detection & Alarm System — Open Dashboard
Icon=dialog-warning
Exec=bash -c "xdg-open http://localhost:5000 || chromium-browser http://localhost:5000 || firefox http://localhost:5000"
Terminal=false
Categories=Utility;
StartupNotify=true
EOF

chmod +x "$DESKTOP_DIR/FDAS.desktop"

# Trust the desktop file (LXDE/Pi OS)
if command -v gio &> /dev/null; then
    gio set "$DESKTOP_DIR/FDAS.desktop" metadata::trusted true 2>/dev/null || true
fi

echo "  Desktop shortcut created: $DESKTOP_DIR/FDAS.desktop"

# ── 5. Auto-open browser on login ─────────────────────────────────────
echo "[5/5] Setting up browser auto-open on login..."

cat > "$AUTOSTART_DIR/fdas-browser.desktop" << EOF
[Desktop Entry]
Type=Application
Name=FDAS Dashboard Browser
Comment=Open FDAS dashboard in browser on login
Exec=bash -c "sleep 10 && (xdg-open http://localhost:5000 || chromium-browser http://localhost:5000)"
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
EOF

echo "  Browser autostart configured."

echo ""
echo "============================================="
echo "  Installation Complete!"
echo "============================================="
echo ""
echo "  Services will start automatically on next boot."
echo "  To start them now:"
echo "    sudo systemctl start fdas-pipeline"
echo "    sudo systemctl start fdas-watchdog"
echo "    sudo systemctl start fdas-ui"
echo ""
echo "  To check status:"
echo "    sudo systemctl status fdas-pipeline"
echo "    sudo systemctl status fdas-ui"
echo ""
echo "  Desktop shortcut: $DESKTOP_DIR/FDAS.desktop"
echo "  Dashboard URL: http://localhost:5000"
echo ""
echo "  To UNINSTALL autostart:"
echo "    sudo systemctl disable fdas-pipeline fdas-watchdog fdas-ui"
echo "    sudo rm /etc/systemd/system/fdas-*.service"
echo "    rm $DESKTOP_DIR/FDAS.desktop"
echo "    rm $AUTOSTART_DIR/fdas-browser.desktop"
echo ""
