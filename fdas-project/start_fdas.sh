#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# FDAS Startup Script — launches the full FDAS system
#
# This script starts:
#   1. The detection pipeline (cv.capture or run_live.py --watch)
#   2. The watchdog (health_monitor.py)
#   3. The web UI (ui/app.py)
#
# Usage:
#   ./start_fdas.sh              # Start all services
#   ./start_fdas.sh --dry-run    # Start in dry-run mode (no real SMS)
#   ./start_fdas.sh --stop       # Stop all services
#
# Owner: Member 1 (Hardware Integration)
# ──────────────────────────────────────────────────────────────────────

set -e

# ── Configuration ─────────────────────────────────────────────────────
FDAS_DIR="$HOME/FDAS_Bekaert/fdas-project"
VENV_DIR="$FDAS_DIR/venv"
LOG_DIR="$FDAS_DIR/logs"
PID_DIR="$FDAS_DIR/.pids"
DRY_RUN=""

# Parse arguments
for arg in "$@"; do
    case $arg in
        --dry-run) DRY_RUN="--dry-run" ;;
        --stop)    STOP=true ;;
    esac
done

# ── Stop function ─────────────────────────────────────────────────────
stop_fdas() {
    echo "[FDAS] Stopping all services..."
    
    # Kill by PID files
    for pidfile in "$PID_DIR"/*.pid; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
                echo "  Stopped PID $pid ($(basename "$pidfile" .pid))"
            fi
            rm -f "$pidfile"
        fi
    done
    
    # Also kill by process name (safety net)
    pkill -f "cv.capture" 2>/dev/null || true
    pkill -f "run_live" 2>/dev/null || true
    pkill -f "watchdog.health_monitor" 2>/dev/null || true
    pkill -f "ui.app" 2>/dev/null || true
    
    echo "[FDAS] All services stopped."
}

if [ "$STOP" = true ]; then
    stop_fdas
    exit 0
fi

# ── Pre-flight checks ────────────────────────────────────────────────
if [ ! -d "$FDAS_DIR" ]; then
    echo "[FDAS] ERROR: Project directory not found: $FDAS_DIR"
    echo "       Clone the repo first: git clone https://github.com/tejas23-11/FDAS_Bekaert.git"
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "[FDAS] ERROR: Virtual environment not found: $VENV_DIR"
    echo "       Create it: cd $FDAS_DIR && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Create directories
mkdir -p "$LOG_DIR" "$PID_DIR" "$FDAS_DIR/panel_inbox"

# ── Activate venv ─────────────────────────────────────────────────────
cd "$FDAS_DIR"
source "$VENV_DIR/bin/activate"

# ── Initialize database ──────────────────────────────────────────────
echo "[FDAS] Initializing database..."
python3 -m backend.db

# ── Stop any existing FDAS processes ──────────────────────────────────
stop_fdas

# ── Start services ────────────────────────────────────────────────────
echo ""
echo "============================================="
echo "  FDAS — Starting All Services"
echo "  Mode: $([ -n "$DRY_RUN" ] && echo "DRY-RUN" || echo "LIVE")"
echo "  Time: $(date)"
echo "============================================="
echo ""

# 1. Detection Pipeline (camera-based)
echo "[FDAS] Starting detection pipeline..."
python3 -m cv.capture --source 0 $DRY_RUN \
    >> "$LOG_DIR/pipeline.log" 2>&1 &
PIPELINE_PID=$!
echo "$PIPELINE_PID" > "$PID_DIR/pipeline.pid"
echo "  Pipeline PID: $PIPELINE_PID (log: $LOG_DIR/pipeline.log)"

# 2. Watchdog
echo "[FDAS] Starting health monitor..."
python3 -m watchdog.health_monitor \
    >> "$LOG_DIR/watchdog.log" 2>&1 &
WATCHDOG_PID=$!
echo "$WATCHDOG_PID" > "$PID_DIR/watchdog.pid"
echo "  Watchdog PID: $WATCHDOG_PID (log: $LOG_DIR/watchdog.log)"

# 3. Web UI
echo "[FDAS] Starting web UI..."
python3 -m ui.app \
    >> "$LOG_DIR/ui.log" 2>&1 &
UI_PID=$!
echo "$UI_PID" > "$PID_DIR/ui.pid"
echo "  Web UI PID: $UI_PID (log: $LOG_DIR/ui.log)"

echo ""
echo "[FDAS] All services started successfully!"
echo "  Dashboard: http://$(hostname -I | awk '{print $1}'):5000"
echo "  Logs:      $LOG_DIR/"
echo ""
echo "  To stop: $0 --stop"
