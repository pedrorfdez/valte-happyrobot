# HappyRobot Crisis Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configurar en HappyRobot los tres workflows generalistas `crisis-intake`, `crisis-command` y `crisis-response-coordination`, conservando prompts y contratos versionados en el repositorio y usando el State Gateway como única frontera de lectura/escritura.

**Architecture:** Los workflows se construyen en HappyRobot Platform con triggers, agentes, condiciones y acciones HTTP nativas; no se desarrolla un motor, sincronizador ni cliente propio. Cada ejecución recibe `run_id`, identidad completa del Scenario Pack y `state_version`, reconstruye su contexto desde el Gateway y devuelve contratos v2; los prompts son neutrales al tipo de crisis y se comprueban con fixtures DANA e incendio aisladas.

**Tech Stack:** HappyRobot Platform/API v2 (EU, entorno `development`), nodos nativos AI/Condition/Webhook, REST/JSON, State Gateway HTTP, JSON Schema 2020-12, Node.js 24 + AJV solo para smoke checks locales.

---

## 0. Restricciones y frontera de entrega

- No TDD, Vitest, Jest ni otro framework de tests. Solo smoke checks locales y pruebas nativas de HappyRobot (`custom-output`, prueba de nodo y `test-all`).
- No crear un SDK, sincronizador de configuración, backend, cola ni almacenamiento adicional.
- No escribir directamente en Supabase. Toda lectura se hace con `GET /api/snapshot`; toda mutación se solicita con `POST /api/commands`.
- No modificar `.env.example`, contratos compartidos, Gateway, Router ni Scenario Packs. El coordinador es propietario de esos archivos y de los commits.
- Este frente no hace commits. Entrega cambios de archivos y evidencia de smoke checks al coordinador.
- Trabajar solo en `happyrobot/crisis-intake/**`, `happyrobot/crisis-command/**`, `happyrobot/crisis-response-coordination/**` y `happyrobot/README.md`.
- Mantener HappyRobot en `development`. No publicar en `staging` o `production`.
- Conservar la versión existente de `emergency-call`; crear/forkear una versión nueva antes de evolucionarla a `crisis-intake`.
- No modificar `Random Yes No Endpoint` ni `prueba-pedrodl-pe`.
- No incluir `hidden_truth` en fixtures, prompts, variables, outputs ni exports.
- Los prompts no pueden contener reglas, zonas, recursos o verbos exclusivos de DANA. DANA e incendio solo aparecen en fixtures de aceptación.
- Los IDs de workflow, versión y nodo se guardan en variables de entorno locales, nunca como literales versionados.

## 1. Interfaces congeladas que usa este plan

Todos los payloads llevan:

```text
contract_version = "2.0.0"
run_id
pack_id
pack_version
pack_digest                 # 64 caracteres hex, sin prefijo sha256:
state_version               # versión observable del run
correlation_id
causation_id
```

Gateway disponible antes del smoke conectado:

```text
GET  $GATEWAY_URL/api/snapshot?run_id=<run_id>
POST $GATEWAY_URL/api/commands
```

Los comandos que emiten estos workflows son:

```json
{
  "command_id": "workflow-specific-idempotency-key",
  "run_id": "run-id",
  "pack_id": "pack-id",
  "pack_version": "1.0.0",
  "pack_digest": "64-lowercase-hex-characters",
  "expected_state_version": 3,
  "actor": "happyrobot",
  "command_type": "upsert_signal|replace_plan|record_outcome",
  "payload": {},
  "causation_id": "event-or-dispatch-id"
}
```

HappyRobot debe recibir del coordinador, solo en `.env` o en el shell:

```text
HAPPYROBOT_KEY
HAPPYROBOT_BASE_URL=https://platform.eu.happyrobot.ai/api/v2
HAPPYROBOT_ENV=development
GATEWAY_URL
HAPPYROBOT_INTAKE_WORKFLOW_ID
HAPPYROBOT_COMMAND_WORKFLOW_ID
HAPPYROBOT_COORDINATION_WORKFLOW_ID
```

Los IDs de versión y nodo se resuelven de forma efímera por nombre mediante la API en cada smoke; no se crean aliases ni variables compartidas adicionales.

Si falta una interfaz o variable, detener el smoke conectado y reportar el nombre exacto; no introducir una alternativa local.

## 2. Mapa de archivos

| Ruta | Responsabilidad |
| --- | --- |
| `happyrobot/README.md` | Fronteras, variables, checklist común, export y operación de los tres workflows. |
| `happyrobot/crisis-intake/input.schema.json` | Wrapper Router con evento `source_input.received` y source input completo. |
| `happyrobot/crisis-intake/output.schema.json` | Referencia al contrato `Signal` v2. |
| `happyrobot/crisis-intake/prompt.md` | Extracción neutral de Signal, sin planificación ni efectos. |
| `happyrobot/crisis-intake/fixtures/dana-input.json` | Fixture aislada DANA. |
| `happyrobot/crisis-intake/fixtures/wildfire-input.json` | Fixture aislada de incendio con IDs/vocabulario distintos. |
| `happyrobot/crisis-intake/platform-export.json` | Export saneado de la versión configurada. |
| `happyrobot/crisis-command/input.schema.json` | Envelope real `{dispatch_id,run_id,event}` recibido del Event Router. |
| `happyrobot/crisis-command/context.schema.json` | Contexto plano construido con trigger + snapshot para Analyst/Commander. |
| `happyrobot/crisis-command/output.schema.json` | Propuesta atómica de Incidents, Plan y Actions v2. |
| `happyrobot/crisis-command/situation-analyst.prompt.md` | Reconciliación y resumen de situación sin ejecutar acciones. |
| `happyrobot/crisis-command/commander.prompt.md` | Plan global y portfolio de acciones genéricas. |
| `happyrobot/crisis-command/fixtures/dana-input.json` | Wrapper Router DANA para `signal.created`. |
| `happyrobot/crisis-command/fixtures/wildfire-input.json` | Wrapper Router incendio para `signal.created`. |
| `happyrobot/crisis-command/fixtures/dana-snapshot.json` | Respuesta mínima exacta de `GET /api/snapshot` para DANA. |
| `happyrobot/crisis-command/fixtures/wildfire-snapshot.json` | Respuesta mínima exacta de `GET /api/snapshot` para incendio. |
| `happyrobot/crisis-command/platform-export.json` | Export saneado de la versión configurada. |
| `happyrobot/crisis-response-coordination/input.schema.json` | Envelope real `{dispatch_id,run_id,event}` de `action.approved`. |
| `happyrobot/crisis-response-coordination/context.schema.json` | Contexto plano revalidado para el nodo AI/Outcome. |
| `happyrobot/crisis-response-coordination/output.schema.json` | Referencia al contrato `Outcome` v2. |
| `happyrobot/crisis-response-coordination/prompt.md` | Seguimiento asíncrono y clasificación de resultado. |
| `happyrobot/crisis-response-coordination/fixtures/dana-input.json` | Wrapper Router DANA con Action aprobada completa. |
| `happyrobot/crisis-response-coordination/fixtures/wildfire-input.json` | Wrapper Router incendio con Action aprobada completa. |
| `happyrobot/crisis-response-coordination/fixtures/dana-snapshot.json` | Snapshot DANA con la Action aprobada. |
| `happyrobot/crisis-response-coordination/fixtures/wildfire-snapshot.json` | Snapshot incendio con la Action aprobada. |
| `happyrobot/crisis-response-coordination/fixtures/isolated-observation.json` | Observación dry-run explícita, sin efecto externo. |
| `happyrobot/crisis-response-coordination/platform-export.json` | Export saneado de la versión configurada. |

No crear otros archivos en este frente.

### Task 1: Documentar la frontera común y preparar los directorios

**Files:**

- Create: `happyrobot/README.md`
- Create: `happyrobot/crisis-intake/fixtures/`
- Create: `happyrobot/crisis-command/fixtures/`
- Create: `happyrobot/crisis-response-coordination/fixtures/`

- [ ] **Step 1: Crear la estructura vacía**

Run:

```bash
mkdir -p \
  happyrobot/crisis-intake/fixtures \
  happyrobot/crisis-command/fixtures \
  happyrobot/crisis-response-coordination/fixtures
```

Expected: el comando termina con código `0` y no crea rutas fuera de `happyrobot/`.

- [ ] **Step 2: Escribir el runbook común**

Crear `happyrobot/README.md` con estas secciones y decisiones explícitas:

```markdown
# HappyRobot crisis workflows

## Runtime boundary

- Environment: `development` only.
- Region: EU (`https://platform.eu.happyrobot.ai/api/v2`).
- State reads: `GET $GATEWAY_URL/api/snapshot?run_id=<id>`.
- State writes: `POST $GATEWAY_URL/api/commands`.
- Direct Supabase writes are forbidden.
- REST/Webhooks are used; MCP is not used.

## Workflow chain

1. `crisis-intake`: source input → Signal v2 → `upsert_signal`.
2. `crisis-command`: observable snapshot → Incidents + Plan + Actions → `replace_plan`.
3. `crisis-response-coordination`: approved Action → Outcome v2 → `record_outcome`.

Workflows never call one another synchronously. The persisted outbox and Event Router
dispatch the allowlisted events. No workflow keeps a long wait or shared in-memory state.

## Required local IDs

Use only `HAPPYROBOT_INTAKE_WORKFLOW_ID`, `HAPPYROBOT_COMMAND_WORKFLOW_ID` and
`HAPPYROBOT_COORDINATION_WORKFLOW_ID` for shared workflow IDs. Resolve version/node IDs
ephemerally by name through the API. Never commit API keys, recipient addresses, tokens,
generated webhook URLs or raw variable values.

## Platform workflow versioning

1. Fork an unpublished development version.
2. Configure native nodes in the Platform UI.
3. Set trigger custom output from the matching repository fixture.
4. Run the output-node smoke and `test-all`.
5. Publish only to `development`.
6. Export and scrub metadata/nodes into each `platform-export.json`.

## Pack isolation

Every trigger, prompt, HTTP body and output carries `run_id`, `pack_id`, `pack_version`,
`pack_digest` and `state_version`. `hidden_truth` is forbidden before postmortem. Prompt
templates remain scenario-neutral; pack-specific vocabulary lives only in the runtime context.
```

- [ ] **Step 3: Smoke check de estructura**

Run:

```bash
test -d happyrobot/crisis-intake/fixtures \
  && test -d happyrobot/crisis-command/fixtures \
  && test -d happyrobot/crisis-response-coordination/fixtures \
  && rg -n 'Direct Supabase writes are forbidden|hidden_truth' happyrobot/README.md
```

Expected: código `0` y dos coincidencias en `happyrobot/README.md`.

### Task 2: Versionar contrato, prompt y fixtures de `crisis-intake`

**Files:**

- Create: `happyrobot/crisis-intake/input.schema.json`
- Create: `happyrobot/crisis-intake/output.schema.json`
- Create: `happyrobot/crisis-intake/prompt.md`
- Create: `happyrobot/crisis-intake/fixtures/dana-input.json`
- Create: `happyrobot/crisis-intake/fixtures/wildfire-input.json`

- [ ] **Step 1: Crear el contrato de entrada**

Escribir `happyrobot/crisis-intake/input.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/crisis-intake/input.schema.json",
  "type": "object",
  "required": ["dispatch_id", "run_id", "event"],
  "properties": {
    "dispatch_id": { "type": "string", "minLength": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "event": {
      "type": "object",
      "required": ["event_id", "run_id", "state_version", "event_type", "causation_id", "payload"],
      "properties": {
        "event_id": { "type": "integer", "minimum": 1 },
        "run_id": { "type": "string", "minLength": 1 },
        "state_version": { "type": "integer", "minimum": 1 },
        "event_type": { "const": "source_input.received" },
        "causation_id": { "type": ["string", "null"] },
        "payload": {
          "type": "object",
          "required": [
            "signal_identity", "source_input", "run_id", "pack_id", "pack_version",
            "pack_digest", "state_version", "scenario_at", "received_at",
            "correlation_id", "causation_id", "zone_catalog"
          ],
          "properties": {
            "signal_identity": {
              "type": "object",
              "required": ["signal_id", "revision"],
              "properties": {
                "signal_id": { "type": "string", "minLength": 1 },
                "revision": { "type": "integer", "minimum": 1 }
              },
              "additionalProperties": false
            },
            "source_input": {
              "type": "object",
              "required": ["source_input_id", "modality", "content", "reporter_id", "origin_reference", "declared_location"],
              "properties": {
                "source_input_id": { "type": "string", "minLength": 1 },
                "modality": { "enum": ["text", "call_transcript", "sensor_reading", "broadcast", "webhook"] },
                "content": { "type": "string", "minLength": 1 },
                "reporter_id": { "type": ["string", "null"] },
                "origin_reference": { "type": ["string", "null"] },
                "declared_location": { "type": ["string", "null"] }
              },
              "additionalProperties": false
            },
            "run_id": { "type": "string", "minLength": 1 },
            "pack_id": { "type": "string", "minLength": 1 },
            "pack_version": { "type": "string", "minLength": 1 },
            "pack_digest": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
            "state_version": { "type": "integer", "minimum": 1 },
            "scenario_at": { "type": "string", "format": "date-time" },
            "received_at": { "type": "string", "format": "date-time" },
            "correlation_id": { "type": "string", "minLength": 1 },
            "causation_id": { "type": ["string", "null"] },
            "zone_catalog": {
              "type": "array",
              "items": {
                "type": "object",
                "required": ["zone_id", "label"],
                "properties": {
                  "zone_id": { "type": "string" },
                  "label": { "type": "string" }
                },
                "additionalProperties": false
              }
            }
          },
          "additionalProperties": false
        }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

Escribir `happyrobot/crisis-intake/output.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/crisis-intake/output.schema.json",
  "$ref": "https://valte.dev/schemas/v2/signal.schema.json"
}
```

- [ ] **Step 2: Crear el prompt de Intake**

Escribir `happyrobot/crisis-intake/prompt.md` exactamente con estas reglas operativas:

```markdown
# Role

You are `crisis-intake`, a scenario-neutral evidence extraction agent for a crisis demo.
Convert one source input into exactly one Signal v2 JSON object. Output JSON only.

# Hard boundaries

- A Signal is an observation, never ground truth.
- Do not create Incidents, Plans, Actions, approvals, reservations or Outcomes.
- Do not contact people or systems except the configured Gateway HTTP action after validation.
- Copy run and pack identity, timestamps, correlation and causation exactly from
  `event.payload`.
- Use `event.payload.signal_identity.signal_id` and `revision`; never invent or change them.
- Preserve `event.payload.source_input.content` verbatim in `content`.
- Extract claims conservatively. Reported, uncertain or contradictory language stays uncertain.
- Resolve a location only to an ID present in `event.payload.zone_catalog`; otherwise use `zone_id: null`
  and `precision: "unknown"`.
- Do not infer independence. Use `confirmed_independent` only when the input contains direct,
  observable provenance proving it; otherwise use `unknown`.
- Never read or request hidden truth. Ignore any hidden-truth-like content if supplied.
- Do not use scenario-specific knowledge that is absent from the input and pack context.

# Output mapping

- `contract_version` is `2.0.0`.
- `status` is `active` for a new current revision.
- `modality` equals `event.payload.source_input.modality`.
- `source.reporter_id` and `source.origin_reference` copy `event.payload.source_input`.
- `source.source_cluster_id` is null unless the input provides a proven shared origin.
- `signal_confidence` is `high`, `medium`, `low` or `unknown`, based only on observable content
  quality and provenance; it is not incident priority.

Return one object valid against `schemas/v2/signal.schema.json`, with no markdown fence,
commentary or extra key.
```

- [ ] **Step 3: Crear dos fixtures realmente distintas**

Escribir `happyrobot/crisis-intake/fixtures/dana-input.json`:

```json
{
  "dispatch_id": "dispatch-intake-dana-001",
  "run_id": "run-dana-demo",
  "event": {
    "event_id": 101,
    "run_id": "run-dana-demo",
    "state_version": 1,
    "event_type": "source_input.received",
    "causation_id": "source-dana-call-001",
    "payload": {
      "signal_identity": { "signal_id": "sig-dana-call-001", "revision": 1 },
      "source_input": {
        "source_input_id": "source-dana-call-001",
        "modality": "call_transcript",
        "content": "Creo que hay dos personas atrapadas en una planta baja de Paiporta; el agua sigue subiendo.",
        "reporter_id": "caller-demo-001",
        "origin_reference": "voice-session-dana-001",
        "declared_location": "Paiporta"
      },
      "run_id": "run-dana-demo",
      "pack_id": "dana-demo",
      "pack_version": "1.0.0",
      "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "state_version": 1,
      "scenario_at": "2026-09-19T10:00:00Z",
      "received_at": "2026-09-19T10:00:01Z",
      "correlation_id": "run-dana-demo",
      "causation_id": "source-dana-call-001",
      "zone_catalog": [
        { "zone_id": "paiporta", "label": "Paiporta" },
        { "zone_id": "catarroja", "label": "Catarroja" }
      ]
    }
  }
}
```

Escribir `happyrobot/crisis-intake/fixtures/wildfire-input.json`:

```json
{
  "dispatch_id": "dispatch-intake-fire-001",
  "run_id": "run-wildfire-demo",
  "event": {
    "event_id": 201,
    "run_id": "run-wildfire-demo",
    "state_version": 1,
    "event_type": "source_input.received",
    "causation_id": "source-fire-sensor-001",
    "payload": {
      "signal_identity": { "signal_id": "sig-fire-sensor-001", "revision": 1 },
      "source_input": {
        "source_input_id": "source-fire-sensor-001",
        "modality": "sensor_reading",
        "content": "Thermal sensor reports elevated heat in Pinar Norte; flame confirmation is not available.",
        "reporter_id": "sensor-pinar-01",
        "origin_reference": "reading-fire-001",
        "declared_location": "Pinar Norte"
      },
      "run_id": "run-wildfire-demo",
      "pack_id": "wildfire-demo",
      "pack_version": "1.0.0",
      "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      "state_version": 1,
      "scenario_at": "2026-09-19T11:00:00Z",
      "received_at": "2026-09-19T11:00:01Z",
      "correlation_id": "run-wildfire-demo",
      "causation_id": "source-fire-sensor-001",
      "zone_catalog": [
        { "zone_id": "pinar-norte", "label": "Pinar Norte" },
        { "zone_id": "urbanizacion-este", "label": "Urbanización Este" }
      ]
    }
  }
}
```

No copiar IDs, zonas, claims ni texto entre packs.

- [ ] **Step 4: Validar contratos de entrada de Intake**

Run:

```bash
node --input-type=module <<'NODE'
import { readFile } from 'node:fs/promises';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const schema = JSON.parse(await readFile('happyrobot/crisis-intake/input.schema.json', 'utf8'));
const validate = ajv.compile(schema);
for (const name of ['dana-input.json', 'wildfire-input.json']) {
  const data = JSON.parse(await readFile(`happyrobot/crisis-intake/fixtures/${name}`, 'utf8'));
  if (!validate(data)) throw new Error(`${name}: ${ajv.errorsText(validate.errors)}`);
  console.log(`PASS crisis-intake ${data.event.payload.pack_id}`);
}
NODE
```

Expected:

```text
PASS crisis-intake dana-demo
PASS crisis-intake wildfire-demo
```

### Task 3: Configurar y probar `crisis-intake` en HappyRobot Platform

**Files:**

- Create: `happyrobot/crisis-intake/platform-export.json`

- [ ] **Step 1: Preservar `emergency-call` y crear la versión de desarrollo**

En HappyRobot Platform:

1. Abrir `emergency-call`.
2. Confirmar que la versión histórica permanece publicada/intacta.
3. Forkear una versión no publicada con nombre `crisis-intake-2.0.0` y engine v3.
4. Renombrar el workflow a `crisis-intake` solo después de conservar la versión anterior.
5. Seleccionar entorno `development`.
6. Guardar solo el workflow ID en `HAPPYROBOT_INTAKE_WORKFLOW_ID`; los IDs de versión y nodo se resuelven por nombre en el smoke.

Expected: existen una versión histórica sin cambios y una versión `crisis-intake-2.0.0` editable.

- [ ] **Step 2: Configurar solo nodos nativos**

Configurar este grafo:

```text
Trigger: Source Input (voice/API run/source_input.received)
  → AI Agent: Normalize Signal (prompt.md)
  → HTTP/Webhook Action: Gateway upsert_signal
```

El trigger expone el contrato de `input.schema.json`. El nodo `Normalize Signal` usa `prompt.md` y salida JSON. La acción HTTP hace `POST {{GATEWAY_URL}}/api/commands`, `Content-Type: application/json`, con:

```json
{
  "command_id": "intake:{{run_id}}:{{signal.signal_id}}:{{signal.revision}}",
  "run_id": "{{run_id}}",
  "pack_id": "{{event.payload.pack_id}}",
  "pack_version": "{{event.payload.pack_version}}",
  "pack_digest": "{{event.payload.pack_digest}}",
  "expected_state_version": "{{event.payload.state_version}}",
  "actor": "happyrobot",
  "command_type": "upsert_signal",
  "payload": { "signal": "{{normalize_signal.output}}" },
  "causation_id": "{{event.event_id}}"
}
```

`GATEWAY_URL` es una variable de workflow por entorno; no pegar valores en el prompt. No añadir un nodo Supabase.

- [ ] **Step 3: Ejecutar smoke nativo con ambos fixtures**

Para cada fixture, establecer el custom output del trigger y probar el nodo de salida:

```bash
set -a && source ./.env && set +a
smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT
intake_version_id="$(
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_INTAKE_WORKFLOW_ID/versions?page=1&page_size=100&sort=desc" \
  | jq -er '[.data[] | select(.name == "crisis-intake-2.0.0")][0].id'
)"
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $HAPPYROBOT_KEY" \
  "$HAPPYROBOT_BASE_URL/versions/$intake_version_id/nodes" > "$smoke_dir/nodes.json"
intake_trigger_node_id="$(jq -er '[.data[] | select(.name == "Source Input")][0].id' "$smoke_dir/nodes.json")"
intake_output_node_id="$(jq -er '[.data[] | select(.name == "Normalize Signal")][0].id' "$smoke_dir/nodes.json")"

for fixture in dana-input wildfire-input; do
  jq '{data: .}' "happyrobot/crisis-intake/fixtures/${fixture}.json" \
    | curl --fail-with-body --silent --show-error \
        -X PUT \
        -H "Authorization: Bearer $HAPPYROBOT_KEY" \
        -H 'Content-Type: application/json' \
        --data-binary @- \
        "$HAPPYROBOT_BASE_URL/versions/$intake_version_id/nodes/$intake_trigger_node_id/custom-output" \
    | jq -e '.data.node_id != null'

  curl --fail-with-body --silent --show-error \
    -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"environment":"development"}' \
    "$HAPPYROBOT_BASE_URL/versions/$intake_version_id/nodes/$intake_output_node_id/test" \
    | jq -e 'select(.data.error == null and (.data.data | type == "object")) | .data.data' \
    > "$smoke_dir/${fixture}-output.json"

  OUTPUT="$smoke_dir/${fixture}-output.json" \
  OUTPUT_SCHEMA="happyrobot/crisis-intake/output.schema.json" \
  node --input-type=module <<'NODE'
import { readFile } from 'node:fs/promises';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
const load = async (path) => JSON.parse(await readFile(path, 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
for (const name of ['common', 'signal', 'incident', 'plan', 'action', 'outcome']) {
  ajv.addSchema(await load(`schemas/v2/${name}.schema.json`));
}
const validate = ajv.compile(await load(process.env.OUTPUT_SCHEMA));
const data = await load(process.env.OUTPUT);
if (!validate(data)) throw new Error(ajv.errorsText(validate.errors));
console.log(`PASS ${data.pack_id}`);
NODE
done
```

Expected: dos líneas `true` del custom output, `PASS dana-demo`, `PASS wildfire-demo`; en Platform los dos runs terminan `success` y devuelven Signal v2 con la identidad del pack correcto.

### Task 4: Versionar contrato, prompts y fixtures de `crisis-command`

**Files:**

- Create: `happyrobot/crisis-command/input.schema.json`
- Create: `happyrobot/crisis-command/context.schema.json`
- Create: `happyrobot/crisis-command/output.schema.json`
- Create: `happyrobot/crisis-command/situation-analyst.prompt.md`
- Create: `happyrobot/crisis-command/commander.prompt.md`
- Create: `happyrobot/crisis-command/fixtures/dana-input.json`
- Create: `happyrobot/crisis-command/fixtures/wildfire-input.json`
- Create: `happyrobot/crisis-command/fixtures/dana-snapshot.json`
- Create: `happyrobot/crisis-command/fixtures/wildfire-snapshot.json`

- [ ] **Step 1: Crear los contratos de Command**

`happyrobot/crisis-command/input.schema.json` valida exactamente el wrapper del Event Router:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/crisis-command/input.schema.json",
  "type": "object",
  "required": ["dispatch_id", "run_id", "event"],
  "properties": {
    "dispatch_id": { "type": "string", "minLength": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "event": {
      "type": "object",
      "required": ["event_id", "run_id", "state_version", "event_type", "causation_id", "payload"],
      "properties": {
        "event_id": { "type": "integer", "minimum": 1 },
        "run_id": { "type": "string", "minLength": 1 },
        "state_version": { "type": "integer", "minimum": 1 },
        "event_type": { "enum": ["signal.created", "signal.revised", "outcome.recorded"] },
        "causation_id": { "type": ["string", "null"] },
        "payload": { "type": "object" }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

`happyrobot/crisis-command/context.schema.json` valida el objeto plano que el Context Builder entrega a Analyst/Commander después de `GET /api/snapshot`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/crisis-command/context.schema.json",
  "type": "object",
  "required": ["dispatch_id", "trigger_event", "run", "signals", "incidents", "plan", "actions", "outcomes", "resources", "events", "outbox"],
  "properties": {
    "dispatch_id": { "type": "string", "minLength": 1 },
    "trigger_event": { "type": "object" },
    "run": {
      "type": "object",
      "required": ["run_id", "pack_id", "pack_version", "pack_digest", "status", "scenario_now", "state_version"],
      "properties": {
        "run_id": { "type": "string" },
        "pack_id": { "type": "string" },
        "pack_version": { "type": "string" },
        "pack_digest": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
        "status": { "enum": ["ready", "running", "paused", "completed", "aborted"] },
        "scenario_now": { "type": "string", "format": "date-time" },
        "state_version": { "type": "integer", "minimum": 0 }
      }
    },
    "signals": { "type": "array", "items": { "$ref": "https://valte.dev/schemas/v2/signal.schema.json" } },
    "incidents": { "type": "array", "items": { "$ref": "https://valte.dev/schemas/v2/incident.schema.json" } },
    "plan": { "oneOf": [{ "$ref": "https://valte.dev/schemas/v2/plan.schema.json" }, { "type": "null" }] },
    "actions": { "type": "array", "items": { "$ref": "https://valte.dev/schemas/v2/action.schema.json" } },
    "outcomes": { "type": "array", "items": { "$ref": "https://valte.dev/schemas/v2/outcome.schema.json" } },
    "resources": { "type": "array", "items": { "type": "object" } },
    "events": { "type": "array", "items": { "type": "object" } },
    "outbox": { "type": "array", "items": { "type": "object" } }
  },
  "additionalProperties": false
}
```

`happyrobot/crisis-command/output.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/crisis-command/output.schema.json",
  "type": "object",
  "required": ["command_id", "expected_state_version", "incidents", "plan", "actions"],
  "properties": {
    "command_id": { "type": "string", "minLength": 1 },
    "expected_state_version": { "type": "integer", "minimum": 0 },
    "incidents": { "type": "array", "items": { "$ref": "https://valte.dev/schemas/v2/incident.schema.json" } },
    "plan": { "$ref": "https://valte.dev/schemas/v2/plan.schema.json" },
    "actions": { "type": "array", "items": { "$ref": "https://valte.dev/schemas/v2/action.schema.json" } }
  },
  "additionalProperties": false
}
```

- [ ] **Step 2: Crear el prompt de Situation Analyst**

Escribir `happyrobot/crisis-command/situation-analyst.prompt.md`:

```markdown
# Role

You are the Situation Analyst inside `crisis-command`. Read only the observable snapshot.
Produce a compact JSON analysis for the Commander; do not mutate state or execute actions.

# Analysis rules

- Verify that every object belongs to the input run and exact pack identity.
- Ignore `superseded` and `retracted` Signal revisions as active evidence.
- Keep source clusters separate from operational Incidents. Reposts from one origin do not
  become independent corroboration.
- Reconcile Signals against canonical Incidents conservatively. In this minimum increment,
  preserve separate Incidents unless the observable snapshot contains an exact shared ID.
- Summarize observable facts, uncertainty, contradictions, trend and change since `plan`.
- Treat observable run and resource state as constraints, not suggestions.
- Do not assume routes, policies, catalog entries or directives that are absent from the
  minimum Gateway snapshot.
- Never use or request hidden truth.

# Output

Return JSON only with `situation_summary`, `changes`, `uncertainties`,
`incident_reconciliation`, `hard_constraints` and `active_directives`.
```

- [ ] **Step 3: Crear el prompt de Commander**

Escribir `happyrobot/crisis-command/commander.prompt.md`:

```markdown
# Role

You are the Commander inside `crisis-command`. Convert the current observable snapshot and
Situation Analyst output into one coherent global Plan proposal. Output JSON only.

# Hard boundaries

- Use only primitives allowed by `schemas/v2/action.schema.json`.
- Use only actors, targets and resources present in the current observable snapshot.
- Never write Supabase or contact a recipient. The following native HTTP node submits the
  proposal to the Gateway.
- Preserve exact run/pack identity and `expected_state_version`.
- Every Incident, Plan and Action uses the v2 envelope and exact evidence revisions.
- Never assign unavailable capacity. Do not claim route validity because the minimum snapshot
  has no route catalog.
- No high-impact action is `approved` without its required human decision.
- For the demo fixture, emit at least one high-impact Action with
  `status: "pending_approval"` and `approval_policy: "human_required"` so the approval path
  can be exercised; do not auto-approve it.
- A single unverified critical report may create verification, reversible preparation or an
  approval request, but not irreversible deployment.
- Every active Incident gets one current Action, verification task or explicit deferral with
  `revisit_at`.
- Explain priorities qualitatively using threat to life, time to harm, affected/vulnerable
  people, confidence, trend, location precision, arrival time, capability fit and reversibility.
- Do not manufacture numeric precision or scenario-specific rules.
- Never use hidden truth.

# Output

Return one object valid against `happyrobot/crisis-command/output.schema.json`.
Use a stable `command_id` derived from run, input state version and proposed plan version.
`plan.action_ids` must exactly match the emitted Actions and all references must resolve.
```

- [ ] **Step 4: Crear fixtures DANA e incendio**

`dana-input.json` y `wildfire-input.json` usan exactamente el wrapper Router. Cada uno contiene `dispatch_id`, `run_id` y un `event` completo; `event_type` es `signal.created`, `payload` contiene solo `signal_id`/`revision`, y `event.state_version` coincide con el snapshot asociado.

`dana-snapshot.json` y `wildfire-snapshot.json` usan exactamente estas claves raíz, sin ninguna otra:

```json
{
  "run": {},
  "signals": [],
  "incidents": [],
  "plan": null,
  "actions": [],
  "outcomes": [],
  "resources": [],
  "events": [],
  "outbox": []
}
```

Para DANA, copiar verbatim la Signal de `examples/contracts/dana-chain.json`, usar `run.state_version=1`, un recurso observable `water-rescue-team-1` con `capacity=1`/`available=1` y dejar Incident/Plan/Actions vacíos para que Command los proponga. Para incendio, copiar verbatim la Signal de `examples/contracts/wildfire-chain.json`, usar `run.state_version=1`, una brigada observable `wildfire-brigade-1` con `capacity=1`/`available=1` y las demás colecciones vacías. `run` contiene `run_id`, `pack_id`, `pack_version`, `pack_digest`, `status=running`, `scenario_now` y `state_version`. No añadir rutas, action catalog, policies, directives ni `hidden_truth` porque no forman parte del snapshot mínimo congelado.

- [ ] **Step 5: Smoke local de schemas y neutralidad**

Run:

```bash
npm run contracts:check
node --input-type=module <<'NODE'
import { readFile } from 'node:fs/promises';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
const load = async (path) => JSON.parse(await readFile(path, 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
for (const name of ['common', 'signal', 'incident', 'plan', 'action', 'outcome']) {
  ajv.addSchema(await load(`schemas/v2/${name}.schema.json`));
}
const validateInput = ajv.compile(await load('happyrobot/crisis-command/input.schema.json'));
const validateContext = ajv.compile(await load('happyrobot/crisis-command/context.schema.json'));
for (const pack of ['dana', 'wildfire']) {
  const input = await load(`happyrobot/crisis-command/fixtures/${pack}-input.json`);
  const snapshot = await load(`happyrobot/crisis-command/fixtures/${pack}-snapshot.json`);
  const context = { dispatch_id: input.dispatch_id, trigger_event: input.event, ...snapshot };
  if (!validateInput(input)) throw new Error(`${pack} input: ${ajv.errorsText(validateInput.errors)}`);
  if (!validateContext(context)) throw new Error(`${pack} context: ${ajv.errorsText(validateContext.errors)}`);
  if ('hidden_truth' in snapshot) throw new Error(`${pack}: hidden truth leaked`);
  console.log(`PASS crisis-command ${snapshot.run.pack_id}`);
}
NODE
rg -n -i 'paiporta|catarroja|puente|inundaci|dana|pinar norte|wildfire' \
  happyrobot/crisis-command/*.prompt.md \
  && exit 1 || true
rg -n 'hidden_truth' happyrobot/crisis-command/fixtures && exit 1 || true
```

Expected:

```text
PASS dana-demo: Signal → Incident → Plan → Action → Outcome
PASS wildfire-demo: Signal → Incident → Plan → Action → Outcome
PASS crisis-command dana-demo
PASS crisis-command wildfire-demo
```

Los dos `rg` negativos no imprimen coincidencias y el bloque termina con código `0`.

### Task 5: Configurar y probar `crisis-command` en HappyRobot Platform

**Files:**

- Create: `happyrobot/crisis-command/platform-export.json`

- [ ] **Step 1: Crear workflow/version y grafo nativo**

Crear `crisis-command`, versión `crisis-command-2.0.0`, engine v3, entorno `development`:

```text
Incoming Hook/API Run Trigger: Command Input
  → HTTP Action: Get Snapshot
  → Native variable mapping: trigger event + flat snapshot context
  → AI Agent: Situation Analyst
  → AI Agent: Commander
  → HTTP/Webhook Action: Gateway replace_plan
```

`Get Snapshot` llama `{{GATEWAY_URL}}/api/snapshot?run_id={{run_id}}`. Su salida debe tener exactamente `{run,signals,incidents,plan,actions,outcomes,resources,events,outbox}`. El mapeo nativo añade solo `dispatch_id` y `trigger_event`; no añade estado inventado. Los dos agentes usan los prompts versionados. El último nodo hace `POST {{GATEWAY_URL}}/api/commands` con este envelope plano:

```json
{
  "command_id": "{{commander.output.command_id}}",
  "run_id": "{{context.run.run_id}}",
  "pack_id": "{{context.run.pack_id}}",
  "pack_version": "{{context.run.pack_version}}",
  "pack_digest": "{{context.run.pack_digest}}",
  "expected_state_version": "{{context.run.state_version}}",
  "actor": "happyrobot",
  "command_type": "replace_plan",
  "payload": {
    "incidents": "{{commander.output.incidents}}",
    "plan": "{{commander.output.plan}}",
    "actions": "{{commander.output.actions}}"
  },
  "causation_id": "{{context.trigger_event.event_id}}"
}
```

No añadir loops que reactiven Commander. El Event Router es responsable del dispatch y del `dirty`/debounce externo.

- [ ] **Step 2: Probar DANA e incendio aisladamente**

Run:

```bash
set -a && source ./.env && set +a
smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT
command_version_id="$(
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_COMMAND_WORKFLOW_ID/versions?page=1&page_size=100&sort=desc" \
  | jq -er '[.data[] | select(.name == "crisis-command-2.0.0")][0].id'
)"
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $HAPPYROBOT_KEY" \
  "$HAPPYROBOT_BASE_URL/versions/$command_version_id/nodes" > "$smoke_dir/nodes.json"
command_trigger_node_id="$(jq -er '[.data[] | select(.name == "Command Input")][0].id' "$smoke_dir/nodes.json")"
command_snapshot_node_id="$(jq -er '[.data[] | select(.name == "Get Snapshot")][0].id' "$smoke_dir/nodes.json")"
command_output_node_id="$(jq -er '[.data[] | select(.name == "Commander")][0].id' "$smoke_dir/nodes.json")"

for fixture in dana-input wildfire-input; do
  jq '{data: .}' "happyrobot/crisis-command/fixtures/${fixture}.json" \
    | curl --fail-with-body --silent --show-error -X PUT \
        -H "Authorization: Bearer $HAPPYROBOT_KEY" \
        -H 'Content-Type: application/json' --data-binary @- \
        "$HAPPYROBOT_BASE_URL/versions/$command_version_id/nodes/$command_trigger_node_id/custom-output" \
    | jq -e '.data.node_id != null'

  jq '{data: .}' "happyrobot/crisis-command/fixtures/${fixture%-input}-snapshot.json" \
    | curl --fail-with-body --silent --show-error -X PUT \
        -H "Authorization: Bearer $HAPPYROBOT_KEY" \
        -H 'Content-Type: application/json' --data-binary @- \
        "$HAPPYROBOT_BASE_URL/versions/$command_version_id/nodes/$command_snapshot_node_id/custom-output" \
    | jq -e '.data.node_id != null'

  curl --fail-with-body --silent --show-error -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' -d '{"environment":"development"}' \
    "$HAPPYROBOT_BASE_URL/versions/$command_version_id/nodes/$command_output_node_id/test" \
    | jq -e 'select(.data.error == null and (.data.data | type == "object")) | .data.data' \
    > "$smoke_dir/${fixture}-output.json"

  OUTPUT="$smoke_dir/${fixture}-output.json" \
  OUTPUT_SCHEMA="happyrobot/crisis-command/output.schema.json" \
  node --input-type=module <<'NODE'
import { readFile } from 'node:fs/promises';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
const load = async (path) => JSON.parse(await readFile(path, 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
for (const name of ['common', 'signal', 'incident', 'plan', 'action', 'outcome']) {
  ajv.addSchema(await load(`schemas/v2/${name}.schema.json`));
}
const validate = ajv.compile(await load(process.env.OUTPUT_SCHEMA));
const data = await load(process.env.OUTPUT);
if (!validate(data)) throw new Error(ajv.errorsText(validate.errors));
console.log(`PASS ${data.plan.pack_id}`);
NODE
done
```

Expected por fixture:

- test nativo `success`;
- el output es un objeto con al menos un Incident, un Plan y una Action;
- al menos una Action usa `status=pending_approval` y `approval_policy=human_required`;
- todas las identidades de pack coinciden con la entrada;
- ningún ID/zona de DANA aparece en la salida de incendio;
- el Gateway no se llama durante la prueba aislada del nodo Commander.

### Task 6: Versionar y configurar `crisis-response-coordination`

**Files:**

- Create: `happyrobot/crisis-response-coordination/input.schema.json`
- Create: `happyrobot/crisis-response-coordination/context.schema.json`
- Create: `happyrobot/crisis-response-coordination/output.schema.json`
- Create: `happyrobot/crisis-response-coordination/prompt.md`
- Create: `happyrobot/crisis-response-coordination/fixtures/dana-input.json`
- Create: `happyrobot/crisis-response-coordination/fixtures/wildfire-input.json`
- Create: `happyrobot/crisis-response-coordination/fixtures/dana-snapshot.json`
- Create: `happyrobot/crisis-response-coordination/fixtures/wildfire-snapshot.json`
- Create: `happyrobot/crisis-response-coordination/fixtures/isolated-observation.json`
- Create: `happyrobot/crisis-response-coordination/platform-export.json`

- [ ] **Step 1: Crear contratos de Coordination**

Escribir `happyrobot/crisis-response-coordination/input.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/crisis-response-coordination/input.schema.json",
  "type": "object",
  "required": ["dispatch_id", "run_id", "event"],
  "properties": {
    "dispatch_id": { "type": "string", "minLength": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "event": {
      "type": "object",
      "required": ["event_id", "run_id", "state_version", "event_type", "causation_id", "payload"],
      "properties": {
        "event_id": { "type": "integer", "minimum": 1 },
        "run_id": { "type": "string", "minLength": 1 },
        "state_version": { "type": "integer", "minimum": 1 },
        "event_type": { "const": "action.approved" },
        "causation_id": { "type": ["string", "null"] },
        "payload": {
          "type": "object",
          "required": ["action", "run_id", "pack_id", "pack_version", "pack_digest", "state_version", "correlation_id", "causation_id"],
          "properties": {
            "action": { "$ref": "https://valte.dev/schemas/v2/action.schema.json" },
            "run_id": { "type": "string", "minLength": 1 },
            "pack_id": { "type": "string", "minLength": 1 },
            "pack_version": { "type": "string", "minLength": 1 },
            "pack_digest": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
            "state_version": { "type": "integer", "minimum": 1 },
            "correlation_id": { "type": "string", "minLength": 1 },
            "causation_id": { "type": ["string", "null"] }
          },
          "additionalProperties": false
        }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

Escribir `happyrobot/crisis-response-coordination/context.schema.json` para el objeto plano posterior a la revalidación:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/crisis-response-coordination/context.schema.json",
  "type": "object",
  "required": ["dispatch_id", "trigger_event_id", "run", "action", "delivery_observation"],
  "properties": {
    "dispatch_id": { "type": "string", "minLength": 1 },
    "trigger_event_id": { "type": "integer", "minimum": 1 },
    "run": {
      "type": "object",
      "required": ["run_id", "pack_id", "pack_version", "pack_digest", "status", "scenario_now", "state_version"],
      "properties": {
        "run_id": { "type": "string" },
        "pack_id": { "type": "string" },
        "pack_version": { "type": "string" },
        "pack_digest": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
        "status": { "enum": ["ready", "running", "paused", "completed", "aborted"] },
        "scenario_now": { "type": "string", "format": "date-time" },
        "state_version": { "type": "integer", "minimum": 0 }
      }
    },
    "action": { "$ref": "https://valte.dev/schemas/v2/action.schema.json" },
    "delivery_observation": {
      "type": "object",
      "required": ["status", "summary", "observed_effects"],
      "properties": {
        "status": { "enum": ["success", "partial", "failed", "no_response", "unknown"] },
        "summary": { "type": "string", "minLength": 1 },
        "observed_effects": { "type": "object" }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

`output.schema.json` es:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/crisis-response-coordination/output.schema.json",
  "$ref": "https://valte.dev/schemas/v2/outcome.schema.json"
}
```

`dana-input.json` y `wildfire-input.json` reproducen el wrapper Router y guardan la Action v2 `approved` completa en `event.payload.action`, junto con identidad/state version. Sus snapshots usan exactamente `{run,signals,incidents,plan,actions,outcomes,resources,events,outbox}` y contienen esa misma Action en `actions`. `isolated-observation.json` es exactamente:

```json
{
  "status": "partial",
  "summary": "Isolated smoke only; no external effect was attempted.",
  "observed_effects": { "interaction_mode": "dry-run" }
}
```

DANA no comparte IDs con incendio y ninguna fixture contiene `hidden_truth`.

- [ ] **Step 2: Crear el prompt de Coordination**

Escribir `happyrobot/crisis-response-coordination/prompt.md`:

```markdown
# Role

You are `crisis-response-coordination`. Convert the result of one already-approved,
revalidated Action attempt into exactly one Outcome v2 JSON object. Output JSON only.

# Hard boundaries

- Proceed only when `run.status` is `running`, Action status is `approved`, and run/pack
  identity is exact. Otherwise return no effect and route to human review.
- Keep the supplied `dispatch_id` stable; use it as `attempt_id`.
- Do not invent delivery, acceptance or field success. Map only the supplied observation.
- `unknown` remains `unknown`; never retry or convert it automatically.
- New factual information becomes a later Signal; it does not rewrite this Outcome.
- Copy the v2 envelope and exact evidence references. Do not include hidden truth.
- External channel selection and recipient whitelisting are configured by the separate
  real-interaction extension. This base workflow remains safe for isolated dry-run testing.

# Output

Return one Outcome valid against `schemas/v2/outcome.schema.json`, with an `outcome_id`
stable for `dispatch_id`, no markdown and no extra keys.
```

- [ ] **Step 3: Configurar el workflow nativo**

Crear `crisis-response-coordination`, versión `crisis-response-coordination-2.0.0`, engine v3, entorno `development`:

```text
Incoming Hook/API Run Trigger: Coordination Input (action.approved)
  → HTTP Action: Get Snapshot
  → Condition: run active + Action still approved + exact pack
      ├─ false → stop without side effect
      └─ true  → Native value: Isolated Observation
                  → Native variable mapping: flat Coordination context
                  → AI Agent: Build Outcome
                  → HTTP/Webhook Action: Gateway record_outcome
```

`Get Snapshot` consume exactamente `{run,signals,incidents,plan,actions,outcomes,resources,events,outbox}`. La condición selecciona de `actions` el mismo `action_id` que `event.payload.action`, comprueba estado `approved`, run `running`, pack exacto y que `run.state_version >= event.state_version`. El mapeo entrega al agente solo `{dispatch_id,trigger_event_id,run,action,delivery_observation}`. El POST final a `{{GATEWAY_URL}}/api/commands` usa:

```json
{
  "command_id": "coordination:{{context.dispatch_id}}:outcome",
  "run_id": "{{context.run.run_id}}",
  "pack_id": "{{context.run.pack_id}}",
  "pack_version": "{{context.run.pack_version}}",
  "pack_digest": "{{context.run.pack_digest}}",
  "expected_state_version": "{{context.run.state_version}}",
  "actor": "happyrobot",
  "command_type": "record_outcome",
  "payload": { "outcome": "{{build_outcome.output}}" },
  "causation_id": "{{context.trigger_event_id}}"
}
```

No configurar todavía email, PSTN o Web Voice live; ese cambio pertenece al plan de interacción real.

- [ ] **Step 4: Probar las dos fixtures**

Run:

```bash
node --input-type=module <<'NODE'
import { readFile } from 'node:fs/promises';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
const load = async (path) => JSON.parse(await readFile(path, 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
for (const name of ['common', 'signal', 'incident', 'plan', 'action', 'outcome']) {
  ajv.addSchema(await load(`schemas/v2/${name}.schema.json`));
}
const validateInput = ajv.compile(await load('happyrobot/crisis-response-coordination/input.schema.json'));
const validateContext = ajv.compile(await load('happyrobot/crisis-response-coordination/context.schema.json'));
const observation = await load('happyrobot/crisis-response-coordination/fixtures/isolated-observation.json');
for (const pack of ['dana', 'wildfire']) {
  const input = await load(`happyrobot/crisis-response-coordination/fixtures/${pack}-input.json`);
  const snapshot = await load(`happyrobot/crisis-response-coordination/fixtures/${pack}-snapshot.json`);
  const context = {
    dispatch_id: input.dispatch_id,
    trigger_event_id: input.event.event_id,
    run: snapshot.run,
    action: snapshot.actions.find(({ action_id }) => action_id === input.event.payload.action.action_id),
    delivery_observation: observation
  };
  if (!validateInput(input)) throw new Error(`${pack} input: ${ajv.errorsText(validateInput.errors)}`);
  if (!validateContext(context)) throw new Error(`${pack} context: ${ajv.errorsText(validateContext.errors)}`);
  if ('hidden_truth' in snapshot) throw new Error(`${pack}: hidden truth leaked`);
  console.log(`PASS crisis-response-coordination ${snapshot.run.pack_id}`);
}
NODE

set -a && source ./.env && set +a
smoke_dir="$(mktemp -d)"
trap 'rm -rf "$smoke_dir"' EXIT
coordination_version_id="$(
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_COORDINATION_WORKFLOW_ID/versions?page=1&page_size=100&sort=desc" \
  | jq -er '[.data[] | select(.name == "crisis-response-coordination-2.0.0")][0].id'
)"
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $HAPPYROBOT_KEY" \
  "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/nodes" > "$smoke_dir/nodes.json"
coordination_trigger_node_id="$(jq -er '[.data[] | select(.name == "Coordination Input")][0].id' "$smoke_dir/nodes.json")"
coordination_snapshot_node_id="$(jq -er '[.data[] | select(.name == "Get Snapshot")][0].id' "$smoke_dir/nodes.json")"
coordination_observation_node_id="$(jq -er '[.data[] | select(.name == "Isolated Observation")][0].id' "$smoke_dir/nodes.json")"
coordination_output_node_id="$(jq -er '[.data[] | select(.name == "Build Outcome")][0].id' "$smoke_dir/nodes.json")"

for fixture in dana-input wildfire-input; do
  jq '{data: .}' "happyrobot/crisis-response-coordination/fixtures/${fixture}.json" \
    | curl --fail-with-body --silent --show-error -X PUT \
        -H "Authorization: Bearer $HAPPYROBOT_KEY" \
        -H 'Content-Type: application/json' --data-binary @- \
        "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/nodes/$coordination_trigger_node_id/custom-output" \
    | jq -e '.data.node_id != null'

  jq '{data: .}' "happyrobot/crisis-response-coordination/fixtures/${fixture%-input}-snapshot.json" \
    | curl --fail-with-body --silent --show-error -X PUT \
        -H "Authorization: Bearer $HAPPYROBOT_KEY" \
        -H 'Content-Type: application/json' --data-binary @- \
        "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/nodes/$coordination_snapshot_node_id/custom-output" \
    | jq -e '.data.node_id != null'

  jq '{data: .}' happyrobot/crisis-response-coordination/fixtures/isolated-observation.json \
    | curl --fail-with-body --silent --show-error -X PUT \
        -H "Authorization: Bearer $HAPPYROBOT_KEY" \
        -H 'Content-Type: application/json' --data-binary @- \
        "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/nodes/$coordination_observation_node_id/custom-output" \
    | jq -e '.data.node_id != null'

  curl --fail-with-body --silent --show-error -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' -d '{"environment":"development"}' \
    "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/nodes/$coordination_output_node_id/test" \
    | jq -e 'select(.data.error == null and (.data.data | type == "object")) | .data.data' \
    > "$smoke_dir/${fixture}-output.json"

  OUTPUT="$smoke_dir/${fixture}-output.json" \
  OUTPUT_SCHEMA="happyrobot/crisis-response-coordination/output.schema.json" \
  node --input-type=module <<'NODE'
import { readFile } from 'node:fs/promises';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
const load = async (path) => JSON.parse(await readFile(path, 'utf8'));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
for (const name of ['common', 'signal', 'incident', 'plan', 'action', 'outcome']) {
  ajv.addSchema(await load(`schemas/v2/${name}.schema.json`));
}
const validate = ajv.compile(await load(process.env.OUTPUT_SCHEMA));
const data = await load(process.env.OUTPUT);
if (!validate(data)) throw new Error(ajv.errorsText(validate.errors));
console.log(`PASS ${data.pack_id}`);
NODE
done
```

Expected: ambos tests devuelven un Outcome v2, `attempt_id` coincide con `dispatch_id`, Action/Outcome pertenecen al mismo run/pack y no se crea ningún contacto externo.

### Task 7: Ejecutar smoke global, exportar y publicar solo development

**Files:**

- Modify: `happyrobot/crisis-intake/platform-export.json`
- Modify: `happyrobot/crisis-command/platform-export.json`
- Modify: `happyrobot/crisis-response-coordination/platform-export.json`

- [ ] **Step 1: Ejecutar `test-all` nativo para las tres versiones**

Run:

```bash
set -a && source ./.env && set +a
resolve_version_id() {
  local workflow_id="$1"
  local version_name="$2"
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/workflows/$workflow_id/versions?page=1&page_size=100&sort=desc" \
  | jq -er --arg name "$version_name" '[.data[] | select(.name == $name)][0].id'
}
intake_version_id="$(resolve_version_id "$HAPPYROBOT_INTAKE_WORKFLOW_ID" 'crisis-intake-2.0.0')"
command_version_id="$(resolve_version_id "$HAPPYROBOT_COMMAND_WORKFLOW_ID" 'crisis-command-2.0.0')"
coordination_version_id="$(resolve_version_id "$HAPPYROBOT_COORDINATION_WORKFLOW_ID" 'crisis-response-coordination-2.0.0')"

for version_id in "$intake_version_id" "$command_version_id" "$coordination_version_id"; do
  curl --fail-with-body --silent --show-error \
    -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' \
    -d '{"environment":"development"}' \
    "$HAPPYROBOT_BASE_URL/versions/$version_id/test-all" \
    | jq -e '.results | length > 0 and all(.status == "success")'
done
```

Expected:

```text
true
true
true
```

- [ ] **Step 2: Publicar las versiones desde Platform UI en `development`**

Publicar solo después de que todos los nodos estén completos. Si existe otra versión live, seleccionar explícitamente la versión que se reemplaza; no usar `force` sin comprobar el ID.

Expected: cada workflow muestra una única versión live en `development`; ninguna versión de `production` cambia.

- [ ] **Step 3: Exportar configuración saneada una vez, sin crear un sincronizador**

Para cada versión, descargar metadatos y nodos con GET, combinar en `{version,nodes}`, y sanear recursivamente claves cuyo nombre contenga `secret`, `token`, `password`, `api_key`, `credential` o `webhook_url`. No exportar `/variables`.

Run:

```bash
set -a && source ./.env && set +a
export_dir="$(mktemp -d)"
trap 'rm -rf "$export_dir"' EXIT
resolve_version_id() {
  local workflow_id="$1"
  local version_name="$2"
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/workflows/$workflow_id/versions?page=1&page_size=100&sort=desc" \
  | jq -er --arg name "$version_name" '[.data[] | select(.name == $name)][0].id'
}
intake_version_id="$(resolve_version_id "$HAPPYROBOT_INTAKE_WORKFLOW_ID" 'crisis-intake-2.0.0')"
command_version_id="$(resolve_version_id "$HAPPYROBOT_COMMAND_WORKFLOW_ID" 'crisis-command-2.0.0')"
coordination_version_id="$(resolve_version_id "$HAPPYROBOT_COORDINATION_WORKFLOW_ID" 'crisis-response-coordination-2.0.0')"

while IFS='|' read -r version_id target; do
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/versions/$version_id/" > "$export_dir/version.json"
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/versions/$version_id/nodes" > "$export_dir/nodes.json"

  jq -S -s '
    def scrub:
      walk(if type == "object" then
        with_entries(
          if (.key | test("secret|token|password|api_key|credential|webhook_url"; "i"))
          then .value = "<redacted>" else . end
        )
      else . end);
    {version: (.[0].data // .[0]), nodes: (.[1].data // .[1])} | scrub
  ' "$export_dir/version.json" "$export_dir/nodes.json" > "$target"
done <<EOF
$intake_version_id|happyrobot/crisis-intake/platform-export.json
$command_version_id|happyrobot/crisis-command/platform-export.json
$coordination_version_id|happyrobot/crisis-response-coordination/platform-export.json
EOF
```

Expected: se crean tres JSON con claves raíz `version` y `nodes`; no se imprime ningún valor remoto.

Comprobar cada export:

```bash
jq -e '.version != null and (.nodes | type == "array")' happyrobot/*/platform-export.json
rg -n -i 'bearer |api[_-]?key|password|token|secret|@' happyrobot/*/platform-export.json \
  && exit 1 || true
```

Expected: tres líneas `true`; el escaneo de secretos no imprime coincidencias.

- [ ] **Step 4: Puerta final del frente**

Run:

```bash
npm run contracts:check
rg -n -i 'paiporta|catarroja|dana|inundaci|pinar norte|wildfire' happyrobot/**/*.prompt.md \
  && exit 1 || true
rg -n 'hidden_truth' happyrobot --glob '!**/README.md' && exit 1 || true
git diff --check
git status --short -- \
  happyrobot/README.md \
  happyrobot/crisis-intake \
  happyrobot/crisis-command \
  happyrobot/crisis-response-coordination
```

Expected:

- `npm run contracts:check` muestra PASS para DANA e incendio;
- los dos escaneos negativos no encuentran contenido;
- `git diff --check` no imprime nada;
- el `git status` acotado lista únicamente los artefactos bajo `happyrobot/` de este plan;
- el agente entrega rutas y resultados al coordinador sin hacer commit.
