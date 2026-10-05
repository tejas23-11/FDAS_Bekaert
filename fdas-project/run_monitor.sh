#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# FDAS 24/7 Live Monitoring Loop for Raspberry Pi + Arducam 64MP
#
# Usage:
#   ./run_monitor.sh         # Start monitoring in background (or run directly)
#   ./run_monitor.sh --stop  # Stop monitoring and release camera
# ──────────────────────────────────────────────────────────────────────

FDAS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$FDAS_DIR"

LOG_DIR="$FDAS_DIR/logs"
mkdir -p "$LOG_DIR" "panel_inbox"

PID_FILE="$FDAS_DIR/.pids/monitor_loop.pid"
mkdir -p "$FDAS_DIR/.pids"

stop_monitor() {
  echo "[FDAS] Stopping monitoring loop and releasing camera..."
  pkill -f "run_monitor.sh" 2>/dev/null || true
  pkill -f "run_live.py" 2>/dev/null || true
  pkill -f "libcamera-still" 2>/dev/null || true
  rm -f "$PID_FILE"
  echo "[FDAS] Stopped."
}

if [ "$1" == "--stop" ]; then
  stop_monitor
  exit 0
fi

# Clean up any lingering processes first
pkill -f "run_live.py" 2>/dev/null || true
pkill -f "libcamera-still" 2>/dev/null || true

echo "$$" > "$PID_FILE"
echo "[FDAS] Starting 24/7 Live Monitoring Pipeline..."
echo "[FDAS] Logging cleanly to: $LOG_DIR/pipeline.log"

while true; do
  # Remove previous image to guarantee we never process stale frames
  rm -f panel_inbox/live_cam.jpg

  # Capture high-res frame with autofocus delay, suppressing driver noise
  LIBCAMERA_LOG_LEVELS=ERROR libcamera-still -t 1500 --width 1920 --height 1080 -q 90 -o panel_inbox/live_cam.jpg --nopreview >/dev/null 2>&1

  if [ -f panel_inbox/live_cam.jpg ]; then
    python3 run_live.py --image panel_inbox/live_cam.jpg
  else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ Camera capture failed or camera busy. Retrying in 10s..."
    sleep 10
    continue
  fi

  sleep 20
done
