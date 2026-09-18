# Kuehne+Nagel Milestone Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one safe, executable HappyRobot REST example that submits carrier milestone follow-ups in simulation or live mode without moving workflow decisions into the caller script.

**Architecture:** A Bash script acts as the upstream TMS adapter, validates operational facts, and triggers `POST /workflows/{workflow_id}/runs`. Simulation data is isolated in a `simulation` payload object; live mode supplies only a server-side carrier contact reference. A standalone Bash test harness exercises payload shape and validation entirely in dry-run mode.

**Tech Stack:** Bash, `curl`, `jq`, HappyRobot Public API v2

---

## File map

- Create `examples/08-kuehne-nagel-milestone-follow-up.sh`: validate inputs, build the REST payload, print it in dry-run mode, and optionally trigger the workflow.
- Create `tests/examples/kuehne-nagel-milestone-follow-up.test.sh`: dependency-free shell test harness for valid and invalid scenarios.
- Modify `examples/README.md`: document simulation, live preview, workflow responsibilities, and public sources.

### Task 1: Build the happy-path payload with tests

**Files:**

- Create: `tests/examples/kuehne-nagel-milestone-follow-up.test.sh`
- Create: `examples/08-kuehne-nagel-milestone-follow-up.sh`

- [ ] **Step 1: Create the initial failing test harness**

Create `tests/examples/kuehne-nagel-milestone-follow-up.test.sh` with:

```bash
#!/usr/bin/env bash

set -u

TEST_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$TEST_DIR/../.." && pwd)"
SCRIPT="$PROJECT_ROOT/examples/08-kuehne-nagel-milestone-follow-up.sh"
failures=0
passes=0
RUN_OUTPUT=''

pass() {
  passes=$((passes + 1))
  printf 'PASS %s\n' "$1"
}

fail() {
  failures=$((failures + 1))
  printf 'FAIL %s\n' "$1" >&2
}

run_success() {
  local name="$1"
  shift

  if RUN_OUTPUT="$(env HAPPYROBOT_KEY=test-key "$@" "$SCRIPT" test-workflow 2>/dev/null)"; then
    return 0
  fi

  fail "$name: command exited non-zero"
  return 1
}

assert_json_eq() {
  local name="$1"
  local json="$2"
  local filter="$3"
  local expected="$4"
  local actual

  actual="$(jq -r "$filter" <<<"$json")"
  if [[ "$actual" == "$expected" ]]; then
    pass "$name"
  else
    fail "$name: expected '$expected', got '$actual'"
  fi
}

test_simulated_confirmed_payload() {
  if ! run_success 'simulated confirmed payload' \
    RUN_MODE=simulate \
    DRY_RUN=true \
    EVENT_ID=event-sim-001 \
    SHIPMENT_ID=KN-HC-001 \
    CARRIER_NAME='Demo Air Carrier' \
    MILESTONE=airport_arrival \
    EXPECTED_AT=2026-09-19T10:00:00Z \
    SIMULATED_CARRIER_STATUS=confirmed \
    SIMULATED_REPORTED_ETA=2026-09-19T09:55:00Z \
    SIMULATED_TEMPERATURE_C=5.2; then
    return
  fi

  assert_json_eq 'simulation event type' "$RUN_OUTPUT" \
    '.payload.event_type' 'carrier_milestone_follow_up_requested'
  assert_json_eq 'simulation status' "$RUN_OUTPUT" \
    '.payload.simulation.carrier_status' 'confirmed'
  assert_json_eq 'simulation temperature' "$RUN_OUTPUT" \
    '.payload.simulation.temperature_c' '5.2'
  assert_json_eq 'script does not decide severity' "$RUN_OUTPUT" \
    '.payload | has("severity")' 'false'
  assert_json_eq 'simulation omits contact id' "$RUN_OUTPUT" \
    '.payload.carrier | has("contact_id")' 'false'
}

test_live_payload() {
  if ! run_success 'live payload' \
    RUN_MODE=live \
    DRY_RUN=true \
    EVENT_ID=event-live-001 \
    SHIPMENT_ID=KN-HC-002 \
    CARRIER_NAME='Demo Air Carrier' \
    CARRIER_CONTACT_ID=contact-123 \
    MILESTONE=pickup_confirmation \
    EXPECTED_AT=2026-09-19T12:00:00Z; then
    return
  fi

  assert_json_eq 'live contact reference' "$RUN_OUTPUT" \
    '.payload.carrier.contact_id' 'contact-123'
  assert_json_eq 'live payload omits simulation' "$RUN_OUTPUT" \
    '.payload | has("simulation")' 'false'
  assert_json_eq 'live event id' "$RUN_OUTPUT" \
    '.payload.event_id' 'event-live-001'
}

test_simulated_confirmed_payload
test_live_payload

printf '%s passes, %s failures\n' "$passes" "$failures"
[[ "$failures" -eq 0 ]]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
bash tests/examples/kuehne-nagel-milestone-follow-up.test.sh
```

Expected: exit code `1`, with both scenarios reporting `command exited non-zero` because the example script does not exist.

- [ ] **Step 3: Implement the minimal payload builder**

Create `examples/08-kuehne-nagel-milestone-follow-up.sh` with:

```bash
#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=_lib/happyrobot.sh
source "$(cd "$(dirname "$0")" && pwd)/_lib/happyrobot.sh"

workflow_id="$(workflow_id_from_arg_or_env "${1:-}")"
run_mode="${RUN_MODE:-simulate}"
shipment_id="${SHIPMENT_ID:-KN-HC-DEMO-001}"
carrier_name="${CARRIER_NAME:-Demo Air Carrier}"
carrier_contact_id="${CARRIER_CONTACT_ID:-}"
milestone="${MILESTONE:-airport_arrival}"
expected_at="${EXPECTED_AT:-2026-09-19T10:00:00Z}"
temperature_min_c="${TEMPERATURE_MIN_C:-2}"
temperature_max_c="${TEMPERATURE_MAX_C:-8}"
contact_attempt="${CONTACT_ATTEMPT:-1}"
max_contact_attempts="${MAX_CONTACT_ATTEMPTS:-3}"
retry_delay_minutes="${RETRY_DELAY_MINUTES:-15}"
language="${LANGUAGE:-en}"
dry_run="${DRY_RUN:-true}"
observed_at="${OBSERVED_AT:-$(date -u '+%Y-%m-%dT%H:%M:%SZ')}"
event_id="${EVENT_ID:-demo-$shipment_id-$milestone}"

simulated_status="${SIMULATED_CARRIER_STATUS:-confirmed}"
if [[ "$simulated_status" == 'no_answer' ]]; then
  simulated_reported_eta="${SIMULATED_REPORTED_ETA:-}"
  simulated_temperature_c="${SIMULATED_TEMPERATURE_C:-}"
else
  simulated_reported_eta="${SIMULATED_REPORTED_ETA:-$expected_at}"
  simulated_temperature_c="${SIMULATED_TEMPERATURE_C:-5}"
fi

body="$(jq -n \
  --arg environment "$HAPPYROBOT_ENV" \
  --arg event_id "$event_id" \
  --arg shipment_id "$shipment_id" \
  --arg carrier_name "$carrier_name" \
  --arg carrier_contact_id "$carrier_contact_id" \
  --arg milestone "$milestone" \
  --arg expected_at "$expected_at" \
  --arg temperature_min_c "$temperature_min_c" \
  --arg temperature_max_c "$temperature_max_c" \
  --arg contact_attempt "$contact_attempt" \
  --arg max_contact_attempts "$max_contact_attempts" \
  --arg retry_delay_minutes "$retry_delay_minutes" \
  --arg language "$language" \
  --arg run_mode "$run_mode" \
  --arg simulated_status "$simulated_status" \
  --arg simulated_reported_eta "$simulated_reported_eta" \
  --arg simulated_temperature_c "$simulated_temperature_c" \
  --arg observed_at "$observed_at" \
  '{
    environment: $environment,
    payload: {
      event_type: "carrier_milestone_follow_up_requested",
      event_id: $event_id,
      shipment: {
        id: $shipment_id,
        milestone: {
          name: $milestone,
          expected_at: $expected_at
        }
      },
      carrier: {
        name: $carrier_name,
        contact_id: $carrier_contact_id,
        preferred_language: $language
      },
      policy: {
        temperature_range_c: {
          min: ($temperature_min_c | tonumber),
          max: ($temperature_max_c | tonumber)
        },
        contact: {
          attempt: ($contact_attempt | tonumber),
          max_attempts: ($max_contact_attempts | tonumber),
          retry_delay_minutes: ($retry_delay_minutes | tonumber)
        }
      },
      mode: $run_mode,
      source: "kuehne-nagel-hypercare-example",
      observed_at: $observed_at
    }
  }
  | if $run_mode == "simulate" then
      .payload.simulation = {carrier_status: $simulated_status}
    else
      .
    end
  | if $run_mode == "simulate" and $simulated_reported_eta != "" then
      .payload.simulation.reported_eta = $simulated_reported_eta
    else . end
  | if $run_mode == "simulate" and $simulated_temperature_c != "" then
      .payload.simulation.temperature_c = ($simulated_temperature_c | tonumber)
    else . end
  | if $run_mode == "simulate" then
      del(.payload.carrier.contact_id)
    else . end')"

if [[ "$dry_run" == 'true' ]]; then
  printf '%s\n' 'Vista previa (DRY_RUN=true): no se ha iniciado ningún workflow.' >&2
  printf '%s\n' "$body" | jq .
  exit 0
fi

printf 'Iniciando seguimiento del hito %s para el envío %s...\n' \
  "$milestone" "$shipment_id" >&2
api_request POST "/workflows/$workflow_id/runs" \
  --header 'Content-Type: application/json' \
  --data "$body" \
  | jq .
```

- [ ] **Step 4: Make the files executable**

Run:

```bash
chmod +x examples/08-kuehne-nagel-milestone-follow-up.sh
chmod +x tests/examples/kuehne-nagel-milestone-follow-up.test.sh
```

Expected: both files have executable mode `755`.

- [ ] **Step 5: Run the happy-path tests**

Run:

```bash
bash tests/examples/kuehne-nagel-milestone-follow-up.test.sh
```

Expected: exit code `0` and `8 passes, 0 failures`.

- [ ] **Step 6: Commit the happy-path implementation**

```bash
git add examples/08-kuehne-nagel-milestone-follow-up.sh tests/examples/kuehne-nagel-milestone-follow-up.test.sh
git commit -m "Add Kuehne Nagel milestone payload example"
```

### Task 2: Add input validation and negative tests

**Files:**

- Modify: `tests/examples/kuehne-nagel-milestone-follow-up.test.sh`
- Modify: `examples/08-kuehne-nagel-milestone-follow-up.sh`

- [ ] **Step 1: Add the failure assertion helper and invalid-input tests**

Insert this helper after `run_success` in the test file:

```bash
assert_command_fails() {
  local name="$1"
  local expected_message="$2"
  shift 2
  local output

  if output="$(env HAPPYROBOT_KEY=test-key "$@" "$SCRIPT" test-workflow 2>&1)"; then
    fail "$name: command unexpectedly succeeded"
  elif [[ "$output" == *"$expected_message"* ]]; then
    pass "$name"
  else
    fail "$name: expected error containing '$expected_message', got '$output'"
  fi
}
```

Insert these test functions before the existing test invocations:

```bash
test_no_answer_payload() {
  if ! run_success 'no-answer payload' \
    RUN_MODE=simulate \
    DRY_RUN=true \
    SIMULATED_CARRIER_STATUS=no_answer \
    CONTACT_ATTEMPT=2 \
    MAX_CONTACT_ATTEMPTS=3; then
    return
  fi

  assert_json_eq 'no-answer omits ETA' "$RUN_OUTPUT" \
    '.payload.simulation | has("reported_eta")' 'false'
  assert_json_eq 'no-answer omits temperature' "$RUN_OUTPUT" \
    '.payload.simulation | has("temperature_c")' 'false'
  assert_json_eq 'script omits escalation decision' "$RUN_OUTPUT" \
    '.payload | has("escalate")' 'false'
  assert_json_eq 'no-answer forwards current attempt' "$RUN_OUTPUT" \
    '.payload.policy.contact.attempt' '2'
}

test_out_of_range_payload() {
  if ! run_success 'out-of-range facts' \
    RUN_MODE=simulate \
    DRY_RUN=true \
    SIMULATED_CARRIER_STATUS=confirmed \
    SIMULATED_TEMPERATURE_C=12; then
    return
  fi

  assert_json_eq 'out-of-range temperature is forwarded' "$RUN_OUTPUT" \
    '.payload.simulation.temperature_c' '12'
  assert_json_eq 'out-of-range decision stays in workflow' "$RUN_OUTPUT" \
    '.payload | has("severity")' 'false'
}

test_delayed_payload() {
  if ! run_success 'delayed facts' \
    RUN_MODE=simulate \
    DRY_RUN=true \
    SIMULATED_CARRIER_STATUS=delayed \
    SIMULATED_REPORTED_ETA=2026-09-19T14:30:00Z \
    SIMULATED_TEMPERATURE_C=6.4; then
    return
  fi

  assert_json_eq 'delayed status is forwarded' "$RUN_OUTPUT" \
    '.payload.simulation.carrier_status' 'delayed'
  assert_json_eq 'delayed ETA is forwarded' "$RUN_OUTPUT" \
    '.payload.simulation.reported_eta' '2026-09-19T14:30:00Z'
  assert_json_eq 'delayed temperature is forwarded' "$RUN_OUTPUT" \
    '.payload.simulation.temperature_c' '6.4'
}

test_no_answer_at_maximum_payload() {
  if ! run_success 'no-answer at maximum payload' \
    RUN_MODE=simulate \
    DRY_RUN=true \
    SIMULATED_CARRIER_STATUS=no_answer \
    CONTACT_ATTEMPT=3 \
    MAX_CONTACT_ATTEMPTS=3; then
    return
  fi

  assert_json_eq 'maximum payload forwards current attempt' "$RUN_OUTPUT" \
    '.payload.policy.contact.attempt' '3'
  assert_json_eq 'maximum payload forwards attempt limit' "$RUN_OUTPUT" \
    '.payload.policy.contact.max_attempts' '3'
  assert_json_eq 'maximum-attempt decision stays in workflow' "$RUN_OUTPUT" \
    '.payload | has("escalate")' 'false'
}

test_invalid_inputs() {
  assert_command_fails 'invalid run mode' 'RUN_MODE no válido' \
    RUN_MODE=unknown DRY_RUN=true
  assert_command_fails 'invalid simulated status' 'SIMULATED_CARRIER_STATUS no válido' \
    RUN_MODE=simulate SIMULATED_CARRIER_STATUS=unknown DRY_RUN=true
  assert_command_fails 'invalid language' 'LANGUAGE no válido' \
    RUN_MODE=simulate LANGUAGE=it DRY_RUN=true
  assert_command_fails 'invalid dry-run value' 'DRY_RUN debe ser true o false' \
    RUN_MODE=simulate DRY_RUN=tru
  assert_command_fails 'inverted temperature range' 'El mínimo de temperatura no puede superar el máximo' \
    RUN_MODE=simulate TEMPERATURE_MIN_C=9 TEMPERATURE_MAX_C=2 DRY_RUN=true
  assert_command_fails 'malformed temperature' 'TEMPERATURE_MIN_C no es un número' \
    RUN_MODE=simulate TEMPERATURE_MIN_C=unknown DRY_RUN=true
  assert_command_fails 'attempt above maximum' 'CONTACT_ATTEMPT no puede superar MAX_CONTACT_ATTEMPTS' \
    RUN_MODE=simulate CONTACT_ATTEMPT=4 MAX_CONTACT_ATTEMPTS=3 DRY_RUN=true
  assert_command_fails 'invalid retry delay' 'RETRY_DELAY_MINUTES no es un entero positivo' \
    RUN_MODE=simulate RETRY_DELAY_MINUTES=0 DRY_RUN=true
  assert_command_fails 'no-answer with temperature' 'no_answer no admite temperatura ni ETA reportadas' \
    RUN_MODE=simulate SIMULATED_CARRIER_STATUS=no_answer SIMULATED_TEMPERATURE_C=5 DRY_RUN=true
  assert_command_fails 'live without event id' 'EVENT_ID es obligatorio en modo live' \
    RUN_MODE=live EVENT_ID= CARRIER_CONTACT_ID=contact-123 DRY_RUN=true
  assert_command_fails 'live without contact id' 'CARRIER_CONTACT_ID es obligatorio en modo live' \
    RUN_MODE=live EVENT_ID=event-live-002 CARRIER_CONTACT_ID= DRY_RUN=true
  assert_command_fails 'live with simulation fields' 'Los campos SIMULATED_* solo se admiten en modo simulate' \
    RUN_MODE=live EVENT_ID=event-live-003 CARRIER_CONTACT_ID=contact-123 SIMULATED_CARRIER_STATUS=confirmed DRY_RUN=true
  assert_command_fails 'raw phone rejected' 'Usa CARRIER_CONTACT_ID; no pases teléfonos en el payload' \
    RUN_MODE=live EVENT_ID=event-live-004 CARRIER_CONTACT_ID=contact-123 CARRIER_PHONE=+34123456789 DRY_RUN=true
}
```

Replace the test invocation block with:

```bash
test_simulated_confirmed_payload
test_live_payload
test_out_of_range_payload
test_delayed_payload
test_no_answer_payload
test_no_answer_at_maximum_payload
test_invalid_inputs

printf '%s passes, %s failures\n' "$passes" "$failures"
[[ "$failures" -eq 0 ]]
```

- [ ] **Step 2: Run the expanded tests to verify they fail**

Run:

```bash
bash tests/examples/kuehne-nagel-milestone-follow-up.test.sh
```

Expected: the existing happy-path assertions pass, while the invalid-input cases report `command unexpectedly succeeded`.

- [ ] **Step 3: Add validation functions to the example script**

Insert this block after the simulation response variables and before `body=...`:

```bash
die() {
  printf '%s\n' "$1" >&2
  exit 1
}

is_number() {
  [[ "$1" =~ ^-?[0-9]+([.][0-9]+)?$ ]]
}

is_positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

case "$run_mode" in
  simulate|live) ;;
  *) die "RUN_MODE no válido: $run_mode" ;;
esac

case "$language" in
  en|es|de|fr|zh) ;;
  *) die "LANGUAGE no válido: $language" ;;
esac

case "$dry_run" in
  true|false) ;;
  *) die 'DRY_RUN debe ser true o false' ;;
esac

is_number "$temperature_min_c" || die "TEMPERATURE_MIN_C no es un número: $temperature_min_c"
is_number "$temperature_max_c" || die "TEMPERATURE_MAX_C no es un número: $temperature_max_c"

if awk -v minimum="$temperature_min_c" -v maximum="$temperature_max_c" \
  'BEGIN { exit !(minimum > maximum) }'; then
  die 'El mínimo de temperatura no puede superar el máximo'
fi

is_positive_integer "$contact_attempt" || die "CONTACT_ATTEMPT no es un entero positivo: $contact_attempt"
is_positive_integer "$max_contact_attempts" || die "MAX_CONTACT_ATTEMPTS no es un entero positivo: $max_contact_attempts"
is_positive_integer "$retry_delay_minutes" || die "RETRY_DELAY_MINUTES no es un entero positivo: $retry_delay_minutes"

if (( contact_attempt > max_contact_attempts )); then
  die 'CONTACT_ATTEMPT no puede superar MAX_CONTACT_ATTEMPTS'
fi

if [[ -n "${CARRIER_PHONE:-}" ]]; then
  die 'Usa CARRIER_CONTACT_ID; no pases teléfonos en el payload'
fi

if [[ "$run_mode" == 'live' ]]; then
  [[ -n "${EVENT_ID:-}" ]] || die 'EVENT_ID es obligatorio en modo live'
  [[ -n "$carrier_contact_id" ]] || die 'CARRIER_CONTACT_ID es obligatorio en modo live'

  if [[ -n "${SIMULATED_CARRIER_STATUS:-}" || \
        -n "${SIMULATED_REPORTED_ETA:-}" || \
        -n "${SIMULATED_TEMPERATURE_C:-}" ]]; then
    die 'Los campos SIMULATED_* solo se admiten en modo simulate'
  fi
else
  case "$simulated_status" in
    confirmed|delayed|no_answer) ;;
    *) die "SIMULATED_CARRIER_STATUS no válido: $simulated_status" ;;
  esac

  if [[ -n "$simulated_temperature_c" ]]; then
    is_number "$simulated_temperature_c" || \
      die "SIMULATED_TEMPERATURE_C no es un número: $simulated_temperature_c"
  fi

  if [[ "$simulated_status" == 'no_answer' && \
        ( -n "$simulated_reported_eta" || -n "$simulated_temperature_c" ) ]]; then
    die 'no_answer no admite temperatura ni ETA reportadas'
  fi
fi
```

- [ ] **Step 4: Run all tests**

Run:

```bash
bash tests/examples/kuehne-nagel-milestone-follow-up.test.sh
```

Expected: exit code `0` and `33 passes, 0 failures`.

- [ ] **Step 5: Run syntax and static checks**

```bash
bash -n examples/08-kuehne-nagel-milestone-follow-up.sh tests/examples/kuehne-nagel-milestone-follow-up.test.sh
shellcheck examples/08-kuehne-nagel-milestone-follow-up.sh tests/examples/kuehne-nagel-milestone-follow-up.test.sh
```

Expected: both commands exit `0`. If `shellcheck` is unavailable, record that fact and rely on `bash -n` plus the behavioral test harness.

- [ ] **Step 6: Commit validation**

```bash
git add examples/08-kuehne-nagel-milestone-follow-up.sh tests/examples/kuehne-nagel-milestone-follow-up.test.sh
git commit -m "Validate milestone follow-up scenarios"
```

### Task 3: Document the use case and operational boundary

**Files:**

- Modify: `examples/README.md`

- [ ] **Step 1: Add the example to the recommended walkthrough**

Append this command after the DHL example in the existing walkthrough code block:

```bash
# 7. Simular seguimiento de un hito con un transportista
./examples/08-kuehne-nagel-milestone-follow-up.sh "$WORKFLOW_ID"
```

- [ ] **Step 2: Add the Kuehne+Nagel use-case section**

Insert this section before `## Decisiones de seguridad`:

````markdown
## Caso de uso: seguimiento de hitos con transportistas

Este ejemplo adapta el caso público de Kuehne+Nagel Healthcare HyperCare. El
script representa al TMS y envía los hechos de un hito pendiente; el workflow de
HappyRobot es responsable de contactar al transportista, interpretar la
respuesta, reintentar o escalar.

Simulación de una confirmación correcta:

```bash
RUN_MODE=simulate \
SIMULATED_CARRIER_STATUS=confirmed \
SIMULATED_REPORTED_ETA=2026-09-19T09:55:00Z \
SIMULATED_TEMPERATURE_C=5.2 \
./examples/08-kuehne-nagel-milestone-follow-up.sh "$WORKFLOW_ID"
```

Simulación sin respuesta en el último intento:

```bash
RUN_MODE=simulate \
SIMULATED_CARRIER_STATUS=no_answer \
CONTACT_ATTEMPT=3 \
MAX_CONTACT_ATTEMPTS=3 \
./examples/08-kuehne-nagel-milestone-follow-up.sh "$WORKFLOW_ID"
```

Vista previa de un payload live, todavía sin iniciar el workflow:

```bash
RUN_MODE=live \
EVENT_ID="milestone-KN-HC-002-arrival" \
CARRIER_CONTACT_ID="contact-from-server" \
DRY_RUN=true \
./examples/08-kuehne-nagel-milestone-follow-up.sh "$WORKFLOW_ID"
```

Para una ejecución real hay que establecer `DRY_RUN=false` y disponer de un
workflow que implemente la llamada, extracción de respuesta, deduplicación,
persistencia de intentos y escalado. El script no toma esas decisiones.

El contrato del workflow debe cumplir además estas condiciones:

- usar `event_id` para garantizar idempotencia antes de llamar o escalar;
- persistir el resultado y el contador de intentos;
- devolver o registrar resultado, gravedad y siguiente acción;
- exponer ese estado al dashboard para reconocimiento o intervención humana.

Después de iniciar una ejecución, puedes localizar su estado con:

```bash
./examples/04-list-workflow-runs.sh "$WORKFLOW_ID"
```
````

- [ ] **Step 3: Add source attribution**

Append these source links under `## Fuentes oficiales consultadas`:

```markdown
- [Kuehne+Nagel x HappyRobot](https://www.happyrobot.ai/customer-story/kuehne-nagel)
- [Kuehne+Nagel HyperCare](https://www.kuehne-nagel.com/us/market-insights/healthcare/product-integrity-within-supply-chain)
```

- [ ] **Step 4: Check documentation formatting**

Run:

```bash
rg -n '[[:blank:]]$' examples/README.md
```

Expected: no output and exit code `1`, meaning no trailing whitespace was found.

- [ ] **Step 5: Commit documentation**

```bash
git add examples/README.md
git commit -m "Document carrier milestone tracking example"
```

### Task 4: Final verification

**Files:**

- Verify: `examples/08-kuehne-nagel-milestone-follow-up.sh`
- Verify: `tests/examples/kuehne-nagel-milestone-follow-up.test.sh`
- Verify: `examples/README.md`

- [ ] **Step 1: Run the complete test harness**

```bash
bash tests/examples/kuehne-nagel-milestone-follow-up.test.sh
```

Expected: `33 passes, 0 failures`.

- [ ] **Step 2: Verify the default dry-run payload manually**

```bash
HAPPYROBOT_KEY=test-key \
./examples/08-kuehne-nagel-milestone-follow-up.sh test-workflow \
  | jq '{mode: .payload.mode, event_id: .payload.event_id, simulation: .payload.simulation}'
```

Expected: mode `simulate`, a deterministic demo event ID, and a simulated
`confirmed` response. No HTTP request is made.

- [ ] **Step 3: Verify that no decision leaked into the caller payload**

```bash
HAPPYROBOT_KEY=test-key \
./examples/08-kuehne-nagel-milestone-follow-up.sh test-workflow \
  | jq -e '(.payload | has("severity") or has("escalate") or has("recommended_action")) | not'
```

Expected: output `true` and exit code `0`.

- [ ] **Step 4: Run repository checks**

```bash
bash -n examples/*.sh examples/_lib/happyrobot.sh tests/examples/*.sh
git diff --check
git status --short
```

Expected: syntax and whitespace checks pass. Status contains only the intended
example work and any pre-existing user changes; no `.env` file is tracked.

- [ ] **Step 5: Review the final diff without triggering external actions**

```bash
git diff -- examples/08-kuehne-nagel-milestone-follow-up.sh tests/examples/kuehne-nagel-milestone-follow-up.test.sh examples/README.md
```

Expected: only the planned script, tests, and documentation changes. Do not run
with `DRY_RUN=false` during verification.
