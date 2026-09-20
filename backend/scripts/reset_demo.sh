#!/usr/bin/env bash
# Wipe previous catastrophes and restart kernel + mundo exterior so the demo can be run again.
# Keeps HappyRobot workflow ids and global lessons (the «Aprendido» block on the next flood).
# Stop first: a crisis mid-tick would be rewritten after we delete it.
#
#   scripts/reset_demo.sh [backend_port] [sim_port]
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
ROOT="$(cd .. && pwd)"
BPORT="${1:-8010}"
SPORT="${2:-8030}"

echo "stopping kernel :$BPORT and mundo :$SPORT"
pkill -f "[u]vicorn valte.main:app .*--port $BPORT" 2>/dev/null || true
pkill -f "[u]vicorn app:app .*--port $SPORT" 2>/dev/null || true
for _ in 1 2 3 4 5 6; do
  pgrep -f "[u]vicorn valte.main:app .*--port $BPORT" >/dev/null || pgrep -f "[u]vicorn app:app .*--port $SPORT" >/dev/null || break
  sleep 0.5
done
pkill -9 -f "[u]vicorn valte.main:app .*--port $BPORT" 2>/dev/null || true
pkill -9 -f "[u]vicorn app:app .*--port $SPORT" 2>/dev/null || true
sleep 0.3

echo "deleting catastrophes"
uv run python scripts/delete_crisis.py --all

echo "starting again"
scripts/dev_server.sh "$BPORT"
"$ROOT/simulator/run.sh" "$SPORT"
echo "lista: dashboard http://localhost:$BPORT/app/  ·  mundo http://localhost:$SPORT"
