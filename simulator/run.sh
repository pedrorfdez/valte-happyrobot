#!/usr/bin/env bash
# Valte · Mundo exterior. Uses the backend's virtualenv (fastapi + httpx are already there).
#   simulator/run.sh [port]     VALTE_BACKEND=http://localhost:8010 by default
cd "$(dirname "$0")" || exit 1
PORT="${1:-8030}"
LOG="${VALTE_SIM_LOG:-/tmp/valte-mundo-$PORT.log}"
pkill -f "[u]vicorn app:app .*--port $PORT" 2>/dev/null
for _ in 1 2 3 4 5 6; do pgrep -f "[u]vicorn app:app .*--port $PORT" > /dev/null || break; sleep 0.5; done
pkill -9 -f "[u]vicorn app:app .*--port $PORT" 2>/dev/null  # never two feeders on one port
sleep 0.5
nohup uv run --project ../backend uvicorn app:app --host 127.0.0.1 --port "$PORT" > "$LOG" 2>&1 &
for _ in $(seq 1 40); do curl -s -m 1 "localhost:$PORT/api/status" > /dev/null 2>&1 && { echo "mundo exterior en http://localhost:$PORT (log: $LOG)"; exit 0; }; sleep 0.5; done
echo "no arrancó; mira $LOG"; tail -20 "$LOG"; exit 1
