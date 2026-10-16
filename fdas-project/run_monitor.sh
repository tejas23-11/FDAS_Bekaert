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
  # Touch heartbeat for watchdog
  touch /tmp/fdas_heartbeat 2>/dev/null || true

  # Run fast continuous in-memory monitoring loop (3s interval, PaddleOCR stays in RAM)
  export PYTHONUNBUFFERED=1
  python3 -u run_live.py --live --interval 3

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ Pipeline loop exited. Restarting in 5s..."
  sleep 5
done
