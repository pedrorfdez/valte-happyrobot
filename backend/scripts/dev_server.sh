#!/usr/bin/env bash
# Restart the backend for local work. Usage: scripts/dev_server.sh [port] (env vars pass through)
cd "$(dirname "$0")/.." || exit 1
PORT="${1:-8010}"
LOG="${VALTE_LOG:-/tmp/valte-$PORT.log}"
pkill -f "[u]vicorn valte.main:app .*--port $PORT" 2>/dev/null
# uvicorn's graceful exit waits for the dashboard's open event streams, and meanwhile the old engine keeps ticking on
# the same database (two kernels, every HappyRobot run dispatched twice): give it 3 s, then kill it for real.
for _ in 1 2 3 4 5 6; do pgrep -f "[u]vicorn valte.main:app .*--port $PORT" > /dev/null || break; sleep 0.5; done
pkill -9 -f "[u]vicorn valte.main:app .*--port $PORT" 2>/dev/null
sleep 0.5
nohup uv run uvicorn valte.main:app --host 0.0.0.0 --port "$PORT" > "$LOG" 2>&1 &
for _ in $(seq 1 40); do curl -s -m 1 "localhost:$PORT/health" > /dev/null 2>&1 && { echo "up on :$PORT (log: $LOG)"; exit 0; }; sleep 0.5; done
echo "did not start; see $LOG"; tail -20 "$LOG"; exit 1
