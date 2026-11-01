#!/bin/bash
# ──────────────────────────────────────────────────────────────────────
# FDAS System Toggle — Start if stopped, Stop if running.
#
# Designed to be launched from a desktop icon (double-click on Pi desktop).
# Requires: zenity (pre-installed on Raspberry Pi OS with desktop)
#
# Usage:
#   ./fdas_toggle.sh              (via desktop icon)
#   ./fdas_toggle.sh --start      (force start)
#   ./fdas_toggle.sh --stop       (force stop)
#
# Owner: FDAS Team
# ──────────────────────────────────────────────────────────────────────

FDAS_DIR="$HOME/FDAS_Bekaert/fdas-project"
PID_DIR="$FDAS_DIR/.pids"

# ── Check if any FDAS process is alive ────────────────────────────────
is_running() {
    # Method 1: Check PID files
    if [ -d "$PID_DIR" ]; then
        for pidfile in "$PID_DIR"/*.pid; do
            [ -f "$pidfile" ] || continue
            pid=$(cat "$pidfile" 2>/dev/null)
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                return 0  # Running
            fi
        done
    fi
    # Method 2: Fallback — check by process name
    pgrep -f "run_live\|cv\.capture\|ui\.app\|health_monitor" > /dev/null 2>&1
}

# ── Start all FDAS services ───────────────────────────────────────────
do_start() {
    local mode="$1"  # "--dry-run" or ""
    cd "$FDAS_DIR" || { zenity --error --text="FDAS directory not found: $FDAS_DIR" --width=320; exit 1; }
    bash "$FDAS_DIR/start_fdas.sh" $mode &
    sleep 3
    zenity --info \
        --title="FDAS System" \
        --text="✅ FDAS started$([ -n '$mode' ] && echo ' (DRY-RUN)' || echo ' in LIVE mode').\n\n📊 Dashboard: http://localhost:5000\n\nThe system will now monitor the fire panel." \
        --width=340 \
        --timeout=8
}

# ── Stop all FDAS services ────────────────────────────────────────────
do_stop() {
    bash "$FDAS_DIR/start_fdas.sh" --stop
    zenity --info \
        --title="FDAS System" \
        --text="🛑 All FDAS services have been stopped." \
        --width=320 \
        --timeout=5
}

# ── Handle explicit flags ─────────────────────────────────────────────
case "$1" in
    --start) do_start ""; exit 0 ;;
    --stop)  do_stop;     exit 0 ;;
esac

# ── Interactive toggle ────────────────────────────────────────────────
if is_running; then
    # System is RUNNING → offer to stop
    zenity --question \
        --title="FDAS System — Running" \
        --text="🟢 FDAS is currently <b>RUNNING</b>.\n\nDo you want to stop all services?" \
        --ok-label="Stop System" \
        --cancel-label="Cancel" \
        --width=340
    if [ $? -eq 0 ]; then
        do_stop
    fi
else
    # System is STOPPED → offer to start
    CHOICE=$(zenity --list \
        --title="FDAS System — Stopped" \
        --text="🔴 FDAS is currently <b>STOPPED</b>.\n\nChoose how to start:" \
        --radiolist \
        --column="" --column="Mode" \
        TRUE  "Live Mode (real SMS & calls)" \
        FALSE "Dry-Run Mode (no real SMS, for testing)" \
        --width=400 --height=250)

    case "$CHOICE" in
        "Live Mode (real SMS & calls)")
            zenity --question \
                --title="Confirm Start — Live Mode" \
                --text="⚠️ Starting in <b>LIVE mode</b>.\n\nReal SMS and voice calls will be sent during alerts.\n\nProceed?" \
                --ok-label="Yes, Start Live" \
                --cancel-label="Cancel" \
                --width=340
            [ $? -eq 0 ] && do_start ""
            ;;
        "Dry-Run Mode (no real SMS, for testing)")
            do_start "--dry-run"
            ;;
    esac
fi

