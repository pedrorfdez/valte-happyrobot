#!/usr/bin/env bash
set -euo pipefail

valte_action="${1:-up}"
valte_root="$(cd "$(dirname "$0")/.." && pwd)"
valte_env_file="${VALTE_ENV_FILE:-$valte_root/.env}"
valte_requested_run="${RUN_ID:-}"
valte_requested_port="${PORT:-}"
valte_requested_gateway="${GATEWAY_URL:-}"
valte_requested_supabase="${SUPABASE_URL:-}"
valte_server_pid=""

die() {
  echo "✗ $*" >&2
  exit 1
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$valte_server_pid" ]] && kill -0 "$valte_server_pid" 2>/dev/null; then
    kill -TERM "$valte_server_pid" 2>/dev/null || true
    wait "$valte_server_pid" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

case "$valte_action" in
  up|check) ;;
  *) die "Uso: scripts/dashboard-v2.sh up|check" ;;
esac

[[ -f "$valte_env_file" ]] || die "No existe el archivo de entorno $valte_env_file. Copia .env.example a .env y configúralo."
command -v python3 >/dev/null 2>&1 || die "python3 es obligatorio. Instálalo y vuelve a ejecutar el comando."
command -v curl >/dev/null 2>&1 || die "curl es obligatorio. Instálalo y vuelve a ejecutar el comando."

set -a
# shellcheck disable=SC1090
source "$valte_env_file"
set +a

valte_run_id="${valte_requested_run:-${DANA_RUN_ID:-}}"
valte_port="${valte_requested_port:-4173}"
valte_gateway_url="${valte_requested_gateway:-${GATEWAY_URL:-}}"
valte_supabase_url="${valte_requested_supabase:-${SUPABASE_URL:-}}"

case "$valte_gateway_url" in
  ""|http://localhost:7071|http://localhost:7071/|http://127.0.0.1:7071|http://127.0.0.1:7071/)
    if [[ -n "$valte_supabase_url" ]]; then
      valte_gateway_url="${valte_supabase_url%/}/functions/v1/gateway"
    fi
    ;;
esac

[[ -n "$valte_gateway_url" ]] || die "Define GATEWAY_URL o SUPABASE_URL en $valte_env_file."
[[ -n "$valte_run_id" ]] || die "Define DANA_RUN_ID en $valte_env_file o usa make up RUN_ID=<run-id>."
case "$valte_gateway_url" in
  *'<'*|*'>'*|*your_gateway*|*your-gateway*|*your-project-ref*|*.example*) die "GATEWAY_URL todavía contiene un valor de plantilla." ;;
esac
case "$valte_run_id" in
  *'<'*|*'>'*|*your_run*|*your-run*) die "El run ID todavía contiene un valor de plantilla." ;;
esac
[[ "$valte_port" =~ ^[0-9]+$ ]] || die "PORT debe ser un entero entre 1 y 65535."
(( valte_port >= 1 && valte_port <= 65535 )) || die "PORT debe ser un entero entre 1 y 65535."

valte_gateway_base="$(python3 - "$valte_gateway_url" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

raw = sys.argv[1]
try:
    parsed = urlsplit(raw)
    _ = parsed.port
except ValueError:
    raise SystemExit(1)
if (
    parsed.scheme not in {"http", "https"}
    or not parsed.hostname
    or parsed.username
    or parsed.password
    or parsed.query
    or parsed.fragment
):
    raise SystemExit(1)
path = parsed.path.rstrip("/")
print(urlunsplit((parsed.scheme, parsed.netloc, path, "", "")))
PY
)" || die "GATEWAY_URL debe ser una URL base HTTP(S) sin query ni credenciales."

valte_run_query="$(python3 - "$valte_run_id" <<'PY'
import sys
from urllib.parse import urlencode

print(urlencode({"run_id": sys.argv[1]}))
PY
)"
valte_snapshot_url="$valte_gateway_base/api/snapshot?$valte_run_query"

if ! valte_snapshot="$(curl -fsS --connect-timeout 3 --max-time 10 "$valte_snapshot_url")"; then
  die "El Gateway no responde para $valte_run_id. Revisa GATEWAY_URL, el run y tu conexión."
fi
if ! printf '%s' "$valte_snapshot" | python3 -c '
import json, sys
expected = sys.argv[1]
payload = json.load(sys.stdin)
raise SystemExit(0 if payload.get("run", {}).get("run_id") == expected else 1)
' "$valte_run_id"; then
  die "El Gateway respondió, pero el snapshot no corresponde a $valte_run_id."
fi

valte_dashboard_url="$(python3 - "$valte_port" "$valte_run_id" "$valte_gateway_base" <<'PY'
import sys
from urllib.parse import urlencode

port, run_id, gateway = sys.argv[1:]
print(f"http://localhost:{port}/?{urlencode({'run_id': run_id, 'gateway_url': gateway})}")
PY
)"

echo "✓ Gateway disponible para $valte_run_id"
echo "Dashboard v2: $valte_dashboard_url"

[[ "$valte_action" == "up" ]] || exit 0

if ! python3 - "$valte_port" <<'PY' >/dev/null 2>&1
import socket
import sys

with socket.socket() as sock:
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", int(sys.argv[1])))
PY
then
  die "El puerto $valte_port está ocupado. Detén el proceso existente o usa make up PORT=<otro-puerto>."
fi

# Ensure v2 build exists; build on demand if missing
if [[ ! -f "$valte_root/app-v2/dist/index.html" ]]; then
  echo "· app-v2/dist no encontrado, construyendo..."
  if [[ -f "$valte_root/app-v2/package.json" ]]; then
    npm --prefix "$valte_root/app-v2" run build >/dev/null 2>&1 || die "Fallo al construir app-v2 (npm --prefix app-v2 run build)"
  else
    die "app-v2/dist/index.html no existe y app-v2/package.json no encontrado."
  fi
fi

python3 -m http.server "$valte_port" --bind 127.0.0.1 --directory "$valte_root/app-v2/dist" &
valte_server_pid=$!

valte_ready=0
for _valte_attempt in $(seq 1 50); do
  if curl -fsS --max-time 1 "http://127.0.0.1:$valte_port/" >/dev/null 2>&1; then
    valte_ready=1
    break
  fi
  sleep 0.1
done
[[ "$valte_ready" == "1" ]] || die "El servidor del dashboard v2 no llegó a estar disponible."

echo "✓ Dashboard v2 activo en http://127.0.0.1:$valte_port/ . Pulsa Ctrl-C para detenerlo."
if [[ "${VALTE_OPEN_BROWSER:-1}" != "0" ]]; then
  if command -v open >/dev/null 2>&1; then
    open "$valte_dashboard_url" >/dev/null 2>&1 || echo "Aviso: abre manualmente $valte_dashboard_url"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$valte_dashboard_url" >/dev/null 2>&1 || echo "Aviso: abre manualmente $valte_dashboard_url"
  else
    echo "Aviso: abre manualmente $valte_dashboard_url"
  fi
fi

wait "$valte_server_pid"
