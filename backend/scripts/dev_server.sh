#!/usr/bin/env bash
# Restart the backend for local work. Usage: scripts/dev_server.sh [port] (env vars pass through)
cd "$(dirname "$0")/.." || exit 1
PORT="${1:-8010}"
LOG="${VALTE_LOG:-/tmp/valte-$PORT.log}"
pkill -f "[u]vicorn valte.main:app .*--port $PORT" 2>/dev/null
sleep 1
nohup uv run uvicorn valte.main:app --host 0.0.0.0 --port "$PORT" > "$LOG" 2>&1 &
for _ in $(seq 1 40); do curl -s -m 1 "localhost:$PORT/health" > /dev/null 2>&1 && { echo "up on :$PORT (log: $LOG)"; exit 0; }; sleep 0.5; done
echo "did not start; see $LOG"; tail -20 "$LOG"; exit 1
