#!/usr/bin/env bash
# Keep the paper agent alive.
#
# The agent loop exits on its own for ordinary reasons (a bad candle, an LLM
# timeout, the process being killed). Any of those used to mean a dead system
# until someone noticed. This restarts it, keeping a bounded log and a backoff
# so a crash loop cannot spin the CPU.
#
# Usage: supervise_agent.sh [seconds between health checks]
set -uo pipefail

ROOT="/home/wempya/projects/AI-Trader-hermes-client"
VENV="/home/wempya/projects/AI-Trader/.venv/bin"
LOG_DIR="$ROOT/data/supervisor"
STATE="$ROOT/data/agent_dashboard_state.json"
LOG="$LOG_DIR/agent.log"
PIDFILE="$LOG_DIR/supervisor.pid"
INTERVAL="${1:-3700}"
RESTART_DELAY=15
MAX_BACKOFF=300
backoff=$RESTART_DELAY

mkdir -p "$LOG_DIR"
cd "$ROOT" || exit 1
export PATH="$VENV:$PATH"
export PYTHONPATH=.

log() { printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"; }

# Refuse to start a second supervisor. Two of these means two agents trading
# against the same paper ledger and writing the same state file, which is far
# worse than not running at all.
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
    echo "supervisor already running as pid $(cat "$PIDFILE")"
    exit 1
fi
# Clear out any orphaned agent from a previous supervisor before we start.
pkill -9 -f "run_agent.py .*--forever" 2>/dev/null
sleep 2

echo $$ > "$PIDFILE"
log "supervisor start pid=$$ interval=${INTERVAL}s"

cleanup() {
    log "supervisor stopping, killing child"
    [ -n "${CHILD:-}" ] && kill "$CHILD" 2>/dev/null
    rm -f "$PIDFILE"
    exit 0
}
trap cleanup INT TERM

while true; do
    # --forever removes the cycle ceiling; this is what makes it a real
    # always-on agent rather than a batch job that quietly ends.
    python run_agent.py \
        --backend remote \
        --entry-mode \
        --forever \
        --port 8788 \
        --hold \
        >> "$LOG" 2>&1 &
    CHILD=$!
    log "started agent pid=$CHILD"

    # Wait, then confirm the dashboard is still answering. A wedged process
    # looks alive to `kill -0` but stops serving, so check the HTTP endpoint.
    while kill -0 "$CHILD" 2>/dev/null; do
        sleep "$INTERVAL"
        kill -0 "$CHILD" 2>/dev/null || break
        if command -v curl >/dev/null 2>&1; then
            if ! curl -fs --max-time 8 http://127.0.0.1:8788/api/state >/dev/null 2>&1; then
                log "dashboard not answering, restarting child"
                kill "$CHILD" 2>/dev/null
                sleep 3
                break
            fi
        fi
    done

    wait "$CHILD" 2>/dev/null
    code=$?
    log "agent exited code=$code, restart in ${backoff}s"
    sleep "$backoff"

    # Escalate only while it keeps failing; reset once it stays up.
    if [ -f "$STATE" ]; then
        started=$(python3 - "$STATE" <<'PY' 2>/dev/null || echo 0
import json, sys, time
d = json.load(open(sys.argv[1]))
print(int(d.get("started_at_ms") or 0))
PY
)
        if [ "${started:-0}" -gt 0 ] && [ $(( $(date +%s) * 1000 - started )) -gt $(( INTERVAL * 1000 )) ]; then
            backoff=$RESTART_DELAY
        fi
    fi
    [ "$backoff" -lt "$MAX_BACKOFF" ] && backoff=$(( backoff * 2 ))
done
