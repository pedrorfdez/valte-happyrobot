#!/usr/bin/env bash
# Keeps the public tunnel alive: anonymous tunnels expire every so often, so check it and reopen it when it dies.
#   nohup backend/scripts/tunnel_watch.sh 8010 > /tmp/valte-tunnel-watch.log 2>&1 &
# Nothing needs re-provisioning in HappyRobot: every dispatch carries the current callback_base.
cd "$(dirname "$0")/.." || exit 1
PORT="${1:-8010}"
while true; do
  URL=$(cat .public_url 2>/dev/null)
  CODE=$(curl -s -m 12 -o /dev/null -w '%{http_code}' "$URL/health" 2>/dev/null)
  if [ "$CODE" != "200" ]; then
    echo "$(date '+%H:%M:%S') tunnel down ($CODE): reopening"
    scripts/tunnel.sh "$PORT"
  fi
  sleep 30
done
