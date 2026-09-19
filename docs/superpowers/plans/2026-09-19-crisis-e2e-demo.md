# Sequential DANA and Wildfire E2E Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar un runner reproducible y un guion live de 8–10 minutos que recorran DANA y después incendio a través de las interfaces públicas, demostrando contratos v2, los tres workflows, aprobación, Outcome, replanificación, idempotencia y aislamiento entre packs.

**Architecture:** Un único script Node.js sin framework ejecuta dos veces la misma función `runScenario(config)`. Cada ejecución espera primero a que el Scenario Controller conectado termine de escribir todos los comandos del timeline; solo entonces drena el Event Router, observa snapshots del Gateway, aprueba una Action, espera Outcome/replanificación y cierra el run con `abort_run`. Esta serialización evita que Controller y workflows intercalen escrituras contra la misma `state_version`; DANA e incendio solo difieren en el directorio del pack, el `run_id` y marcadores declarativos de aceptación.

**Tech Stack:** Node.js 24 ESM, `fetch`/`child_process`/`fs` nativos, Gateway HTTP v2, Scenario Controller, HappyRobot, JSON/NDJSON, Markdown

---

## Restricciones explícitas

- No TDD ni framework de tests; no añadir Vitest, Jest, Playwright, Mocha ni dependencias.
- Solo smoke checks de sintaxis, preflight conectado y el recorrido E2E real.
- Código mínimo: un runner ESM; no crear servidor mock, base de datos temporal ni duplicar el motor del Scenario Controller.
- Llamar únicamente a `GET /api/snapshot`, `POST /api/commands`, `POST /api/event-router` y al CLI público del Scenario Controller.
- No leer ni escribir tablas Supabase, no usar `DATABASE_URL` ni `SUPABASE_SERVICE_ROLE_KEY`.
- Los tres workflows y los contratos son los mismos en ambos recorridos. No crear ramas de lógica de negocio para DANA o incendio.
- DANA alcanza `aborted` mediante un comando de operador antes de iniciar incendio. Los dos runs y digests deben ser distintos.
- No drenar el Router, aprobar Actions ni ejecutar otra mutación mientras el Scenario Controller siga activo.
- La ruta normal usa efectos externos `dry-run`; el ensayo live controlado exige confirmación explícita y destinatarios en whitelist del frente de integraciones.
- Los artifacts no contienen claves, tokens, cabeceras Authorization, teléfonos, emails ni payloads crudos de callbacks.
- Este frente no modifica `schemas/v2/**`, packs, workflows, Gateway, Router o integraciones.
- Este frente no crea commits. El coordinador integra y hace el commit de la ola.

## Precondiciones y handshake exacto entre frentes

El coordinador no asigna este plan hasta superar la Puerta de Integración 1. Deben existir:

```text
scenario-packs/dana-demo/manifest.json
scenario-packs/dana-demo/hidden-truth.json
scenario-packs/wildfire-demo/manifest.json
scenario-packs/wildfire-demo/hidden-truth.json
scripts/scenario-controller.mjs
api/commands/
api/event-router/
api/snapshot/
happyrobot/crisis-intake/
happyrobot/crisis-command/
happyrobot/crisis-response-coordination/
```

El CLI público congelado que este plan consume es:

```bash
node scripts/scenario-controller.mjs \
  --pack <scenario-pack-directory> \
  --run-id <existing-run-id> \
  --gateway-url <gateway-origin> \
  --connected \
  --json
```

Expected del CLI: código `0` al terminar de emitir el timeline y una última línea JSON con `run_id`, `pack_id`, `pack_version`, `pack_digest`, `events_sent` y `status`. El exit `0` es la barrera de timeline finalizado; no cierra el run ni ejecuta workflows. Logs humanos van a stderr. Si el frente B congela nombres de flags distintos, el coordinador alinea este handshake una vez antes de implementar el runner; el frente E2E no añade un segundo controlador.

Los dos runs deben estar provisionados y sin datos de ejecuciones anteriores. El runner recibe sus IDs por flags, no los inventa:

```text
--dana-run <run-id>
--wildfire-run <run-id>
```

HappyRobot y la integración externa se configuran server-side. El runner nunca recibe `HAPPYROBOT_KEY` ni datos del destinatario.

## Interfaces congeladas usadas por el runner

```text
GET  /api/snapshot?run_id=<id>
POST /api/commands
POST /api/event-router
```

El command envelope es exactamente:

```json
{
  "command_id": "e2e-unique",
  "run_id": "run-id",
  "pack_id": "pack-id",
  "pack_version": "1.0.0",
  "pack_digest": "64-caracteres-hex",
  "expected_state_version": 3,
  "actor": "operator",
  "command_type": "approve_action",
  "payload": { "action_id": "action-id" },
  "causation_id": null
}
```

La aceptación contiene `command_id`, `state_version`, `result` y eventos. `version_conflict`, `pack_context_mismatch` y `action_not_in_active_pack` son errores de dominio que el runner debe distinguir de HTTP/transporte.

## Mapa de archivos

| Ruta | Acción | Responsabilidad única |
| --- | --- | --- |
| `scripts/e2e-demo.mjs` | Crear | CLI, recorrido común, aserciones, redacción y artifacts |
| `docs/demo-runbook.md` | Crear | Preflight, seguridad y guion live minuto a minuto |
| `artifacts/e2e/.gitkeep` | Crear | Mantener el directorio de resultados sin versionar resultados concretos |

No modificar `package.json`: el comando se ejecuta como `node scripts/e2e-demo.mjs` para mantener el incremento mínimo y no disputar un archivo compartido.

## Task 1: Definir CLI, configuración y preflight del runner

**Files:**

- Create: `scripts/e2e-demo.mjs`

- [ ] **Step 1: Importar solo APIs nativas y definir constantes**

Usar:

```js
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile, appendFile } from "node:fs/promises";
import { resolve } from "node:path";
```

Definir `POLL_MS=1000`, `ROUTER_MS=1500`, timeout por escenario `180000` ms y máximo de 300 snapshots por escenario. No usar waits bloqueantes; `delay(ms)` devuelve una Promise con `setTimeout`.

- [ ] **Step 2: Implementar parser de argumentos sin dependencia**

Aceptar exactamente:

```text
--gateway <origin>                  requerido salvo GATEWAY_URL
--dana-run <id>                    requerido salvo DANA_RUN_ID
--wildfire-run <id>                requerido salvo WILDFIRE_RUN_ID
--effects dry-run|controlled       default dry-run
--confirm-controlled-contact SIMULACION  requerido para controlled
--timeout-ms <n>                   default 180000
--artifacts-dir <path>             default artifacts/e2e
--preflight-only                   no inicia timelines
--help
```

Rechazar flags desconocidos, `danaRun === wildfireRun`, gateway sin `http:`/`https:`, timeout menor que 30 s y modo de efectos desconocido. `--help` imprime uso y termina `0`; argumentos inválidos terminan `2` sin hacer red.

- [ ] **Step 3: Mantener dos configuraciones declarativas con el mismo shape**

Crear `scenarioConfigs(args)` que devuelve:

```js
[
  {
    name: "dana",
    label: "DANA",
    packPath: "scenario-packs/dana-demo",
    runId: args.danaRun,
    forbiddenInNextRun: ["Paiporta", "Catarroja", "rescate acuático", "inundación"]
  },
  {
    name: "wildfire",
    label: "Incendio forestal",
    packPath: "scenario-packs/wildfire-demo",
    runId: args.wildfireRun,
    forbiddenInNextRun: []
  }
]
```

No añadir `if (config.name === ...)` dentro de `runScenario`. Las diferencias son solo datos de configuración y contenido del pack.

- [ ] **Step 4: Cargar y comprobar manifests**

`loadPack(config)` lee `manifest.json` y exige `pack_id` y `pack_version`. El digest autoritativo se toma del snapshot inmutable del run y debe tener 64 caracteres hex; si el manifest publica además `pack_digest`, exigir igualdad. El runner nunca inventa ni recalcula otra identidad del pack.

Verificar que los dos `pack_id` y digests son distintos. No cargar playbooks de un pack dentro del otro.

- [ ] **Step 5: Implementar cliente HTTP con errores legibles**

Crear:

```text
requestJson(method, path, body?)
getSnapshot(runId)
postCommand(command)
drainRouter(runId)
```

Aplicar `AbortSignal.timeout(10000)` a cada petición. Guardar status y body redactado en el artifact; nunca guardar headers. Un body no JSON debe producir error con método, URL, status y los primeros 200 caracteres redactados.

- [ ] **Step 6: Validar el snapshot inicial de ambos runs**

`preflightScenario(config, pack)` exige:

```text
snapshot.run.run_id === config.runId
snapshot.run.pack_id === manifest.pack_id
snapshot.run.pack_version === manifest.pack_version
snapshot.run.pack_digest === digest esperado
snapshot.run.status en ready|running
snapshot.run.state_version entero >= 0
signals/incidents/actions/outcomes vacíos para un run limpio
```

Si un run no está limpio, fallar con instrucción exacta de recrearlo o reseedearlo; no borrar ni abortar automáticamente datos ajenos.

- [ ] **Step 7: Smoke del CLI y preflight**

Run:

```bash
node --check scripts/e2e-demo.mjs
node scripts/e2e-demo.mjs --help
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --preflight-only
```

Expected:

```text
PASS config: DANA and wildfire use distinct runs and packs
PASS preflight: DANA <run-id> ready
PASS preflight: Incendio forestal <run-id> ready
```

Todos terminan con código `0`; no se crea ningún comando de mutación.

## Task 2: Crear artifacts redactados y aserciones comunes

**Files:**

- Modify: `scripts/e2e-demo.mjs`
- Create: `artifacts/e2e/.gitkeep`

- [ ] **Step 1: Crear un directorio único por ejecución**

Usar UTC segura para ruta:

```text
artifacts/e2e/YYYYMMDDTHHMMSSZ-dana-wildfire/
  summary.json
  summary.md
  dana/commands.ndjson
  dana/snapshots.ndjson
  dana/controller.stdout.log
  dana/controller.stderr.log
  wildfire/commands.ndjson
  wildfire/snapshots.ndjson
  wildfire/controller.stdout.log
  wildfire/controller.stderr.log
```

Los archivos se crean durante runtime. `artifacts/e2e/.gitkeep` queda vacío; no añadir resultados concretos al plan ni al commit del coordinador.

- [ ] **Step 2: Implementar redacción recursiva antes de escribir**

`redact(value)` sustituye con `"[REDACTED]"` cualquier valor cuya key coincida, sin distinguir mayúsculas, con:

```text
authorization|api[_-]?key|anon[_-]?key|service[_-]?role|secret|token|phone|email|raw[_-]?payload
```

También redacta strings con patrón Bearer/JWT y direcciones email. Conserva `pack_digest`, IDs de dominio, versiones, status y resúmenes operativos.

- [ ] **Step 3: Guardar NDJSON incremental y acotado**

`recordSnapshot` escribe una línea `{at, reason, state_version, snapshot:redact(snapshot)}` solo cuando cambia `state_version` o `reason` es `initial|timeline_complete|aborted|error`. `recordCommand` escribe request y response redactados. Si se alcanzan 300 snapshots, fallar con “snapshot limit exceeded” para evitar artifacts sin límite.

- [ ] **Step 4: Implementar aserciones sin librería**

Crear `assert(condition, code, details)` que lanza un `E2EAssertionError` con código estable. Implementar helpers:

```text
assertMonotonicVersions(history)
assertPackIdentity(snapshot, pack)
assertNoHiddenTruth(snapshot)
assertContractChain(snapshot)
assertWorkflowTrail(history)
collectPackSpecificIds(snapshot)
assertNoCrossPackValues(wildfireSnapshot, danaIds, danaTerms)
```

- [ ] **Step 5: Definir `assertContractChain()` con referencias exactas**

Exigir al menos una cadena completa:

```text
Incident.evidence contiene Signal signal_id + revision exactos
Plan.incident_ids contiene Incident.incident_id
Plan.action_ids contiene Action.action_id
Action.plan_id === Plan.plan_id
Action.incident_id === Incident.incident_id
Action.evidence contiene la revisión Signal usada
Outcome.action_id === Action.action_id
Outcome.evidence conserva evidencia Signal o Incident observable
```

Para todos los registros comprobar igualdad de `contract_version`, `run_id`, `pack_id`, `pack_version` y `pack_digest` con el run. Usar solo campos definidos en `schemas/v2/*.schema.json`.

- [ ] **Step 6: Definir `assertWorkflowTrail()` sobre estado observable**

Acumular durante el recorrido entradas visibles de `outbox`/eventos y exigir destinos o tipos equivalentes a:

```text
source_input.received → crisis-intake
signal.created|signal.revised → crisis-command
action.approved → crisis-response-coordination
outcome.recorded → crisis-command
```

Si el snapshot no conserva outbox entregado, el Gateway debe exponerlo en la proyección visible antes de implementar esta aserción; el runner no consulta tablas internas como workaround.

- [ ] **Step 7: Detectar verdad oculta sin registrarla**

`assertNoHiddenTruth` recorre keys y falla ante `hidden_truth`, `scenario_truth`, `ground_truth` o `truth_canary`. Puede leer el valor `canary` de `hidden-truth.json` solo en memoria para buscarlo en snapshots/artifacts, pero nunca lo imprime ni lo escribe.

- [ ] **Step 8: Smoke de redacción**

Run:

```bash
node scripts/e2e-demo.mjs --help >/tmp/valte-e2e-help.txt
rg -n 'HAPPYROBOT_KEY|SERVICE_ROLE|Authorization:|Bearer ' artifacts/e2e scripts/e2e-demo.mjs || true
```

Expected: el primer comando sale `0`; `rg` no encuentra valores de secretos ni código que escriba cabeceras. Borrar `/tmp/valte-e2e-help.txt` al terminar no es parte del repositorio.

## Task 3: Implementar el recorrido común Signal → Outcome → replanning

**Files:**

- Modify: `scripts/e2e-demo.mjs`

- [ ] **Step 1: Arrancar el Scenario Controller como proceso hijo**

`startController(config, args, artifactPaths)` usa `process.execPath` y argumentos separados, nunca una cadena de shell:

```js
spawn(process.execPath, [
  "scripts/scenario-controller.mjs",
  "--pack", config.packPath,
  "--run-id", config.runId,
  "--gateway-url", args.gateway,
  "--connected",
  "--json"
], { stdio: ["ignore", "pipe", "pipe"] });
```

Capturar stdout/stderr redactados. Un exit distinto de `0`, señal o timeout falla el escenario con las últimas 20 líneas, sin matar procesos no creados por el runner. Mientras este proceso esté activo, el runner puede hacer `GET /api/snapshot` diagnóstico, pero no llama a Router ni envía comandos.

- [ ] **Step 2: Esperar el Controller completo antes de permitir otra escritura**

`waitForController(controller, config)` debe esperar el exit `0` y analizar la última línea JSON. Exigir:

```text
summary.run_id === config.runId
summary.pack_id === manifest.pack_id
summary.pack_version === manifest.pack_version
summary.pack_digest === digest del snapshot inicial
summary.events_sent >= 1
typeof summary.status === "string" && summary.status.length > 0
```

Tras el exit, obtener y guardar un snapshot con reason `timeline_complete`. Solo a partir de ese momento puede invocarse `POST /api/event-router`. Esta barrera es obligatoria: las escrituras del timeline y las escrituras de los workflows nunca se solapan.

- [ ] **Step 3: Drenar Router y esperar evidencia/primer plan operable**

Implementar `waitForSnapshot(predicate, phase)` que, ahora que el Controller ya terminó, alterna:

```text
POST /api/event-router con {"run_id":"<id>"}
GET /api/snapshot?run_id=<id>
validar identidad, versión monotónica y ausencia de hidden truth
guardar únicamente versiones nuevas
evaluar el predicado de progreso
```

El Router puede responder que no hay trabajo y eso cuenta como éxito. Aplicar timeout global e incluir última versión, fase y conteos en cualquier error.

El primer checkpoint común exige:

```text
signals.length >= 1
incidents.length >= 1
snapshot.plan != null
actions.length >= 1
```

Guardar `initialPlanVersion` y comprobar que cada Action referencia el Plan/Incident del mismo pack. No comprobar vocabulario DANA dentro de la lógica común.

Al cumplirse este checkpoint, `waitForSnapshot` retorna y deja de invocar Router antes de construir la aprobación.

- [ ] **Step 4: Elegir una única aprobación de demo de forma determinista**

Filtrar `status === "pending_approval"` y `approval_policy === "human_required"`, ordenar por prioridad `P0..P3` y después `action_id`, y elegir la primera. Si no existe, fallar: el E2E debe demostrar aprobación humana. En modo `controlled`, exigir además la confirmación CLI exacta `SIMULACION`; la whitelist sigue siendo responsabilidad server-side.

- [ ] **Step 5: Aprobar y comprobar idempotencia con el mismo command_id**

Construir un command usando identidad/version del último snapshot, enviarlo dos veces sin cambiar un byte y exigir:

```text
response2.command_id === response1.command_id
response2.state_version === response1.state_version
response2.result deep-equal response1.result
```

Guardar ambos intercambios. La repetición no debe crear otra mutación, evento, intento u Outcome. Si la primera llamada da `version_conflict`, releer y reconstruir una vez con un `command_id` nuevo; no reutilizar un ID con body distinto.

- [ ] **Step 6: Esperar paso por Coordination y Outcome único**

Drenar Router y esperar un Outcome cuyo `action_id` sea el aprobado. Exigir `attempt_id`, status permitido por schema y un solo Outcome por pareja `(action_id, attempt_id)`. `dry-run` debe conservar exactamente la misma Action/dispatch/Outcome que `controlled`; solo cambia el adaptador de contacto server-side.

- [ ] **Step 7: Esperar la replanificación sin cerrar el run implícitamente**

Esperar que:

```text
plan.plan_version > initialPlanVersion
plan.supersedes_plan_id no sea null
el Outcome esté incorporado a la trazabilidad observable
el cambio dinámico del pack haya dejado de usar el estado/ruta/recurso anterior
```

La regla específica del cambio se evalúa por `evaluation-rules.json` del pack o por el resumen ya finalizado del Scenario Controller; no codificar una rama DANA/incendio en el runner. Al cumplir el predicado, detener el loop de Router antes de enviar otra mutación.

- [ ] **Step 8: Abortar explícitamente el run después de Outcome y replan**

Leer un snapshot fresco y construir un comando con:

```text
actor=operator
command_type=abort_run
payload={}
expected_state_version=<última versión observada>
```

Enviar el comando una vez, guardar request/response y esperar mediante `GET /api/snapshot` —sin volver a drenar Router— hasta `run.status === "aborted"`. Exigir que la versión aumente y que Signals, Incidents, Plan, Actions y Outcomes previamente observados sigan presentes. Si aparece `version_conflict`, releer y reintentar una sola vez con un `command_id` nuevo y body actualizado; nunca reutilizar el ID anterior.

- [ ] **Step 9: Implementar `runScenario(config, context)` como pipeline único**

Orden exacto:

```text
preflight → startController → wait controller exit/timeline_complete
→ drain Router → evidence/plan → choose approval → duplicate approval
→ Coordination/Outcome → replan → stop Router loop → abort_run
→ wait aborted snapshot → assertions → result
```

Devolver `{runId, pack, versions, approvedActionId, outcomeId, ids, abortedSnapshot, durationMs}`. No mantener estado global entre runs salvo el resultado DANA usado para comprobar aislamiento.

- [ ] **Step 10: Smoke de fallo rápido sin infraestructura**

Run:

```bash
node scripts/e2e-demo.mjs \
  --gateway http://127.0.0.1:1 \
  --dana-run dana-smoke \
  --wildfire-run fire-smoke \
  --preflight-only; test $? -ne 0
```

Expected: imprime un error de conexión acotado en menos de 15 s, no stack con secretos, y el `test` final sale `0` porque el runner falló como se esperaba.

## Task 4: Probar aborto explícito y aislamiento DANA → incendio

**Files:**

- Modify: `scripts/e2e-demo.mjs`

- [ ] **Step 1: Verificar que DANA está aborted antes de continuar**

`assertScenarioAborted(dana)` exige que el command log contenga un `abort_run` con `actor="operator"`, que su respuesta sea aceptada, que el último snapshot tenga `run.status === "aborted"` y que su `state_version` sea mayor que la versión del Plan replanificado. No enviar comandos adicionales a DANA.

- [ ] **Step 2: Ejecutar los dos rechazos cross-pack contra incendio**

Antes de iniciar su controller:

1. Enviar al run incendio un comando con identidad/digest DANA y exigir `pack_context_mismatch` sin incremento de versión.
2. Enviar `approve_action` al run incendio con identidad correcta de incendio pero `action_id` DANA y exigir `action_not_in_active_pack` sin incremento de versión.
3. Volver a leer el snapshot incendio todavía limpio y comprobar que no contiene IDs ni términos DANA.

No intentar reparar ni convertir esos rechazos en success.

- [ ] **Step 3: Ejecutar incendio con la misma función**

Llamar:

```js
const dana = await runScenario(configs[0], context);
await assertScenarioAborted(dana, context);
await assertCrossPackRejections(dana, configs[1], context);
const wildfire = await runScenario(configs[1], context);
```

No reinicializar módulos, cambiar prompts, cambiar workflow IDs ni limpiar memoria compartida de HappyRobot manualmente. El aislamiento debe proceder del nuevo `run_id` y snapshot del pack.

- [ ] **Step 4: Comprobar ausencia de contaminación**

Recopilar en DANA todos los valores de campos `run_id`, `signal_id`, `incident_id`, `plan_id`, `action_id`, `outcome_id`, `attempt_id`, `reservation_id`, `resource_id`, `entity_id` y `zone_id`. Exigir que ninguno aparezca como valor exacto en el snapshot/incidencias/actions/artifacts de incendio.

Buscar además, case-insensitive, los `forbiddenInNextRun` de la configuración DANA en el snapshot incendio. Excluir únicamente textos fijos del propio resumen E2E, no el estado operativo.

- [ ] **Step 5: Comprobar que no cambió el pipeline**

Comparar ambos resultados y exigir:

```text
mismos contract_version
mismas cinco clases Signal/Incident/Plan/Action/Outcome
misma secuencia de destinos Intake → Command → Coordination → Command
pack_id, pack_version, digest y run_id distintos
al menos una replanificación y un Outcome en cada run
```

- [ ] **Step 6: Generar resumen legible y exit code**

`summary.json` incluye resultado global, duración, rutas de artifacts, IDs, versiones y aserciones; `summary.md` incluye una tabla DANA/incendio y lista PASS/FAIL. En éxito imprimir:

```text
PASS DANA: Signal → Intake → Command → approval → Coordination → Outcome → replan
PASS DANA abort: operator abort_run → run.status=aborted
PASS wildfire: same contracts and workflows
PASS wildfire abort: operator abort_run → run.status=aborted
PASS isolation: no DANA IDs or terms in wildfire
Artifacts: artifacts/e2e/<run-directory>/summary.md
```

Exit `0` solo si todas las aserciones pasan. Ante fallo, terminar `1`, escribir summary parcial y conservar artifacts redactados.

## Task 5: Escribir el runbook live de 8–10 minutos

**Files:**

- Create: `docs/demo-runbook.md`

- [ ] **Step 1: Documentar seguridad y prerequisitos arriba del todo**

Abrir con:

```text
SIMULACIÓN. No contactar servicios de emergencia ni destinatarios fuera de whitelist.
Entorno HappyRobot: development.
Modo recomendado: dry-run.
Modo controlled: solo Web Voice/email ya verificado por el frente de integraciones.
```

Listar variables públicas/IDs necesarias y aclarar que `HAPPYROBOT_KEY`, service role y contactos nunca se pasan al runner.

- [ ] **Step 2: Añadir preflight de cinco comandos copiables**

```bash
npm ci
npm run contracts:check
node --check scripts/scenario-controller.mjs
node --check scripts/e2e-demo.mjs
node scripts/e2e-demo.mjs --gateway "$GATEWAY_URL" --dana-run "$DANA_RUN_ID" --wildfire-run "$WILDFIRE_RUN_ID" --preflight-only
```

Expected: dos PASS de contracts, ambos `node --check` silenciosos y dos runs limpios/distintos.

- [ ] **Step 3: Documentar comando dry-run autoritativo**

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --effects dry-run
```

Expected: las cinco líneas PASS de Task 4 y ruta a `summary.md`.

- [ ] **Step 4: Documentar activación controlada con doble barrera**

Solo tras verificar visualmente la whitelist y el prefijo `SIMULACIÓN`:

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --effects controlled \
  --confirm-controlled-contact SIMULACION
```

Si Web Voice falla, el adaptador usa email configurado; si ambos fallan, Outcome debe ser `failed|no_response|unknown`, nunca éxito fingido.

- [ ] **Step 5: Añadir guion minuto a minuto**

El runbook debe indicar qué decir, qué mostrar en `/ops` y qué verificar:

```text
00:00–01:00  Aviso SIMULACIÓN, arquitectura y snapshot DANA limpio.
01:00–02:00  Controller DANA emite todo el timeline y sale; Router aún no se drena.
02:00–03:00  Drenar Router: source input → Signal → Incidents y primer Plan.
03:00–04:00  Action high-impact pending_approval; aprobación humana.
04:00–05:00  Coordination dry-run/controlada → Outcome trazable.
05:00–06:15  Cambio dinámico ya emitido → nueva versión del Plan.
06:15–06:45  Operator envía abort_run; confirmar DANA aborted.
06:45–07:15  Probar aislamiento contra el run incendio todavía limpio.
07:15–08:00  Controller incendio emite su timeline completo sin drenar Router.
08:00–09:15  Drenar Router: mismo pipeline → Outcome → replan → abort_run.
09:15–10:00  Confirmar aislamiento y abrir summary.md/artifacts redactados.
```

- [ ] **Step 6: Añadir tabla de fallos y decisión en vivo**

Cubrir al menos:

| Fallo | Acción del presentador | Evidencia válida |
| --- | --- | --- |
| Realtime cae | continuar con polling y mostrar `degraded` | snapshot sigue avanzando |
| `version_conflict` | releer y decidir de nuevo | no hay mutación parcial |
| HappyRobot tarda | tras finalizar Controller, drenar Router hasta timeout | outbox queda visible |
| canal externo falla | permitir fallback | Outcome no finge success |
| efecto incierto | parar reintento | Outcome `unknown` |
| run no está limpio | detener demo y usar nuevos IDs | nunca borrar automáticamente |

- [ ] **Step 7: Añadir checklist final de aceptación**

```text
[ ] Controller terminó antes del primer drenaje de Router en cada pack.
[ ] DANA quedó aborted mediante abort_run de operator antes de arrancar incendio.
[ ] Ambos recorridos pasaron por los tres workflows.
[ ] El mismo command_id de aprobación devolvió el mismo resultado.
[ ] Incendio rechazó digest y Action DANA.
[ ] No hubo IDs, recursos ni términos DANA en incendio.
[ ] Cada Action llegó a Outcome y Plan posterior.
[ ] Incendio también quedó aborted después de su replanificación.
[ ] No hubo hidden truth ni secretos en snapshots/artifacts.
[ ] summary.md es legible y el proceso salió 0.
```

## Task 6: Ejecutar smoke final y entregar sin commit

**Files:**

- Verify: `scripts/e2e-demo.mjs`
- Verify: `docs/demo-runbook.md`
- Verify: `artifacts/e2e/.gitkeep`

- [ ] **Step 1: Validar contratos y sintaxis**

Run:

```bash
npm run contracts:check
node --check scripts/e2e-demo.mjs
node scripts/e2e-demo.mjs --help
```

Expected: dos cadenas contractuales PASS, `node --check` silencioso y usage completo con código `0`.

- [ ] **Step 2: Ejecutar recorrido conectado seguro**

Run:

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --effects dry-run
```

Expected: código `0`, PASS DANA, DANA abort, wildfire, wildfire abort e isolation; se crea un único directorio timestamped con `summary.json`, `summary.md`, commands, snapshots y logs redactados.

- [ ] **Step 3: Escanear secretos y artifacts**

Run:

```bash
latest_artifact="$(find artifacts/e2e -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
rg -n --hidden 'HAPPYROBOT_KEY|SUPABASE_SERVICE_ROLE_KEY|DATABASE_URL|Authorization: Bearer|your_api_key_here' "$latest_artifact" && exit 1 || true
node -e "const fs=require('node:fs'); const p=process.argv[1]; const s=JSON.parse(fs.readFileSync(p)); if(s.status!=='PASS') process.exit(1); console.log('PASS summary.json')" "$latest_artifact/summary.json"
```

Expected:

```text
PASS summary.json
```

El escaneo no imprime coincidencias.

- [ ] **Step 4: Verificar diff limitado sin hacer commit**

Run:

```bash
git diff --check -- scripts/e2e-demo.mjs docs/demo-runbook.md artifacts/e2e/.gitkeep
git status --short -- scripts/e2e-demo.mjs docs/demo-runbook.md artifacts/e2e/.gitkeep
```

Expected: `git diff --check` sin salida; status lista únicamente los tres paths del frente. Entregar al coordinador sin `git add` ni `git commit`.

## Contrato de entrega al coordinador

Reportar exactamente:

```text
E2E smoke: PASS|FAIL
DANA: <run_id> <pack_digest> versions <initial>→<aborted> outcome <id>
Wildfire: <run_id> <pack_digest> versions <initial>→<aborted> outcome <id>
Idempotency: PASS|FAIL
Abort after replan: DANA PASS|FAIL, Wildfire PASS|FAIL
Cross-pack rejections: pack_context_mismatch + action_not_in_active_pack
Isolation: PASS|FAIL
Artifacts: <path>/summary.md
Archivos: scripts/e2e-demo.mjs, docs/demo-runbook.md, artifacts/e2e/.gitkeep
Bloqueos: ninguno | request/response/error exactos
```

No modificar contratos compartidos para ocultar un fallo. Si el Router, Snapshot, Controller o workflow no expone lo congelado, conservar artifacts redactados, indicar la última `state_version` y devolver el bloqueo al propietario del frente.
