# Diseño de entrega paralela en seis frentes

## 1. Objetivo

Entregar la demo generalista de crisis con el mínimo código propio, usando los contratos v2 ya implementados como frontera estable. Los seis frentes se ejecutan en dos olas de tres agentes porque la sesión admite tres trabajadores simultáneos además del coordinador.

El objetivo inmediato es una demo completa DANA y una comprobación E2E de incendio. Los otros cuatro Scenario Packs y las capacidades avanzadas permanecen después de esta entrega mínima.

## 2. Restricciones de ejecución

- Sin TDD ni framework de pruebas unitarias.
- Verificación por smoke checks de cada frente y E2E de integración.
- Máximo tres agentes implementadores simultáneos.
- Ningún agente modifica archivos propiedad de otro frente.
- Los agentes no hacen commits paralelos; el coordinador integra y crea un commit por ola.
- Solo el coordinador cambia contratos compartidos, variables comunes o interfaces entre frentes.
- Se reutilizan Supabase, HappyRobot y Azure Static Web Apps; no se introduce Redis, Kafka, Docker ni un backend adicional.
- La demo usa destinatarios controlados y mensajes `SIMULACIÓN`.

## 3. Interfaces congeladas antes de empezar

Los contratos v2 bajo `schemas/v2/` son la autoridad para Signal, Incident, Plan, Action y Outcome. Ningún frente crea una representación alternativa.

El coordinador congela además estas interfaces mínimas:

### 3.1 Gateway HTTP

```text
POST /api/commands
GET  /api/snapshot?run_id=<id>
POST /api/event-router
```

`POST /api/commands` recibe:

```json
{
  "command_id": "cmd-unique",
  "run_id": "run-id",
  "pack_id": "pack-id",
  "pack_version": "1.0.0",
  "pack_digest": "sha256-hex",
  "expected_state_version": 3,
  "actor": "scenario-controller|happyrobot|operator",
  "command_type": "receive_source_input|upsert_signal|replace_plan|approve_action|reject_action|record_outcome|advance_clock|pause_run|resume_run|abort_run",
  "payload": {},
  "causation_id": null
}
```

La respuesta aceptada contiene `command_id`, `state_version`, `result` y eventos generados. Un conflicto devuelve `version_conflict`; repetir el mismo `command_id` devuelve el resultado original.

### 3.2 Snapshot observable

El snapshot incluye identidad del run, reloj, Signals activas, Incidents canónicos, Plan activo, Actions, Outcomes, recursos y outbox visible. Nunca incluye `hidden_truth`.

### 3.3 Variables compartidas

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
DATABASE_URL
GATEWAY_URL
HAPPYROBOT_KEY
HAPPYROBOT_BASE_URL
HAPPYROBOT_ENV
```

Los nombres se congelan antes de la Ola 1. Los secretos no se escriben en el repositorio.

## 4. Ola 1 — núcleo, tres agentes en paralelo

### 4.1 Frente A — Supabase y State Gateway

**Propósito:** ofrecer una única autoridad de estado e idempotencia.

**Propiedad exclusiva:**

```text
supabase/migrations/
supabase/seed.sql
api/_shared/supabase.mjs
api/commands/
api/event-router/
api/snapshot/
```

**Entrega mínima:**

- tablas para runs, source inputs, Signals, Incidents, Plans, Actions, Outcomes, resources, commands, events y outbox;
- `state_version` por run;
- una función SQL/RPC `apply_command` que guarda comando, mutación, eventos y outbox atómicamente;
- endpoint fino `/api/commands` que delega en la RPC;
- endpoint `/api/event-router` que reclama, despacha y marca trabajo idempotentemente;
- allowlist `source_input.received → Intake`, `signal.created/revised → Command`, `action.approved → Coordination` y `outcome.recorded → Command`;
- endpoint `/api/snapshot` de lectura para dashboard y workflows;
- seed de un run DANA listo para recibir Signals.

No implementa todavía reservas avanzadas, backpressure por carriles, retractaciones o terminal fence completo. Conserva columnas/extensiones claras para añadirlas sin romper contratos.

**Smoke check:** aplicar migración, enviar dos veces el mismo `command_id` y comprobar una sola mutación y el mismo resultado.

### 4.2 Frente B — Scenario Controller y dos packs

**Propósito:** producir una crisis dinámica reproducible sin conocer internals de Supabase.

**Propiedad exclusiva:**

```text
scenario-packs/dana-demo/
scenario-packs/wildfire-demo/
scripts/scenario-controller.mjs
```

**Entrega mínima:**

- manifest, zonas, entidades, recursos, timeline y hidden truth separados para DANA;
- pack mínimo de incendio con IDs y vocabulario distintos;
- modo `--dry-run` que imprime los comandos sin red;
- modo conectado que usa únicamente `GATEWAY_URL/api/commands` y entrega `receive_source_input`, nunca una Signal ya interpretada;
- avance, pausa, reanudación e inyección de eventos por tiempo de escenario;
- ningún acceso directo a tablas de Supabase.

**Smoke check:** dry-run DANA produce una secuencia determinista; después incendio no contiene IDs ni términos exclusivos de DANA.

### 4.3 Frente C — tres workflows HappyRobot

**Propósito:** configurar razonamiento y coordinación sobre los contratos congelados.

**Propiedad exclusiva:**

```text
happyrobot/crisis-intake/
happyrobot/crisis-command/
happyrobot/crisis-response-coordination/
happyrobot/README.md
```

**Entrega mínima:**

- prompts y contratos de entrada/salida versionados;
- Intake transforma llamada/webhook en Signal v2;
- Command transforma snapshot en Incident, Plan y Actions genéricas;
- Coordination acepta Action aprobada y devuelve Outcome;
- cada workflow recibe `run_id`, identidad del pack y `state_version`;
- las herramientas llaman al Gateway HTTP, nunca escriben directamente en Supabase;
- ejecución native/isolated con ejemplos DANA e incendio;
- configuración manual mínima en HappyRobot Platform mediante checklist exacto, con prompts y contratos guardados en el repositorio, IDs por variables de entorno y export de la versión resultante; no se crea un sincronizador propio.

**Smoke check:** cada workflow procesa su fixture aislada y devuelve JSON válido contra los schemas v2.

## 5. Puerta de integración 1

El coordinador no inicia la Ola 2 hasta verificar:

1. las migraciones se aplican en Supabase;
2. un comando duplicado es idempotente;
3. Scenario Controller registra un source input mediante Gateway y Router lo despacha a Intake;
4. Intake devuelve una Signal v2 válida y la guarda mediante `upsert_signal`;
5. Command recibe snapshot y devuelve un Plan con Action trazable;
6. Coordination devuelve un Outcome válido;
7. ningún componente escribe fuera de su interfaz asignada.

Los fallos se devuelven al propietario del frente. El coordinador no reimplementa el componente ni cambia el contrato para ocultar el fallo.

El commit de la Ola 1 contiene únicamente núcleo, dos packs y artefactos HappyRobot.

## 6. Ola 2 — experiencia y validación, tres agentes en paralelo

### 6.1 Frente D — Dashboard Azure Static Web Apps

**Propósito:** mostrar el estado y permitir intervención humana mínima.

**Propiedad exclusiva:**

```text
app/index.html
app/app.js
app/styles.css
staticwebapp.config.json
```

**Entrega mínima:**

- JavaScript y CSS sin framework ni proceso de build;
- snapshot inicial y actualización Supabase Realtime con polling como fallback;
- paneles de run, Signals, Incidents, Plan, Actions, Outcomes y timeline;
- botones aprobar, rechazar, pausar, reanudar y abortar mediante Gateway;
- indicador `live`, `stale`, `degraded` u `offline`;
- lenguaje visible de `SIMULACIÓN`.

**Smoke check:** abrir localmente con un snapshot DANA, aprobar una Action y observar la nueva versión.

### 6.2 Frente E — interacción real y fallback

**Propósito:** demostrar al menos un efecto externo real y controlado.

**Propiedad exclusiva:**

```text
happyrobot/integrations/
examples/real-interaction/
docs/demo-contacts.md
```

**Entrega mínima:**

- Web Voice como canal principal; PSTN solo si ya está disponible;
- un email configurado como fallback;
- whitelist de destinatarios de demo;
- prefijo hablado/escrito `SIMULACIÓN`;
- callbacks correlacionados por `dispatch_id` y convertidos en Outcomes;
- modo dry-run que conserva el mismo payload sin contactar a nadie.

**Smoke check:** una Action aprobada produce una interacción controlada o fallback, y su callback registra exactamente un Outcome.

### 6.3 Frente F — E2E y guion de demo

**Propósito:** verificar el sistema distribuido completo sin introducir un framework de tests.

**Propiedad exclusiva:**

```text
scripts/e2e-demo.mjs
docs/demo-runbook.md
artifacts/e2e/
```

**Entrega mínima:**

- un script E2E que llama interfaces públicas, no tablas internas;
- recorrido DANA: Signal → Intake → Gateway → Command → aprobación → Coordination → Outcome → replanificación;
- recorrido secuencial DANA cerrada → incendio nuevo;
- comprobaciones de identidad del pack, referencias, idempotencia, trazabilidad y ausencia de contaminación;
- guion live de 8–10 minutos;
- captura de IDs, versiones y resultados en `artifacts/e2e/`, sin secretos.

**Smoke check:** ambos recorridos finalizan con código cero y generan un resumen legible.

## 7. Puerta de integración 2

El coordinador verifica en este orden:

1. `npm run contracts:check` continúa pasando;
2. migración limpia y seed DANA;
3. Scenario Controller conectado;
4. tres workflows conectados;
5. dashboard observa y muta únicamente vía interfaces permitidas;
6. una interacción controlada genera Outcome;
7. E2E DANA pasa;
8. E2E incendio pasa inmediatamente después sin contaminación;
9. `git diff --check` y escaneo de secretos pasan;
10. worktree queda limpio tras el commit de Ola 2.

## 8. Política de mocks y fallos

- No se crea un servidor mock adicional.
- Antes de la integración, Scenario Controller usa `--dry-run` y los workflows usan fixtures v2.
- Dashboard puede cargar un snapshot JSON estático únicamente en modo local; producción siempre consulta el Gateway/Supabase.
- Un frente bloqueado documenta el request, response y error exactos. No modifica contratos compartidos.
- Si un cambio de interfaz es imprescindible, el coordinador pausa los consumidores, actualiza la interfaz una vez y notifica a los tres frentes afectados.
- Un fallo de canal externo cambia a fallback; no se marca como éxito sin Outcome confirmado.

## 9. Revisiones y commits

No hay TDD. Cada frente realiza su smoke check antes de entregar. Después de cada ola:

1. un revisor comprueba cumplimiento del alcance;
2. otro revisor comprueba simplicidad, calidad e integración;
3. el propietario corrige únicamente los hallazgos confirmados;
4. el coordinador ejecuta la puerta completa;
5. el coordinador crea un único commit de la ola.

Los agentes paralelos no hacen commits para evitar carreras sobre el índice Git compartido.

## 10. Resultado de esta entrega

Al terminar las dos olas existe:

- un estado compartido en Supabase;
- DANA dinámica y un incendio aislado;
- tres workflows HappyRobot conectados;
- dashboard observable e intervenible;
- una interacción real controlada con fallback;
- un E2E y guion de demo reproducibles.

Quedan fuera de este ciclo los otros cuatro packs, reservas avanzadas, retractación completa, merge/split operativo, directivas complejas, backpressure completo, terminal fence completo y postmortem aprendido. Se incorporan después de demostrar estable el camino mínimo.

## 11. Documentos de ejecución resultantes

Este diseño no se convierte en un único plan monolítico. `writing-plans` generará:

1. un plan coordinador con Wave 0, puertas de integración y commits;
2. un plan autocontenido para Supabase/Gateway;
3. un plan autocontenido para Scenario Controller;
4. un plan autocontenido para HappyRobot;
5. un plan autocontenido para dashboard;
6. un plan autocontenido para interacción real;
7. un plan autocontenido para E2E y runbook.

Cada plan de frente incluirá únicamente sus archivos, comandos, smoke check y contrato de entrega. El coordinador proporcionará el texto completo a cada agente; ningún agente dependerá de leer los otros seis planes.
