#!/usr/bin/env bash
set -euo pipefail

valte_root="$(cd "$(dirname "$0")/.." && pwd)"
valte_launcher="$valte_root/scripts/dashboard-local.sh"
valte_tmp="$(mktemp -d "${TMPDIR:-/tmp}/valte-dashboard-test.XXXXXX")"
valte_mock_pid=""
valte_up_pid=""

cleanup() {
  if [[ -n "$valte_up_pid" ]] && kill -0 "$valte_up_pid" 2>/dev/null; then
    kill -TERM "$valte_up_pid" 2>/dev/null || true
    wait "$valte_up_pid" 2>/dev/null || true
  fi
  if [[ -n "$valte_mock_pid" ]] && kill -0 "$valte_mock_pid" 2>/dev/null; then
    kill -TERM "$valte_mock_pid" 2>/dev/null || true
    wait "$valte_mock_pid" 2>/dev/null || true
  fi
  rm -rf "$valte_tmp"
}
trap cleanup EXIT INT TERM

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

wait_for_file() {
  local file="$1"
  local attempt
  for attempt in $(seq 1 50); do
    [[ -s "$file" ]] && return 0
    sleep 0.1
  done
  return 1
}

wait_for_http() {
  local url="$1"
  local attempt
  for attempt in $(seq 1 50); do
    curl -fsS --max-time 1 "$url" >/dev/null 2>&1 && return 0
    sleep 0.1
  done
  return 1
}

valte_port_file="$valte_tmp/mock-port"
python3 - "$valte_port_file" <<'PY' &
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

port_file = sys.argv[1]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlsplit(self.path)
        run_id = parse_qs(parsed.query).get("run_id", [""])[0]
        if parsed.path != "/functions/v1/gateway/api/snapshot" or not run_id:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps({"run": {"run_id": run_id}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
with open(port_file, "w", encoding="utf-8") as handle:
    handle.write(str(server.server_port))
server.serve_forever()
PY
valte_mock_pid=$!

wait_for_file "$valte_port_file" || fail "mock Gateway did not start"
valte_mock_port="$(cat "$valte_port_file")"
valte_env="$valte_tmp/.env"
printf 'SUPABASE_URL=http://127.0.0.1:%s\nGATEWAY_URL=http://localhost:7071\nDANA_RUN_ID=run-dana-demo\n' \
  "$valte_mock_port" > "$valte_env"

if VALTE_ENV_FILE="$valte_tmp/missing.env" "$valte_launcher" check >"$valte_tmp/missing.log" 2>&1; then
  fail "missing env file should fail"
fi
grep -q 'No existe el archivo de entorno' "$valte_tmp/missing.log" || fail "missing env error is not actionable"

if VALTE_ENV_FILE="$valte_env" PORT=invalid "$valte_launcher" check >"$valte_tmp/port.log" 2>&1; then
  fail "invalid port should fail"
fi
grep -q 'PORT debe ser un entero' "$valte_tmp/port.log" || fail "invalid port error is not actionable"

VALTE_ENV_FILE="$valte_env" "$valte_launcher" check >"$valte_tmp/check.log"
grep -q 'Gateway disponible para run-dana-demo' "$valte_tmp/check.log" || fail "Gateway check did not pass"

valte_dashboard_port="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"

VALTE_ENV_FILE="$valte_env" \
VALTE_OPEN_BROWSER=0 \
PORT="$valte_dashboard_port" \
RUN_ID=run-wildfire-demo \
  "$valte_launcher" up >"$valte_tmp/up.log" 2>&1 &
valte_up_pid=$!

wait_for_http "http://127.0.0.1:$valte_dashboard_port/" || fail "dashboard did not start"
curl -fsS "http://127.0.0.1:$valte_dashboard_port/" | \
  grep -q 'Centro de coordinación de crisis' || fail "dashboard content is missing"
grep -q 'run_id=run-wildfire-demo' "$valte_tmp/up.log" || fail "selected run is absent from URL"
grep -q 'gateway_url=http%3A%2F%2F127.0.0.1.*%2Ffunctions%2Fv1%2Fgateway' "$valte_tmp/up.log" || fail "Edge Gateway path is absent from URL"

kill -TERM "$valte_up_pid"
wait "$valte_up_pid" || true
valte_up_pid=""

if curl -fsS --max-time 1 "http://127.0.0.1:$valte_dashboard_port/" >/dev/null 2>&1; then
  fail "dashboard port remained open after shutdown"
fi

VALTE_ENV_FILE="$valte_env" \
VALTE_OPEN_BROWSER=0 \
PORT="$valte_dashboard_port" \
  "$valte_launcher" up >"$valte_tmp/restart.log" 2>&1 &
valte_up_pid=$!

wait_for_http "http://127.0.0.1:$valte_dashboard_port/" || fail "dashboard could not restart on its released port"
kill -TERM "$valte_up_pid"
wait "$valte_up_pid" || true
valte_up_pid=""

echo "PASS dashboard launcher"
