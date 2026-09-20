# Runbook live: DANA → incendio forestal

> **SIMULACIÓN. No contactar servicios de emergencia ni destinatarios fuera de whitelist.**
>
> Entorno HappyRobot: `development`. Modo recomendado: `dry-run`. Los modos live son explícitos: `web_voice`, `email` o `pstn`.

## 1. Preparación segura

Necesitas únicamente el origen público del Gateway y dos runs nuevos, provisionados con packs distintos:

```bash
set -a; source ./.env; set +a
: "${SUPABASE_URL:?SUPABASE_URL is required}"
VALTE_SUPABASE_ORIGIN="${SUPABASE_URL%/}"
export GATEWAY_URL="${VALTE_SUPABASE_ORIGIN}/functions/v1/gateway"
export DANA_RUN_ID="<run-dana-limpio>"
export WILDFIRE_RUN_ID="<run-incendio-limpio>"
```

Las credenciales de HappyRobot, la clave privilegiada de datos y los datos de contacto se configuran server-side y nunca se pasan al runner. Los runs deben estar limpios; si no lo están, crea o reseedea IDs nuevos. El runner nunca borra datos automáticamente.

## 2. Preflight, paso a paso

Reseed limpio obligatorio — evita contaminación DANA→wildfire (requisito `cross_pack_contamination`):

```bash
./scripts/reseed-runs.sh
# o manualmente:
# psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --file supabase/seed.sql
```

Luego ejecuta estos seis comandos antes de abrir la demo:

```bash
npm ci
npm run contracts:check
node --check scripts/scenario-controller.mjs
node --check scripts/e2e-demo.mjs
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=$DANA_RUN_ID" \
  | jq -e '.run.run_id == env.DANA_RUN_ID'
node scripts/e2e-demo.mjs --gateway "$GATEWAY_URL" --dana-run "$DANA_RUN_ID" --wildfire-run "$WILDFIRE_RUN_ID" --preflight-only
```

Resultado esperado:

1. `contracts:check` imprime los tres PASS contractuales.
2. Ambos `node --check` terminan silenciosamente con código `0`.
3. El `GET` del Gateway imprime `true`, confirmando el run DANA seleccionado antes de abrir el dashboard.
4. El runner confirma packs/runs distintos y muestra un PASS para cada run limpio en estado `ready`.
5. El preflight no inicia timelines, no drena el Router y no envía comandos de mutación.

## 3. Comando recomendado: dry-run

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --effects dry-run
```

Debe terminar con cinco líneas PASS —DANA, aborto DANA, incendio, aborto incendio y aislamiento— más la ruta a `summary.md`.

## 3b. Simulación agente (`agent_simulation`) y aprendizaje histórico

Para demostrar conversación agente-a-agente sin PSTN/Web Voice real y aprendizaje entre runs del mismo pack:

```bash
./scripts/reseed-runs.sh --yes
node scripts/e2e-historical-learning.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run run-dana-demo --dana-run2 run-dana-demo-2 \
  --wildfire-run run-wildfire-demo \
  --effects agent_simulation
```

Debe terminar con:

```
PASS dana1: agent_simulation transcript → Outcome → replan
PASS lesson created for dana1
PASS lesson injection: dana2 sees lesson, wildfire isolated
PASS dana2 applied lesson to plan and recorded link
PASS wildfire isolation: no dana lesson
```

El Outcome de `dana1` contiene `observed_effects.interaction_mode=agent_simulation` y `simulated_transcript` (2-6 líneas, primera `SIMULACIÓN —`). El `crisis-review` crea una `Lesson` pack-scoped (`lessons` table, `source_run_id` único) y `dana2` la recibe en `GET /api/snapshot` (`lessons` array) y la aplica: `plan_lessons` registra el enlace y el nuevo `Plan` cambia `objectives` con la instrucción. `wildfire` nunca recibe la lección DANA.

## 3c. Referencia visual

La UI v2 toma como referencia `Valte · Pantallas.html` (bundle) y `frontend/design/*.body.html` de `feat/valte-v2` unpacked en `docs/reference/valte-pantallas/`. `scripts/unpack-valte-pantallas.mjs` regenera la referencia.

## 4. Activación live: modo exacto y doble barrera

Hazlo solo después de comprobar visualmente que el destinatario está en whitelist y que todo mensaje empieza con `SIMULACIÓN`:

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --effects web_voice \
  --confirm-live-contact SIMULACION
```

La confirmación CLI es la primera barrera; la whitelist server-side es la segunda. Selecciona exactamente uno de `web_voice`, `email` o `pstn`. El runner exige que `Outcome.observed_effects.interaction_mode` coincida con el modo solicitado; un fallback a otro canal no produce PASS. Si necesitas email tras un preflight fallido de Web Voice, detén ese ensayo y arranca uno nuevo seleccionando `--effects email`. Un efecto incierto queda `unknown` y nunca se reintenta a ciegas.

## 5. Guion de 8–10 minutos

| Tiempo | Qué decir | Qué mostrar en `/ops` | Qué verificar |
| --- | --- | --- | --- |
| 00:00–01:00 | “Esto es una SIMULACIÓN. El Gateway mantiene estado observable y los tres workflows operan mediante eventos.” | Snapshot DANA limpio. | Run/pack v2 correctos; sin Signals, Incidents, Plan, Actions ni Outcomes. |
| 01:00–02:00 | “El Controller emite el timeline completo antes de permitir cualquier workflow.” | Reloj y eventos fuente DANA. | Controller termina; Router aún no se drena. |
| 02:00–03:00 | “Drenamos exactamente un trabajo y esperamos progreso antes del siguiente.” | Signals, Incidents y Plan operativo tras completar el upstream. | `source_input.received → Intake → signal.created → Command`. |
| 03:00–04:00 | “La misión de contacto de mayor prioridad requiere decisión humana.” | Action activa `contact_entity`, `pending_approval`, con `params.mission` y respuesta `accept_or_reject` o `acknowledge`. | Política `human_required`; aprobación de operador; el mismo `command_id` repetido devuelve el mismo resultado. |
| 04:00–05:00 | “Coordination registra lo observado, no lo que querríamos que hubiera pasado.” | Action aprobada y Outcome. | `action.approved → Coordination`; estado, evidencia y `interaction_mode` exacto. |
| 05:00–06:15 | “El Outcome vuelve a Command y provoca una revisión material del Plan.” | Nueva versión del Plan y Actions modificadas. | `outcome.recorded → Command`; el replan supersede exactamente el Plan aprobado y tiene causalidad Outcome-driven. |
| 06:15–06:45 | “Cerramos DANA explícitamente como operador.” | Estado DANA `aborted`. | `abort_run` ocurre después del replan; los objetos siguen visibles. |
| 06:45–07:15 | “Antes del incendio probamos dos fronteras de aislamiento.” | Run incendio todavía limpio. | Rechaza digest DANA y Action DANA sin cambiar versión. |
| 07:15–08:00 | “Repetimos el mismo motor con otro pack; no cambiamos prompts ni workflows.” | Timeline incendio completo. | Controller termina antes del primer drenaje. |
| 08:00–09:15 | “Mismo pipeline, semántica distinta del pack.” | Signal → Plan → aprobación → Outcome → replan. | Los tres workflows y contratos v2; después, aborto explícito. |
| 09:15–10:00 | “La evidencia queda reproducible y redactada.” | `summary.md` y artifacts. | Sin IDs/términos DANA en incendio, sin verdad oculta ni secretos, exit `0`. |

## 6. Fallos y decisión en vivo

| Fallo | Acción del presentador | Evidencia válida |
| --- | --- | --- |
| Realtime cae | Continúa con polling y muestra `degraded`. | El snapshot sigue avanzando. |
| `version_conflict` | Relee el snapshot y decide de nuevo; como máximo un reintento con ID nuevo. | No existe mutación parcial. |
| HappyRobot tarda | Después de que termine el Controller, sigue drenando de uno en uno hasta el timeout. | El outbox continúa visible. |
| Timeout HTTP de mutación/Router | Marca el estado como incierto y no reintentes. Reconcilia receipt del comando, `state_version` y outbox antes de decidir. | Snapshot y receipt determinan si la operación ocurrió. |
| Canal externo falla antes de intentar | Detén el ensayo y arranca otro seleccionando explícitamente el canal alternativo. | El nuevo Outcome declara ese canal exacto. |
| Efecto incierto | Detén el reintento. | Outcome `unknown`. |
| Run no está limpio | Detén la demo y provisiona IDs nuevos. | Nunca se borra automáticamente. |
| El Plan activo no contiene misión de contacto aprobable | Detén la demo; no elijas otra primitive ni inventes texto. Corrige el workflow Command. | Debe existir `contact_entity` pendiente, humana, con `mission` no vacía y `requested_response` igual a `accept_or_reject` o `acknowledge`. |
| Router no muestra progreso tras un dispatch | No envíes otro dispatch; conserva artifacts y termina. | Última `state_version`, outbox y respuesta del Router. |

## 7. Checklist final de aceptación

- [ ] Controller terminó antes del primer drenaje de Router en cada pack.
- [ ] Cada drenaje usó `limit=1`, `run_id` e `interaction_mode`, esperando progreso antes del siguiente dispatch.
- [ ] DANA quedó aborted mediante `abort_run` de operator antes de arrancar incendio.
- [ ] Ambos recorridos pasaron por los tres workflows.
- [ ] Cada outbox del trail quedó `dispatched` y tuvo respuesta Router exitosa.
- [ ] La Action elegida pertenecía al Plan activo, era `contact_entity`, `pending_approval` y `human_required`, con misión no vacía y respuesta `accept_or_reject` o `acknowledge`.
- [ ] El mismo `command_id` de aprobación devolvió el mismo resultado.
- [ ] Incendio rechazó digest y Action DANA.
- [ ] No hubo IDs, recursos ni términos DANA en estado/artifacts de incendio salvo los dos requests negativos.
- [ ] La Action aprobada llegó a Outcome y a un replan material que supersede exactamente su Plan.
- [ ] El Outcome declaró exactamente `dry-run`, `web_voice`, `email` o `pstn` según `--effects`.
- [ ] Incendio también quedó aborted después de su replanificación.
- [ ] No hubo hidden truth ni secretos en snapshots/artifacts.
- [ ] `summary.md` es legible y el proceso salió `0`.
