# Minimal Azure Static Web Apps Crisis Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar una pantalla `/ops` accesible y orientada a demo que lea el snapshot autoritativo, siga cambios por Supabase Realtime con polling de respaldo y permita aprobar, rechazar, pausar, reanudar o abortar mediante el Gateway.

**Architecture:** Una aplicación estática sin framework ni build sirve HTML, CSS y JavaScript nativos desde Azure Static Web Apps. El navegador obtiene siempre el estado completo de `GET /api/snapshot`; Supabase Realtime actúa únicamente como aviso para volver a leer ese snapshot y nunca como fuente de orden o completitud. Todas las mutaciones pasan por `POST /api/commands` con `expected_state_version`, y el cliente vuelve a leer tras cada comando o conflicto.

**Tech Stack:** HTML semántico, CSS, JavaScript ESM nativo, `@supabase/supabase-js@2` cargado desde CDN, Azure Static Web Apps, Gateway HTTP v2

---

## Restricciones explícitas

- No TDD, Vitest, Jest, Playwright ni otro framework de pruebas.
- Verificación únicamente mediante smoke checks manuales y comandos de sintaxis/configuración.
- No framework UI, bundler, transpiler, `npm install` adicional ni proceso de build.
- No backend adicional, Redis, SSE ni escritura directa a tablas Supabase.
- No modificar `.env.example`, `package.json`, `schemas/v2/**`, `api/**` ni archivos de otros frentes.
- No introducir claves `SUPABASE_SERVICE_ROLE_KEY`; la anon key es pública y solo da lectura a las proyecciones de demo.
- No mostrar, solicitar ni conservar `hidden_truth`.
- Toda la interfaz y cada acción externa visible deben estar marcadas como `SIMULACIÓN`.
- Este frente no crea commits. El coordinador integra y hace el commit de la ola.

## Precondiciones de integración

Antes de ejecutar el smoke conectado, el coordinador proporciona:

```text
GATEWAY_URL=https://<azure-static-web-app-host>
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_ANON_KEY=<public-anon-key>
DEMO_RUN_ID=<seed-dana-run-id>
```

El Gateway ya debe respetar estas interfaces congeladas:

```text
GET  /api/snapshot?run_id=<id>
POST /api/commands
```

El dashboard consume este shape mínimo, sin crear otro modelo de dominio:

```json
{
  "run": {
    "run_id": "run-dana-demo",
    "pack_id": "dana-demo",
    "pack_version": "1.0.0",
    "pack_digest": "64-caracteres-hex",
    "state_version": 7,
    "status": "running",
    "scenario_now": "2026-09-19T10:03:00.000Z"
  },
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

Los nombres de los objetos v2 proceden exclusivamente de `schemas/v2/*.schema.json`. El cliente puede tolerar arrays ausentes tratándolos como `[]`, pero debe rechazar como error visible un snapshot sin `run.run_id`, `run.pack_id`, `run.pack_version`, `run.pack_digest` o `run.state_version`.

## Mapa de archivos

| Ruta | Acción | Responsabilidad única |
| --- | --- | --- |
| `app/index.html` | Crear | Shell semántico, aviso de simulación, controles y regiones de paneles |
| `app/styles.css` | Crear | Layout responsive, alto contraste, foco y estados no dependientes del color |
| `app/app.js` | Crear | Configuración runtime, snapshot, render, Realtime, polling y comandos |
| `staticwebapp.config.json` | Crear | Rutas `/ops`, fallback SPA y cabeceras de seguridad/cache |

No se crean fixtures ni un servidor mock. Para el smoke local se usa el Gateway real de development y un servidor estático de Python.

## Task 1: Crear el shell accesible de una sola pantalla

**Files:**

- Create: `app/index.html`

- [ ] **Step 1: Crear el documento y la configuración runtime pública**

Usar exactamente estos parámetros opcionales de query string, sin persistirlos en `localStorage` ni imprimirlos:

```text
run_id=<run id requerido>
gateway_url=<origen del Gateway; por defecto location.origin>
supabase_url=<URL pública; si falta se usa polling>
supabase_anon_key=<anon key pública; si falta se usa polling>
```

El `<head>` debe contener `charset`, `viewport`, título, `theme-color`, `<link rel="stylesheet" href="/styles.css">` y `<script type="module" src="/app.js"></script>`. Las rutas son absolutas para que funcionen igual en `/` y `/ops`; no añadir scripts inline ni secretos.

- [ ] **Step 2: Añadir cabecera y estado de conexión**

Crear esta jerarquía de elementos y conservar los IDs porque `app/app.js` los usa como contrato interno:

```html
<a class="skip-link" href="#main">Saltar al estado de la crisis</a>
<header class="topbar">
  <div>
    <p class="eyebrow">SIMULACIÓN · NO ES UN SERVICIO DE EMERGENCIAS</p>
    <h1>Centro de coordinación de crisis</h1>
  </div>
  <div id="connection-status" class="connection" data-state="offline"
       role="status" aria-live="polite">offline</div>
</header>
<div id="error-banner" class="banner" role="alert" hidden></div>
```

- [ ] **Step 3: Añadir resumen del run y controles operativos**

Dentro de `<main id="main">`, crear:

```html
<section class="run-strip" aria-labelledby="run-title">
  <div>
    <h2 id="run-title">Run</h2>
    <dl id="run-summary" class="run-summary"></dl>
  </div>
  <div id="run-controls" class="controls" aria-label="Controles del run">
    <button type="button" data-command="pause_run">Pausar</button>
    <button type="button" data-command="resume_run">Reanudar</button>
    <button type="button" data-command="abort_run" class="danger">Abortar simulación</button>
  </div>
</section>
```

Los botones se habilitan según estado: `pause_run` solo en `running`, `resume_run` solo en `paused` y `abort_run` solo en `ready`, `running` o `paused`.

- [ ] **Step 4: Añadir los siete paneles de lectura**

Crear una cuadrícula `#dashboard-grid` con secciones y listas vacías para:

```text
#signals-list   — Signals activas con revisión, modalidad, ubicación y confianza
#incidents-list — Incidents canónicos con P0–P3, confianza, zona y evidencia
#plan-panel     — Plan activo, versión, objetivos, incidentes y acciones
#actions-list   — Actions, estado, prioridad, riesgo, evidencia y controles humanos
#outcomes-list  — Outcomes append-only, intento, resultado y resumen
#resources-list — disponibilidad/reserva observable
#timeline-list  — timeline derivado y ordenado por tiempo persistido
```

Cada sección debe tener un `<h2>`, un contador con `aria-label`, un estado vacío explícito y nunca depender de iconos o color para transmitir estado.

- [ ] **Step 5: Añadir templates seguros para elementos repetidos**

Definir `<template id="empty-template">`, `<template id="record-template">` y `<template id="action-template">`. El JavaScript rellenará texto únicamente con `textContent`; no usar `innerHTML` con contenido de snapshot.

- [ ] **Step 6: Comprobar el HTML sin iniciar integración**

Run:

```bash
python3 -m http.server 4173 --directory app
```

Expected: `Serving HTTP on ... port 4173`; al abrir `http://localhost:4173/` aparecen el aviso `SIMULACIÓN`, los siete paneles y un error accesible indicando que falta `run_id`. Detener el servidor con `Ctrl-C`.

## Task 2: Diseñar layout, contraste y foco

**Files:**

- Create: `app/styles.css`

- [ ] **Step 1: Definir tokens visuales de alto contraste**

Crear variables CSS para fondo, superficie, texto, borde, foco y los cuatro estados. Cada estado debe combinar color con texto visible:

```css
:root {
  color-scheme: dark;
  --bg: #081018;
  --surface: #111c27;
  --surface-raised: #172635;
  --text: #f6f8fb;
  --muted: #b6c2cf;
  --border: #3b4c5d;
  --focus: #ffd166;
  --live: #43d17d;
  --stale: #f6c453;
  --degraded: #ff8f3d;
  --offline: #ff6b6b;
  --danger: #d7394c;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}
```

- [ ] **Step 2: Implementar una cuadrícula responsive sin ocultar información**

Usar una columna por defecto, dos columnas desde `48rem` y tres desde `80rem`. La cabecera y el run strip ocupan todo el ancho. Las listas deben crecer en vertical y no crear scroll horizontal salvo datos técnicos largos, que usan `overflow-wrap: anywhere`.

- [ ] **Step 3: Hacer estados y prioridades perceptibles sin depender del color**

Cada badge debe mostrar texto (`P0`, `pending_approval`, `live`, etc.) y usar borde/patrón además del color. Añadir selectores `[data-state="live"]`, `[data-state="stale"]`, `[data-state="degraded"]` y `[data-state="offline"]`.

- [ ] **Step 4: Añadir navegación por teclado y movimiento reducido**

Incluir `:focus-visible` con contorno de al menos `3px`, skip link visible al recibir foco, target mínimo de botón `44px`, y:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 5: Smoke visual responsive**

Run:

```bash
python3 -m http.server 4173 --directory app
```

Expected: a 375 px no hay scroll horizontal; con Tab se alcanza primero “Saltar al estado de la crisis”, después controles y acciones; el foco siempre es visible; a 1280 px aparecen tres columnas sin cortar texto.

## Task 3: Implementar carga, normalización y render del snapshot

**Files:**

- Create: `app/app.js`

- [ ] **Step 1: Definir estado y leer configuración sin guardar credenciales**

Usar un único objeto de estado:

```js
const state = {
  config: null,
  snapshot: null,
  realtime: null,
  pollTimer: null,
  refreshTimer: null,
  inFlight: new Set(),
  lastSuccessfulSync: 0,
  consecutiveFailures: 0,
  realtimeSubscribed: false
};
```

`readConfig()` debe validar `run_id`, normalizar URLs quitando `/` final, aceptar Realtime solo cuando existen `supabase_url` y `supabase_anon_key`, y usar `location.origin` para `gateway_url` si no se indica. Nunca incluir la anon key en errores, logs o DOM.

- [ ] **Step 2: Implementar `fetchSnapshot()` como única lectura autoritativa**

La petición exacta es:

```js
const url = new URL("/api/snapshot", state.config.gatewayUrl);
url.searchParams.set("run_id", state.config.runId);
const response = await fetch(url, { headers: { Accept: "application/json" } });
```

Validar `response.ok`, `snapshot.run.run_id === config.runId` y los cinco campos de identidad/versión definidos en precondiciones. Normalizar únicamente colecciones ausentes:

```js
for (const key of ["signals", "incidents", "actions", "outcomes", "resources", "events", "outbox"]) {
  snapshot[key] = Array.isArray(snapshot[key]) ? snapshot[key] : [];
}
```

No transformar Signal, Incident, Plan, Action ni Outcome a tipos alternativos.

- [ ] **Step 3: Crear helpers DOM seguros**

Implementar `clear(node)`, `appendText(node, tag, text, className)`, `formatTime(value)`, `formatEvidence(evidence)` y `renderEmpty(container, message)`. Todos los valores remotos usan `textContent`. `formatEvidence` muestra `signal_id@revision` para evidencia Signal y `incident_id` para evidencia Incident.

- [ ] **Step 4: Renderizar run, Signals, Incidents y Plan**

`renderRun()` muestra pack/version, run ID, estado, reloj y `state_version`. `renderSignals()` ordena por `scenario_at`, descendente, y muestra solo las revisiones entregadas por el snapshot. `renderIncidents()` muestra estado canónico, prioridad, confianza, `hazard_types`, `zone_ids`, evidencia y `revisit_at`. `renderPlan()` muestra `plan_id`, `plan_version`, `status`, `objectives`, `incident_ids`, `action_ids` y evidencia, o “Sin plan activo”.

- [ ] **Step 5: Renderizar Actions, Outcomes y recursos**

`renderActions()` muestra `action_id`, primitiva, estado, prioridad, riesgo, policy, actor, reserva, razonamiento y evidencia. Solo añade botones “Aprobar” y “Rechazar” cuando `status === "pending_approval"`; cada botón lleva `data-action-id` y `data-decision`. `renderOutcomes()` muestra intento, estado, resumen, efectos observados y evidencia. `renderResources()` muestra las propiedades observables disponibles sin inferir capacidad oculta.

- [ ] **Step 6: Derivar un timeline sin pedir otro endpoint**

`buildTimeline(snapshot)` usa `snapshot.events` como fuente preferente:

```text
Event: sequence, event_type/type, scenario_at/created_at, aggregate_id y resumen observable
Fallback solo si events está vacío: Signal, Action y Outcome por sus timestamps persistidos
```

Ordenar Events por `sequence` persistida y usar timestamp únicamente como desempate; en fallback, ordenar Signal/Action/Outcome por `scenario_at` y `received_at`. `snapshot.outbox` no crea entradas de timeline: solo anota el estado de dispatch (`pending`, `leased`, `delivered`, `failed` o el valor expuesto) sobre el Event correlacionado por `event_id`/`causation_id`. No usar el orden de llegada de Realtime. Limitar la vista a 100 entradas y anunciar “Mostrando 100 de N” si hay más.

- [ ] **Step 7: Conectar el render completo**

`render()` invoca todos los renderers, actualiza botones del run y conserva el foco: si el elemento enfocado tenía `data-action-id` y sigue existiendo tras render, devolverle foco; en caso contrario no mover foco automáticamente.

- [ ] **Step 8: Smoke de sintaxis**

Run:

```bash
node --check app/app.js
```

Expected: código de salida `0` y ninguna salida.

## Task 4: Añadir Realtime con polling de respaldo y estado de salud

**Files:**

- Modify: `app/app.js`

- [ ] **Step 1: Implementar recarga coalescida**

`scheduleRefresh(reason)` debe agrupar avisos durante 250 ms y ejecutar una sola llamada a `fetchSnapshot()`. Si la nueva `state_version` es menor que la actual, ignorarla; si es igual puede actualizar salud pero no volver a renderizar.

- [ ] **Step 2: Suscribirse solo a avisos persistidos del run**

Cuando haya configuración Supabase, importar:

```js
const { createClient } = await import(
  "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm"
);
```

Crear un cliente con persistencia de sesión desactivada y suscribirse a cambios `INSERT` de `events` filtrados por `run_id=eq.<run_id>`. El callback no aplica el payload al dominio: llama a `scheduleRefresh("realtime")`. En `SUBSCRIBED` marcar `realtimeSubscribed=true`; en error, timeout o cierre marcarlo `false` y conservar polling.

- [ ] **Step 3: Implementar polling fallback cada cinco segundos**

`startPolling()` ejecuta `scheduleRefresh("poll")` cada `5000` ms cuando Realtime no está suscrito. Aunque Realtime esté activo, hacer un refresh de reconciliación cada `30000` ms para corregir eventos perdidos. Evitar dos fetch simultáneos con una promesa compartida.

- [ ] **Step 4: Definir la máquina de salud visible**

Aplicar exactamente estas reglas, evaluadas cada segundo:

```text
live      = último snapshot correcto hace <=10 s y Realtime está SUBSCRIBED
degraded  = último snapshot correcto hace <=10 s y Realtime no está disponible
stale     = último snapshot correcto hace >10 s y <=30 s
offline   = aún no hubo snapshot correcto, o hace >30 s y hay fallos consecutivos
```

Actualizar texto y `data-state`; no mostrar solo un punto de color. Al recuperar conexión, ocultar error y anunciar “Conexión recuperada”.

- [ ] **Step 5: Limpiar recursos del navegador**

En `pagehide`, limpiar timers y cancelar el canal Realtime. No añadir listeners nuevos en cada render.

- [ ] **Step 6: Smoke de fallback**

Abrir con configuración Supabase omitida:

```text
http://localhost:4173/?run_id=<DEMO_RUN_ID>&gateway_url=<GATEWAY_URL>
```

Expected: carga el snapshot, muestra `degraded` con texto “polling activo” y registra una petición `/api/snapshot` cada cinco segundos; no hay error no capturado en consola.

## Task 5: Añadir comandos humanos con concurrencia optimista

**Files:**

- Modify: `app/app.js`

- [ ] **Step 1: Construir el envelope congelado del Gateway**

`buildCommand(commandType, payload)` debe devolver:

```js
{
  command_id: `ops-${crypto.randomUUID()}`,
  run_id: snapshot.run.run_id,
  pack_id: snapshot.run.pack_id,
  pack_version: snapshot.run.pack_version,
  pack_digest: snapshot.run.pack_digest,
  expected_state_version: snapshot.run.state_version,
  actor: "operator",
  command_type: commandType,
  payload,
  causation_id: null
}
```

No enviar campos que no estén en la interfaz congelada.

- [ ] **Step 2: Implementar `sendCommand()`**

Hacer `POST` a `/api/commands` con `Content-Type: application/json`. Deshabilitar solo el control en curso, mostrar “Enviando…”, y tras éxito ejecutar inmediatamente `scheduleRefresh("command")`. No modificar localmente Action, Plan ni versión antes de la respuesta.

- [ ] **Step 3: Resolver conflictos sin sobrescribir**

Si el Gateway devuelve `version_conflict` o HTTP `409`, no repetir el comando. Volver a leer el snapshot, mostrar “El estado cambió; revisa la versión actual y vuelve a decidir” y devolver foco al panel afectado. Un reintento humano generará un `command_id` nuevo.

- [ ] **Step 4: Conectar aprobación y rechazo**

Delegar un único listener de click en `#actions-list`:

```text
Aprobar → command_type=approve_action, payload={"action_id":"<id>"}
Rechazar → command_type=reject_action, payload={"action_id":"<id>"}
```

Antes de rechazar, pedir confirmación nativa con texto que incluye el ID y `SIMULACIÓN`. La aprobación no usa confirmación extra para mantener fluida la demo.

- [ ] **Step 5: Conectar pausa, reanudación y aborto**

Delegar en `#run-controls`:

```text
pause_run  → payload={}
resume_run → payload={}
abort_run  → payload={}
```

`abort_run` requiere confirmación: “SIMULACIÓN: abortar cierra el run y no puede deshacerse. ¿Continuar?”.

- [ ] **Step 6: Arrancar en orden seguro**

En `main()`:

```text
1. leer/validar config;
2. instalar listeners una vez;
3. obtener snapshot inicial;
4. renderizar;
5. iniciar Realtime si hay config;
6. iniciar polling y reloj de salud.
```

Un fallo inicial deja la pantalla utilizable para reintento automático y nunca habilita mutaciones sin snapshot válido.

- [ ] **Step 7: Smoke de mutación DANA**

Con un Action `pending_approval`, abrir:

```text
http://localhost:4173/?run_id=<DEMO_RUN_ID>&gateway_url=<GATEWAY_URL>&supabase_url=<SUPABASE_URL>&supabase_anon_key=<SUPABASE_ANON_KEY>
```

Pulsar “Aprobar”. Expected: Network muestra un único `POST /api/commands` con `actor=operator`, `command_type=approve_action` y la versión visible; después un nuevo snapshot aumenta `state_version`, Action deja `pending_approval` y el timeline muestra el cambio. Supabase no recibe ninguna escritura desde el navegador.

## Task 6: Configurar Azure Static Web Apps y cerrar smoke checks

**Files:**

- Create: `staticwebapp.config.json`

- [ ] **Step 1: Configurar rutas estáticas**

Crear configuración JSON válida con:

```json
{
  "routes": [
    { "route": "/", "rewrite": "/index.html" },
    { "route": "/ops", "rewrite": "/index.html" },
    { "route": "/ops/*", "rewrite": "/index.html" }
  ],
  "navigationFallback": {
    "rewrite": "/index.html",
    "exclude": ["/api/*", "/*.{css,js,png,jpg,jpeg,gif,svg,ico,json}"]
  },
  "globalHeaders": {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self'; connect-src 'self' https://*.supabase.co wss://*.supabase.co; img-src 'self' data:; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
  },
  "mimeTypes": {
    ".js": "text/javascript"
  }
}
```

El coordinador debe empaquetar esta configuración junto al contenido de `app/` en el artifact de Azure; este frente no modifica workflows de despliegue.

- [ ] **Step 2: Validar JSON y sintaxis**

Run:

```bash
node -e "JSON.parse(require('node:fs').readFileSync('staticwebapp.config.json','utf8')); console.log('PASS staticwebapp.config.json')"
node --check app/app.js
```

Expected:

```text
PASS staticwebapp.config.json
```

El segundo comando no imprime nada y ambos terminan con código `0`.

- [ ] **Step 3: Verificar que los contratos compartidos siguen intactos**

Run:

```bash
npm run contracts:check
```

Expected:

```text
PASS dana-demo: Signal → Incident → Plan → Action → Outcome
PASS wildfire-demo: Signal → Incident → Plan → Action → Outcome
```

- [ ] **Step 4: Ejecutar smoke manual completo**

Checklist observable:

```text
[ ] /ops muestra siempre SIMULACIÓN y el run DANA correcto.
[ ] Signals, Incidents, Plan, Actions, Outcomes, recursos y timeline son legibles.
[ ] Desconectar Realtime mantiene snapshot por polling y marca degraded/stale.
[ ] Restaurar Realtime vuelve a live sin recargar la página.
[ ] Aprobar una Action aumenta state_version y termina mostrando su Outcome.
[ ] Un version_conflict recarga y no repite la mutación.
[ ] Pausa y reanudación cambian el estado mediante Gateway.
[ ] Toda la operación es posible con teclado y el foco es visible.
[ ] No aparecen hidden_truth, service_role ni secretos en DOM, consola o Network.
```

- [ ] **Step 5: Verificar el diff sin hacer commit**

Run:

```bash
git diff --check -- app/index.html app/app.js app/styles.css staticwebapp.config.json
git status --short -- app/index.html app/app.js app/styles.css staticwebapp.config.json
```

Expected: `git diff --check` sin salida; `git status` lista únicamente los cuatro archivos propiedad de este frente. Entregar al coordinador sin ejecutar `git add` ni `git commit`.

## Contrato de entrega al coordinador

Informar:

```text
Dashboard smoke: PASS|FAIL
Run probado: <run_id>
Versión antes/después de aprobar: <n> → <n+1 o superior>
Realtime: live|fallback probado
Archivos: app/index.html, app/app.js, app/styles.css, staticwebapp.config.json
Bloqueos: ninguno | request/response/error exactos
```

No ampliar alcance si falta una interfaz. Si `/api/snapshot` o `/api/commands` no respetan el contrato congelado, capturar request, status y body exactos y devolver el bloqueo al coordinador.
