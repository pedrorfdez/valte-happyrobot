#!/usr/bin/env bash
# Public URL for HappyRobot callbacks, with nothing to install: ssh reverse tunnel via localhost.run.
# Writes the URL to backend/.public_url, which the backend re-reads on every dispatch.
# NOTE: run this script on its own command line (its pkill matches any shell whose command mentions the tunnel host).
cd "$(dirname "$0")/.." || exit 1
PORT="${1:-8010}"
LOG="${VALTE_TUNNEL_LOG:-/tmp/valte-tunnel.log}"
pkill -f "[n]okey@localhost.run" 2>/dev/null
sleep 1
: > "$LOG"
# localhost.run only announces the URL to a terminal, so give ssh a pseudo-tty with script(1).
SSH="ssh -tt -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -o ConnectTimeout=8 -o ConnectionAttempts=3 -R 80:localhost:$PORT nokey@localhost.run"
nohup script -qfc "$SSH" "$LOG" > /dev/null 2>&1 < /dev/null &
for _ in $(seq 1 120); do
  HOST=$(grep -aoE '[a-z0-9-]+\.lhr\.life' "$LOG" | tail -1)
  [ -n "$HOST" ] && { echo "https://$HOST" > .public_url; echo "tunnel: https://$HOST -> localhost:$PORT"; exit 0; }
  sleep 0.5
done
echo "no tunnel URL yet; see $LOG"; tail -c 600 "$LOG"; exit 1
