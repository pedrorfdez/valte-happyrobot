# Controlled Real Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir a `crisis-response-coordination` una interacción externa real, controlada y trazable mediante Web Voice, con email nativo como fallback, destinatarios en whitelist, modo dry-run y un único Outcome correlacionado por `dispatch_id`.

**Architecture:** Se forkea la versión `development` del workflow existente y se añaden Conditions, Web Voice/Voice Agent, Email y acciones HTTP nativas de HappyRobot; no se crea un cuarto workflow ni un servicio de mensajería propio. Un sobre de dispatch inmutable alimenta dry-run y live, y toda respuesta/callback se convierte en `record_outcome` idempotente a través del Gateway.

**Tech Stack:** HappyRobot Web Voice y Email nativos, HappyRobot Platform/API v2 EU, State Gateway REST, JSON Schema 2020-12, `curl`/`jq` para smoke checks manuales.

---

## 0. Restricciones y precondiciones

- No TDD ni framework de tests; solo smoke checks dry-run, live controlado e idempotencia.
- No código de envío de voz/email. Los efectos externos usan nodos e integraciones nativas de HappyRobot.
- No crear un workflow adicional. Extender una nueva versión de `crisis-response-coordination`.
- No escribir directamente en Supabase y no guardar estado de callback en archivos locales.
- No usar PSTN salvo que el organizador confirme que ya existe número/credential operativo. No comprar, aprovisionar ni verificar un número en este frente.
- Web Voice es el canal live principal. Email es el fallback declarado. El dashboard/registro es la degradación sin efecto externo.
- Todo mensaje hablado o escrito empieza por `SIMULACIÓN —`.
- Solo destinatarios controlados y presentes en whitelist. Ningún contacto real se versiona en Git.
- `dry-run` es el modo por defecto y conserva el mismo dispatch payload que live sin abrir sesión de voz ni enviar email.
- `unknown` no se reintenta. Un fallo conocido sin efecto puede cambiar al fallback una sola vez conservando `dispatch_id` y creando un `attempt_id` de canal distinto.
- No hacer commits. El coordinador integra y crea el commit de la ola.
- Modificar solo `happyrobot/integrations/**`, `examples/real-interaction/**` y `docs/demo-contacts.md`.

Precondiciones de integración:

```text
crisis-response-coordination existe y está publicado en development
GET  $GATEWAY_URL/api/snapshot?run_id=<id> funciona
POST $GATEWAY_URL/api/commands acepta record_outcome de forma idempotente
action.approved llega con Action v2, state_version y dispatch_id estable
```

Variables locales/plataforma requeridas:

```text
HAPPYROBOT_KEY
HAPPYROBOT_BASE_URL=https://platform.eu.happyrobot.ai/api/v2
HAPPYROBOT_ENV=development
GATEWAY_URL
HAPPYROBOT_COORDINATION_WORKFLOW_ID
REAL_INTERACTION_TRIGGER_NODE_ID
REAL_INTERACTION_OUTPUT_NODE_ID
DEMO_INTERACTION_MODE=dry-run|web_voice|email|pstn
DEMO_ALLOWED_CONTACT_IDS
DEMO_CONTACT_ID
DEMO_CONTACT_NAME
DEMO_CONTACT_EMAIL             # solo variable oculta de Platform/.env
DEMO_CONTACT_PHONE             # opcional; no requerido por el camino base
```

## 1. Mapa de archivos

| Ruta | Responsabilidad |
| --- | --- |
| `happyrobot/integrations/README.md` | Topología nativa, mapeo de variables, setup y operación. |
| `happyrobot/integrations/channel-policy.json` | Prioridad de canal, dry-run, fallback y reglas de seguridad. |
| `happyrobot/integrations/dispatch.schema.json` | Sobre inmutable que comparten dry-run, Web Voice y email. |
| `happyrobot/integrations/callback.schema.json` | Callback normalizado y correlacionado por `dispatch_id`. |
| `happyrobot/integrations/platform-export.json` | Export saneado de la versión live-interaction del workflow. |
| `examples/real-interaction/README.md` | Comandos reproducibles de dry-run, Web Voice, email e idempotencia. |
| `examples/real-interaction/approved-action.json` | Wrapper Router `action.approved` con Action v2 completa. |
| `examples/real-interaction/dispatch.json` | Dispatch interno ya renderizado; sin datos personales. |
| `examples/real-interaction/callback-success.json` | Callback positivo de ejemplo. |
| `examples/real-interaction/callback-unknown.json` | Callback incierto que no admite reintento ciego. |
| `examples/real-interaction/record-outcome-command.json` | Comando Gateway idempotente derivado del callback. |
| `docs/demo-contacts.md` | Procedimiento de whitelist y checklist humana; sin direcciones reales. |

No crear scripts de envío ni modificar el export del plan de workflows; esta versión nueva se exporta bajo `happyrobot/integrations/`.

### Task 1: Congelar política de canales y contactos

**Files:**

- Create: `happyrobot/integrations/channel-policy.json`
- Create: `docs/demo-contacts.md`

- [ ] **Step 1: Crear la política declarativa**

Escribir `happyrobot/integrations/channel-policy.json`:

```json
{
  "policy_version": "1.0.0",
  "environment": "development",
  "default_interaction_mode": "dry-run",
  "message_prefix": "SIMULACIÓN — ",
  "channels": [
    {
      "id": "web_voice",
      "priority": 1,
      "enabled_when": "DEMO_INTERACTION_MODE=web_voice",
      "requires": ["DEMO_CONTACT_ID"]
    },
    {
      "id": "email",
      "priority": 2,
      "enabled_when": "DEMO_INTERACTION_MODE=email OR web_voice_unavailable_in_preflight",
      "requires": ["DEMO_CONTACT_ID", "DEMO_CONTACT_EMAIL"]
    },
    {
      "id": "pstn",
      "priority": 3,
      "enabled_when": "existing_verified_credential_and_explicit_operator_selection",
      "requires": ["DEMO_CONTACT_ID", "DEMO_CONTACT_PHONE"],
      "optional": true
    }
  ],
  "safety": {
    "allowlist_variable": "DEMO_ALLOWED_CONTACT_IDS",
    "reject_unlisted_recipient": true,
    "preflight_fallback_max": 1,
    "retry_unknown": false,
    "require_approved_action": true,
    "require_active_run": true,
    "require_exact_pack_identity": true
  }
}
```

- [ ] **Step 2: Crear el registro operativo de contactos sin PII**

Escribir `docs/demo-contacts.md` con:

```markdown
# Demo contact allowlist

This file never contains a real email address, phone number, token or credential.

## Logical contacts

| Contact ID | Purpose | Allowed channels | Owner confirmation |
| --- | --- | --- | --- |
| `demo-field-lead` | Controlled mission recipient | Web Voice, email | Required before every live run |

## Before enabling live mode

- [ ] The recipient is present and has explicitly consented to this demo interaction.
- [ ] `DEMO_CONTACT_ID=demo-field-lead`.
- [ ] `DEMO_ALLOWED_CONTACT_IDS` contains exactly `demo-field-lead`.
- [ ] The real address exists only in `.env` and a hidden HappyRobot development variable.
- [ ] The operator reads the rendered message before changing `DEMO_INTERACTION_MODE`.
- [ ] The run and Action are still active/approved in the latest Gateway snapshot.
- [ ] The spoken/written message begins with `SIMULACIÓN —`.

## Stop conditions

Stay in `dry-run` when consent, whitelist, current approval, pack identity or channel status is
uncertain. Set an uncertain external effect to `unknown`; do not retry it automatically.
```

- [ ] **Step 3: Smoke check de política**

Run:

```bash
jq -e '
  .default_interaction_mode == "dry-run"
  and .message_prefix == "SIMULACIÓN — "
  and .channels[0].id == "web_voice"
  and .channels[1].id == "email"
  and .safety.retry_unknown == false
' happyrobot/integrations/channel-policy.json
rg -n -i 'https?://|[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}|\+[0-9]{7,}' docs/demo-contacts.md \
  && exit 1 || true
```

Expected: `true`; el escaneo de PII no imprime coincidencias.

### Task 2: Definir dispatch, callback y ejemplos idempotentes

**Files:**

- Create: `happyrobot/integrations/dispatch.schema.json`
- Create: `happyrobot/integrations/callback.schema.json`
- Create: `examples/real-interaction/approved-action.json`
- Create: `examples/real-interaction/dispatch.json`
- Create: `examples/real-interaction/callback-success.json`
- Create: `examples/real-interaction/callback-unknown.json`
- Create: `examples/real-interaction/record-outcome-command.json`

- [ ] **Step 1: Crear el contrato de dispatch**

Escribir `happyrobot/integrations/dispatch.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/integrations/dispatch.schema.json",
  "type": "object",
  "required": ["dispatch_id", "run_id", "pack_id", "pack_version", "pack_digest", "state_version", "action_id", "interaction_mode", "recipient", "message"],
  "properties": {
    "dispatch_id": { "type": "string", "minLength": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "pack_id": { "type": "string", "minLength": 1 },
    "pack_version": { "type": "string", "minLength": 1 },
    "pack_digest": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
    "state_version": { "type": "integer", "minimum": 0 },
    "action_id": { "type": "string", "minLength": 1 },
    "interaction_mode": { "enum": ["dry-run", "web_voice", "email", "pstn"] },
    "recipient": {
      "type": "object",
      "required": ["contact_id", "display_name"],
      "properties": {
        "contact_id": { "type": "string", "minLength": 1 },
        "display_name": { "type": "string", "minLength": 1 }
      },
      "additionalProperties": false
    },
    "message": {
      "type": "object",
      "required": ["prefix", "subject", "body", "requested_response"],
      "properties": {
        "prefix": { "const": "SIMULACIÓN — " },
        "subject": { "type": "string", "minLength": 1 },
        "body": { "type": "string", "minLength": 1 },
        "requested_response": { "enum": ["accept_or_reject", "acknowledge"] }
      },
      "additionalProperties": false
    }
  },
  "additionalProperties": false
}
```

- [ ] **Step 2: Crear el contrato de callback**

Escribir `happyrobot/integrations/callback.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/happyrobot/integrations/callback.schema.json",
  "type": "object",
  "required": ["provider_event_id", "dispatch_id", "run_id", "action_id", "channel", "status", "received_at", "summary", "observed_effects"],
  "properties": {
    "provider_event_id": { "type": "string", "minLength": 1 },
    "dispatch_id": { "type": "string", "minLength": 1 },
    "run_id": { "type": "string", "minLength": 1 },
    "action_id": { "type": "string", "minLength": 1 },
    "channel": { "enum": ["dry-run", "web_voice", "email", "pstn"] },
    "status": { "enum": ["success", "partial", "failed", "no_response", "unknown"] },
    "received_at": { "type": "string", "format": "date-time" },
    "summary": { "type": "string", "minLength": 1 },
    "observed_effects": { "type": "object" }
  },
  "additionalProperties": false
}
```

- [ ] **Step 3: Crear ejemplos concretos**

`approved-action.json` reproduce el wrapper Router `{dispatch_id,run_id,event}`. `event.event_type` es `action.approved`; `event.payload` contiene la Action v2 `approved` completa, `run_id`, `pack_id=wildfire-demo`, `pack_version=1.0.0`, digest de 64 `d`, `state_version=7`, `correlation_id` y `causation_id`. No incluye `hidden_truth`, email ni teléfono.

`dispatch.json` contiene el dispatch interno para `run-wildfire-demo`, la misma identidad, `action_id=act-demo-contact-001`, `dispatch_id=dispatch-demo-001`, `interaction_mode=dry-run`, recipient `demo-field-lead` y un mensaje con `prefix="SIMULACIÓN — "`. Este objeto es la salida esperada de `Build Dispatch Envelope` y valida `dispatch.schema.json`.

`callback-success.json` usa `provider_event_id: voice-event-demo-001`, el mismo dispatch/run/action, canal `web_voice`, estado `success`, y `observed_effects.accepted: true`.

`callback-unknown.json` usa otro `provider_event_id`, el mismo dispatch/run/action, canal `email`, estado `unknown`, y `observed_effects.delivery_confirmation: "unavailable"`.

`record-outcome-command.json` usa:

```json
{
  "command_id": "callback:voice-event-demo-001",
  "run_id": "run-wildfire-demo",
  "pack_id": "wildfire-demo",
  "pack_version": "1.0.0",
  "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "expected_state_version": 7,
  "actor": "happyrobot",
  "command_type": "record_outcome",
  "payload": {
    "outcome": {
      "contract_version": "2.0.0",
      "run_id": "run-wildfire-demo",
      "pack_id": "wildfire-demo",
      "pack_version": "1.0.0",
      "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      "scenario_at": "2026-09-19T12:00:00Z",
      "received_at": "2026-09-19T12:00:05Z",
      "correlation_id": "run-wildfire-demo",
      "causation_id": "dispatch-demo-001",
      "outcome_id": "outcome-dispatch-demo-001",
      "action_id": "act-demo-contact-001",
      "attempt_id": "dispatch-demo-001:web_voice:1",
      "status": "success",
      "summary": "Controlled demo recipient accepted the simulated mission.",
      "observed_effects": { "accepted": true },
      "evidence": []
    }
  },
  "causation_id": "dispatch-demo-001"
}
```

- [ ] **Step 4: Validar los contratos sin framework**

Run:

```bash
node --input-type=module <<'NODE'
import { readFile } from 'node:fs/promises';
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
for (const name of ['common', 'signal', 'incident', 'plan', 'action', 'outcome']) {
  ajv.addSchema(JSON.parse(await readFile(`schemas/v2/${name}.schema.json`, 'utf8')));
}
for (const [schemaPath, fixtures] of [
  ['happyrobot/integrations/dispatch.schema.json', ['examples/real-interaction/dispatch.json']],
  ['happyrobot/integrations/callback.schema.json', ['examples/real-interaction/callback-success.json', 'examples/real-interaction/callback-unknown.json']]
]) {
  const validate = ajv.compile(JSON.parse(await readFile(schemaPath, 'utf8')));
  for (const fixture of fixtures) {
    const data = JSON.parse(await readFile(fixture, 'utf8'));
    if (!validate(data)) throw new Error(`${fixture}: ${ajv.errorsText(validate.errors)}`);
    console.log(`PASS ${fixture}`);
  }
}
const validateRouterInput = ajv.compile(JSON.parse(await readFile(
  'happyrobot/crisis-response-coordination/input.schema.json', 'utf8'
)));
const routerInput = JSON.parse(await readFile('examples/real-interaction/approved-action.json', 'utf8'));
if (!validateRouterInput(routerInput)) {
  throw new Error(`approved-action.json: ${ajv.errorsText(validateRouterInput.errors)}`);
}
console.log('PASS examples/real-interaction/approved-action.json');
NODE
```

Expected: cuatro líneas `PASS`, una por fixture.

### Task 3: Documentar y configurar la extensión nativa de Coordination

**Files:**

- Create: `happyrobot/integrations/README.md`
- Create: `happyrobot/integrations/platform-export.json`

- [ ] **Step 1: Forkear una versión sin tocar la versión base**

En Platform, abrir el workflow identificado por `HAPPYROBOT_COORDINATION_WORKFLOW_ID`, forkear la versión base a `crisis-response-coordination-real-interaction-1.0.0`, engine v3, `development`. El ID de versión se resuelve por nombre mediante la API en los smoke checks; no crear otro alias compartido.

Expected: la versión aislada del frente anterior sigue disponible y la versión nueva está editable.

- [ ] **Step 2: Configurar variables nativas por entorno**

En workflow variables de `development`:

- `GATEWAY_URL`: URL del Gateway, visible;
- `DEMO_INTERACTION_MODE`: `dry-run`, visible;
- `DEMO_ALLOWED_CONTACT_IDS`: `demo-field-lead`, visible;
- `DEMO_CONTACT_ID`: `demo-field-lead`, visible;
- `DEMO_CONTACT_NAME`: alias de demo, visible;
- `DEMO_CONTACT_EMAIL`: dirección consentida, oculta;
- `DEMO_CONTACT_PHONE`: solo si ya existe PSTN, oculta.

No exportar valores de `/variables` ni copiar direcciones a configuración versionada.

- [ ] **Step 3: Añadir la topología nativa**

Después de la revalidación de snapshot/Action existente, configurar:

```text
Build Dispatch Envelope
  → Condition: contact_id is allowlisted AND message prefix is SIMULACIÓN
      ├─ false → Stop + needs_human_review (no effect)
      └─ true
          → Condition: DEMO_INTERACTION_MODE
              ├─ dry-run   → Render Dispatch Only → Build dry-run callback
              ├─ web_voice → Voice Agent session → Normalize voice callback
              ├─ email     → Native Email node → Normalize delivery callback
              └─ pstn      → disabled unless an existing verified credential is selected
                    ↓
              HTTP Action: Gateway record_outcome
```

Usar el mismo objeto validado por `dispatch.schema.json` en las cuatro ramas. No regenerar `dispatch_id` al cambiar de canal. El primer y único canal realmente intentado usa `attempt_id={{dispatch_id}}:{{channel}}:1`; un fallo de disponibilidad en preflight puede seleccionar email antes de crear ese intento.

La rama Web Voice empieza toda locución con `SIMULACIÓN —`, lee misión/objetivo y pide aceptación o rechazo. La rama Email usa asunto y cuerpo con el mismo prefijo. La rama `dry-run` no ejecuta nodos Voice/Email y produce callback `partial` con `observed_effects.interaction_mode="dry-run"`. Un fallo de disponibilidad detectado en preflight selecciona email antes de crear un intento/Outcome de voz; así el dispatch de demo termina con un solo callback y un solo Outcome. Si ya hubo intento de voz y su efecto es incierto, no se ejecuta fallback.

El nodo final forma `command_id=callback:{{provider_event_id}}`, `command_type=record_outcome` y `payload.outcome` v2. Repetir el mismo callback conserva el mismo `command_id`.

- [ ] **Step 4: Escribir el runbook de integración**

`happyrobot/integrations/README.md` debe documentar:

1. preflight de snapshot, Action aprobada y whitelist;
2. cambio explícito entre `dry-run`, `web_voice`, `email` y `pstn`;
3. prohibición de fallback cuando el efecto es `unknown`;
4. mapeo `success|partial|failed|no_response|unknown` a Outcome homónimo;
5. creación de `attempt_id` por canal sin cambiar `dispatch_id`;
6. callback idempotente `callback:<provider_event_id>`;
7. procedimiento de export saneado y prohibición de exportar variables.

### Task 4: Crear el recorrido dry-run reproducible

**Files:**

- Create: `examples/real-interaction/README.md`

- [ ] **Step 1: Documentar el trigger dry-run**

Añadir a `examples/real-interaction/README.md` este comando:

```bash
set -a && source ./.env && set +a
: "${HAPPYROBOT_COORDINATION_WORKFLOW_ID:?missing workflow id}"
test "${DEMO_INTERACTION_MODE:-dry-run}" = dry-run

jq -n \
  --arg environment development \
  --slurpfile payload examples/real-interaction/approved-action.json \
  '{environment: $environment, payload: $payload[0]}' \
| curl --fail-with-body --silent --show-error \
    -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_COORDINATION_WORKFLOW_ID/runs" \
| jq -e '{run_id, status}'
```

Expected: objeto con `run_id` no vacío y `status` programado/ejecutándose; el run de Platform muestra la rama `dry-run`, no muestra invocación de Voice/Email y conserva `dispatch-demo-001`.

- [ ] **Step 2: Comprobar el payload sin efecto**

En Platform, abrir el run y verificar:

- `Build Dispatch Envelope` coincide campo por campo con `dispatch.json`;
- `SIMULACIÓN —` encabeza el mensaje;
- contacto allowlisted;
- callback `partial` contiene `interaction_mode="dry-run"`;
- ningún nodo de canal externo tiene output/usage.

Expected: run `completed`, cero voz/email consumidos y un solo Outcome dry-run para ese `dispatch_id`.

### Task 5: Ensayar Web Voice y el fallback de email

**Files:**

- Modify: `examples/real-interaction/README.md`
- Modify: `docs/demo-contacts.md`

- [ ] **Step 1: Ejecutar preflight humano**

Completar todos los checkboxes de `docs/demo-contacts.md`, releer snapshot y confirmar Action `approved`. Si algo no coincide, permanecer en `dry-run`.

Expected: consentimiento, whitelist, run, Action, pack y mensaje confirmados por el operador.

- [ ] **Step 2: Crear sesión Web Voice sin imprimir el token**

Cambiar `DEMO_INTERACTION_MODE=web_voice` en la variable `development` y crear token:

```bash
set -a && source ./.env && set +a
jq -n \
  --arg workflow_id "$HAPPYROBOT_COORDINATION_WORKFLOW_ID" \
  --slurpfile data examples/real-interaction/approved-action.json \
  '{workflow_id: $workflow_id, env: "development", ttl_seconds: 900, data: $data[0]}' \
| curl --fail-with-body --silent --show-error \
    -X POST \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    -H 'Content-Type: application/json' \
    --data-binary @- \
    "$HAPPYROBOT_BASE_URL/voice/tokens/" \
| jq -e '{run_id, room_name, has_token: (.token | length > 0), has_url: (.url | length > 0)}'
```

Expected: `has_token=true`, `has_url=true`; el token no aparece en la salida. Conectar mediante el Web Voice nativo/UI autorizado, o la superficie Web Voice del dashboard si ya está integrada.

- [ ] **Step 3: Completar una interacción controlada**

El receptor debe oír `SIMULACIÓN —` antes de la misión y responder aceptar o rechazar. Verificar en Platform que el callback conserva `dispatch_id` y genera un Outcome.

Expected: exactamente una conversación controlada; el run termina y el Gateway muestra un Outcome correlacionado.

- [ ] **Step 4: Probar email como fallback conocido**

Solo cuando Web Voice esté indisponible en preflight, antes de abrir una sesión o crear un intento, cambiar `DEMO_INTERACTION_MODE=email` y ejecutar el dispatch con el mismo `dispatch_id` y `attempt_id` terminado en `:email:1`. No ejecutar este paso después de iniciar Web Voice ni después de un resultado `unknown`.

Expected: un único email a la dirección oculta/allowlisted, asunto y cuerpo con `SIMULACIÓN —`, callback correlacionado y ningún envío adicional.

### Task 6: Probar idempotencia del callback y un único Outcome

**Files:**

- Modify: `examples/real-interaction/README.md`

- [ ] **Step 1: Enviar dos veces el mismo comando de callback**

Usar un run seeded/conectado cuya identidad coincida con `record-outcome-command.json`; actualizar solo `expected_state_version` antes del primer envío. Después:

```bash
set -a && source ./.env && set +a
for attempt in 1 2; do
  curl --fail-with-body --silent --show-error \
    -X POST \
    -H 'Content-Type: application/json' \
    --data-binary @examples/real-interaction/record-outcome-command.json \
    "$GATEWAY_URL/api/commands" \
    | jq -c '{command_id, state_version, result}'
done
```

Expected: las dos respuestas tienen el mismo `command_id`, `state_version` y `result`; la segunda no incrementa versión.

- [ ] **Step 2: Contar Outcomes correlacionados**

Run:

```bash
curl --fail-with-body --silent --show-error \
  "$GATEWAY_URL/api/snapshot?run_id=run-wildfire-demo" \
| jq -e '[.outcomes[] | select(.attempt_id | startswith("dispatch-demo-001:"))] | length == 1'
```

Expected: `true`.

- [ ] **Step 3: Comprobar el caso `unknown`**

Inyectar `callback-unknown.json` en el custom output del nodo de callback y ejecutar el nodo de normalización.

Expected: Outcome `status=unknown`, ninguna segunda invocación Voice/Email, ninguna liberación automática y route a revisión humana.

### Task 7: Exportar, revisar secretos y cerrar el frente

**Files:**

- Modify: `happyrobot/integrations/platform-export.json`

- [ ] **Step 1: Ejecutar `test-all` de la versión extendida**

Run:

```bash
set -a && source ./.env && set +a
coordination_version_id="$(
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_COORDINATION_WORKFLOW_ID/versions?page=1&page_size=100&sort=desc" \
  | jq -er '[.data[] | select(.name == "crisis-response-coordination-real-interaction-1.0.0")][0].id'
)"
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Authorization: Bearer $HAPPYROBOT_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"environment":"development"}' \
  "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/test-all" \
| jq -e '.results | length > 0 and all(.status == "success")'
```

Expected: `true`.

- [ ] **Step 2: Publicar solo la versión de `development` verificada**

Desde Platform UI, reemplazar explícitamente la versión live de Coordination en `development`. No tocar producción.

Expected: una sola versión live en development y la versión base sigue consultable en historial.

- [ ] **Step 3: Exportar metadatos/nodos saneados**

Resolver `coordination_version_id` por nombre como en Step 1, usar GET `/versions/$coordination_version_id/` y GET `/versions/$coordination_version_id/nodes`, y combinar ambos documentos sin consultar/exportar `/variables`.

Run:

```bash
set -a && source ./.env && set +a
export_dir="$(mktemp -d)"
trap 'rm -rf "$export_dir"' EXIT
coordination_version_id="$(
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer $HAPPYROBOT_KEY" \
    "$HAPPYROBOT_BASE_URL/workflows/$HAPPYROBOT_COORDINATION_WORKFLOW_ID/versions?page=1&page_size=100&sort=desc" \
  | jq -er '[.data[] | select(.name == "crisis-response-coordination-real-interaction-1.0.0")][0].id'
)"
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $HAPPYROBOT_KEY" \
  "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/" > "$export_dir/version.json"
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer $HAPPYROBOT_KEY" \
  "$HAPPYROBOT_BASE_URL/versions/$coordination_version_id/nodes" > "$export_dir/nodes.json"
jq -S -s '
  def scrub:
    walk(if type == "object" then
      with_entries(
        if (.key | test("secret|token|password|api_key|credential|webhook_url|email|phone"; "i"))
        then .value = "<redacted>" else . end
      )
    else . end);
  {version: (.[0].data // .[0]), nodes: (.[1].data // .[1])} | scrub
' "$export_dir/version.json" "$export_dir/nodes.json" \
  > happyrobot/integrations/platform-export.json
```

Expected: el archivo contiene `version` y `nodes`; no se imprime ningún valor remoto.

- [ ] **Step 4: Puerta final**

Run:

```bash
jq -e '.version != null and (.nodes | type == "array")' happyrobot/integrations/platform-export.json
rg -n -i 'bearer |api[_-]?key|password|token|secret|@[[:alnum:]]|\+[0-9]{7,}' \
  happyrobot/integrations examples/real-interaction docs/demo-contacts.md \
  && exit 1 || true
rg -n 'SIMULACIÓN —' \
  happyrobot/integrations/channel-policy.json \
  examples/real-interaction/dispatch.json
npm run contracts:check
git diff --check
git status --short -- \
  happyrobot/integrations \
  examples/real-interaction \
  docs/demo-contacts.md
```

Expected:

- export válido (`true`);
- escaneo de secretos/PII sin coincidencias;
- dos coincidencias de `SIMULACIÓN —`;
- contratos DANA/incendio continúan en PASS;
- `git diff --check` sin salida;
- `git status --short` lista únicamente `happyrobot/integrations/**`, `examples/real-interaction/**` y `docs/demo-contacts.md` de este frente;
- entregar al coordinador evidencia del dry-run, canal live/fallback usado, `dispatch_id`, Outcome único y smoke checks, sin hacer commit.
