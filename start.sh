#!/bin/bash
# Job Agent — start everything and keep it alive
# Usage: bash start.sh

cd /Users/jefersongrueso/job-agent

NGROK_DOMAIN="nonfeeding-malinda-supervast.ngrok-free.dev"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') [watchdog] $1" | tee -a "$LOG_DIR/watchdog.log"; }

# ── Prevent Mac from sleeping ────────────────────────────────────────────────
pkill caffeinate 2>/dev/null
caffeinate -dims &
CAFFEINATE_PID=$!
log "caffeinate started (PID $CAFFEINATE_PID) — Mac will not sleep"

# ── Start functions ──────────────────────────────────────────────────────────
start_ngrok() {
    pkill ngrok 2>/dev/null; sleep 1
    ngrok http 8080 --url="$NGROK_DOMAIN" --log=stdout > /tmp/ngrok.log 2>&1 &
    echo $! > /tmp/ngrok.pid
    sleep 4
    if grep -q "started tunnel" /tmp/ngrok.log 2>/dev/null; then
        log "ngrok tunnel UP → https://$NGROK_DOMAIN"
    else
        log "ngrok tunnel FAILED — check /tmp/ngrok.log"
    fi
}

start_bot() {
    kill $(cat /tmp/job-agent.lock 2>/dev/null) 2>/dev/null; sleep 2
    python3.14 main.py >> "$LOG_DIR/bot.log" 2>&1 &
    sleep 5
    if [ -f /tmp/job-agent.lock ] && kill -0 $(cat /tmp/job-agent.lock) 2>/dev/null; then
        log "bot UP (PID $(cat /tmp/job-agent.lock))"
    else
        log "bot FAILED — check logs/bot.log"
    fi
}

# ── Initial startup ──────────────────────────────────────────────────────────
log "=== Job Agent starting ==="
start_ngrok
start_bot

# ── Watchdog loop (checks every 60s) ────────────────────────────────────────
while true; do
    sleep 60

    # Check ngrok
    NGROK_PID=$(cat /tmp/ngrok.pid 2>/dev/null)
    if ! kill -0 "$NGROK_PID" 2>/dev/null; then
        log "ngrok down — restarting..."
        start_ngrok
    fi

    # Check bot
    BOT_PID=$(cat /tmp/job-agent.lock 2>/dev/null)
    if ! kill -0 "$BOT_PID" 2>/dev/null; then
        log "bot down — restarting..."
        start_bot
    fi
done
