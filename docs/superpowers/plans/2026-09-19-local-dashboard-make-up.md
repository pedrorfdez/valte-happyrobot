# Local Dashboard `make up` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a foreground `make up` command that validates the deployed Gateway, serves the local dashboard, opens the correctly configured URL, and shuts down cleanly with `Ctrl-C`.

**Architecture:** A small root `Makefile` provides the public commands and delegates lifecycle behavior to one Bash launcher. A Bash integration test starts a temporary mock Gateway and verifies failure, health-check, serving, URL construction, and shutdown without touching the real `.env` or remote services.

**Tech Stack:** GNU/BSD Make, Bash 3.2+, Python 3 standard library, curl

---

## File map

- Create `Makefile`: stable `up`, `check`, `test-dashboard`, and `help` entry points.
- Create `scripts/dashboard-local.sh`: environment loading, validation, remote Gateway preflight, URL construction, server lifecycle, and optional browser opening.
- Create `scripts/test-dashboard-local.sh`: isolated end-to-end checks using a temporary mock Gateway and dashboard port.
- Modify `README.md`: make `make up` the recommended dashboard startup path and remove local Azure Functions from that path.

### Task 1: Build the launcher test-first

**Files:**
- Create: `scripts/test-dashboard-local.sh`
- Create: `scripts/dashboard-local.sh`

- [ ] **Step 1: Write the failing integration test**

Create `scripts/test-dashboard-local.sh` with:

```bash
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
        if parsed.path != "/api/snapshot" or not run_id:
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
printf 'GATEWAY_URL=http://127.0.0.1:%s\nDANA_RUN_ID=run-dana-demo\n' \
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
grep -q 'gateway_url=http%3A%2F%2F127.0.0.1' "$valte_tmp/up.log" || fail "Gateway URL is not encoded"

kill -TERM "$valte_up_pid"
wait "$valte_up_pid" || true
valte_up_pid=""

if curl -fsS --max-time 1 "http://127.0.0.1:$valte_dashboard_port/" >/dev/null 2>&1; then
  fail "dashboard port remained open after shutdown"
fi

echo "PASS dashboard launcher"
```

- [ ] **Step 2: Make the test executable and prove it fails**

Run:

```bash
chmod +x scripts/test-dashboard-local.sh
./scripts/test-dashboard-local.sh
```

Expected: non-zero exit because `scripts/dashboard-local.sh` does not exist.

- [ ] **Step 3: Implement the minimal launcher**

Create `scripts/dashboard-local.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

valte_action="${1:-up}"
valte_root="$(cd "$(dirname "$0")/.." && pwd)"
valte_env_file="${VALTE_ENV_FILE:-$valte_root/.env}"
valte_requested_run="${RUN_ID:-}"
valte_requested_port="${PORT:-}"
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
  *) die "Uso: scripts/dashboard-local.sh up|check" ;;
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

[[ -n "${GATEWAY_URL:-}" ]] || die "GATEWAY_URL no está definido en $valte_env_file."
[[ -n "$valte_run_id" ]] || die "Define DANA_RUN_ID en $valte_env_file o usa make up RUN_ID=<run-id>."
case "$GATEWAY_URL" in
  *'<'*|*'>'*|*your_gateway*|*your-gateway*) die "GATEWAY_URL todavía contiene un valor de plantilla." ;;
esac
case "$valte_run_id" in
  *'<'*|*'>'*|*your_run*|*your-run*) die "El run ID todavía contiene un valor de plantilla." ;;
esac
[[ "$valte_port" =~ ^[0-9]+$ ]] || die "PORT debe ser un entero entre 1 y 65535."
(( valte_port >= 1 && valte_port <= 65535 )) || die "PORT debe ser un entero entre 1 y 65535."

valte_gateway_origin="$(python3 - "$GATEWAY_URL" <<'PY'
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
    or parsed.path not in {"", "/"}
    or parsed.query
    or parsed.fragment
):
    raise SystemExit(1)
print(urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))
PY
)" || die "GATEWAY_URL debe ser un origen HTTP(S) sin ruta, query ni credenciales."

valte_run_query="$(python3 - "$valte_run_id" <<'PY'
import sys
from urllib.parse import urlencode
print(urlencode({"run_id": sys.argv[1]}))
PY
)"
valte_snapshot_url="$valte_gateway_origin/api/snapshot?$valte_run_query"

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

valte_dashboard_url="$(python3 - "$valte_port" "$valte_run_id" "$valte_gateway_origin" <<'PY'
import sys
from urllib.parse import urlencode
port, run_id, gateway = sys.argv[1:]
print(f"http://localhost:{port}/?{urlencode({'run_id': run_id, 'gateway_url': gateway})}")
PY
)"

echo "✓ Gateway disponible para $valte_run_id"
echo "Dashboard: $valte_dashboard_url"

[[ "$valte_action" == "up" ]] || exit 0

if ! python3 - "$valte_port" <<'PY' >/dev/null 2>&1
import socket
import sys
with socket.socket() as sock:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
PY
then
  die "El puerto $valte_port está ocupado. Detén el proceso existente o usa make up PORT=<otro-puerto>."
fi

python3 -m http.server "$valte_port" --bind 127.0.0.1 --directory "$valte_root/app" &
valte_server_pid=$!

valte_ready=0
for _valte_attempt in $(seq 1 50); do
  if curl -fsS --max-time 1 "http://127.0.0.1:$valte_port/" >/dev/null 2>&1; then
    valte_ready=1
    break
  fi
  sleep 0.1
done
[[ "$valte_ready" == "1" ]] || die "El servidor del dashboard no llegó a estar disponible."

echo "✓ Dashboard activo. Pulsa Ctrl-C para detenerlo."
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
```

- [ ] **Step 4: Make the launcher executable and run the integration test**

Run:

```bash
chmod +x scripts/dashboard-local.sh
bash -n scripts/dashboard-local.sh scripts/test-dashboard-local.sh
./scripts/test-dashboard-local.sh
```

Expected:

```text
PASS dashboard launcher
```

- [ ] **Step 5: Commit the launcher and test**

```bash
git add scripts/dashboard-local.sh scripts/test-dashboard-local.sh
git commit -m "feat: add local dashboard launcher"
```

### Task 2: Add the Make interface

**Files:**
- Create: `Makefile`
- Test: `scripts/test-dashboard-local.sh`

- [ ] **Step 1: Demonstrate the public target is absent**

Run:

```bash
make help
```

Expected: non-zero exit because no `Makefile` exists.

- [ ] **Step 2: Add the Makefile**

Create `Makefile` with literal tab indentation for recipe lines:

```make
SHELL := /bin/bash
.DEFAULT_GOAL := help

PORT ?= 4173
RUN_ID ?=
export PORT
export RUN_ID

.PHONY: up check test-dashboard help

up: ## Comprueba el Gateway y levanta el dashboard en primer plano
	@./scripts/dashboard-local.sh up

check: ## Comprueba configuración y conectividad sin levantar el dashboard
	@./scripts/dashboard-local.sh check

test-dashboard: ## Ejecuta las pruebas aisladas del launcher
	@./scripts/test-dashboard-local.sh

help: ## Muestra los comandos disponibles
	@printf '%s\n' \
	  'Valte Crisis Orchestrator' \
	  '' \
	  '  make up                         Levanta el dashboard DANA' \
	  '  make up RUN_ID=run-wildfire-demo  Levanta otro run' \
	  '  make up PORT=4174               Usa otro puerto' \
	  '  make check                      Comprueba .env y Gateway' \
	  '  make test-dashboard             Ejecuta las pruebas del launcher' \
	  '' \
	  'Ctrl-C detiene el dashboard.'
```

- [ ] **Step 3: Verify Make delegates correctly**

Run:

```bash
make help
make test-dashboard
```

Expected: help lists all four targets and the test prints `PASS dashboard launcher`.

- [ ] **Step 4: Commit the Make interface**

```bash
git add Makefile
git commit -m "feat: add dashboard make targets"
```

### Task 3: Update the launch documentation and run the real smoke

**Files:**
- Modify: `README.md:51-225`

- [ ] **Step 1: Update the prerequisite and Gateway sections**

In `README.md`, remove `func --version` from the prerequisite commands and replace the local Gateway prerequisite with a deployed Gateway URL. Change the environment example to:

```dotenv
GATEWAY_URL=https://your-deployed-gateway.example
```

Replace the local Azure Functions startup section with:

```markdown
### Step 4 — Verify the deployed Gateway

The dashboard and HappyRobot workflows use the deployed Gateway configured in `.env`; no local Azure Functions process is required.

```bash
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=$DANA_RUN_ID" \
  | jq -e '.run.run_id == "run-dana-demo"'
```

Continue when `jq` prints `true`.
```

- [ ] **Step 2: Make `make up` the recommended dashboard command**

Replace the local dashboard startup commands with:

```markdown
### Step 7 — Start the dashboard

From the repository root:

```bash
make up
```

The command loads `.env`, verifies the selected run through the deployed Gateway, starts the dashboard on port `4173`, and opens the correctly configured URL. It stays attached to the terminal; press `Ctrl-C` to stop it.

To show the wildfire run or select another port:

```bash
make up RUN_ID="$WILDFIRE_RUN_ID"
make up PORT=4174
```
```

- [ ] **Step 3: Run static verification**

Run:

```bash
git diff --check -- Makefile scripts/dashboard-local.sh scripts/test-dashboard-local.sh README.md
bash -n scripts/dashboard-local.sh scripts/test-dashboard-local.sh
make test-dashboard
rg -n 'make up|deployed Gateway|no local Azure Functions' README.md
```

Expected: no whitespace or shell syntax errors, launcher test passes, and README contains the new launch path.

- [ ] **Step 4: Stop the manually started dashboard and run the configured preflight**

Stop the existing Python dashboard process on port `4173` only after identifying that exact listener. Then run:

```bash
make check
```

Expected: either a successful remote Gateway check, or an actionable failure naming the `.env` value that must be corrected. Do not substitute a local Azure Functions URL.

- [ ] **Step 5: Run the real foreground smoke**

Run `make up` in a managed terminal session, wait for `HTTP 200` from `http://127.0.0.1:4173/`, verify the printed URL uses the configured Gateway rather than an implicit `localhost:7071`, send `Ctrl-C`, and confirm the port is released.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md
git commit -m "docs: launch dashboard with make"
```

### Task 4: Final verification

**Files:**
- Verify only; no new files.

- [ ] **Step 1: Run the focused checks**

```bash
make help
make test-dashboard
make check
npm run contracts:check
git diff --check
```

Expected: all local tests and contract checks pass; `make check` confirms the deployed Gateway.

- [ ] **Step 2: Confirm scope and user work preservation**

Run:

```bash
git status --short
git log -5 --oneline
```

Expected: the implementation commits contain only the new dashboard launcher, its test, the root `Makefile`, and the targeted README changes. Pre-existing modifications in `api/event-router/index.mjs`, `docs/demo-runbook.md`, `happyrobot/crisis-command/commander.prompt.md`, `scripts/e2e-demo.mjs`, `scripts/check-workflows.sh`, and `scripts/reseed-runs.sh` remain uncommitted and unchanged by this plan.
