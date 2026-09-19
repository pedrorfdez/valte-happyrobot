# Scenario Controller and Two Demo Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a deterministic DANA simulation and an isolated wildfire simulation that emit only frozen Gateway commands while keeping simulator truth private.

**Architecture:** Each Scenario Pack is immutable, declarative JSON split into public world inputs and a separate `hidden-truth.json`. One dependency-free Node.js CLI validates a pack, controls scenario time, and either prints the exact command stream or posts it sequentially to `GATEWAY_URL/api/commands`, carrying forward the returned `state_version`. It never imports Supabase, opens a database connection, or converts source material into Signal v2 itself.

**Tech Stack:** Node.js 24 ESM, JSON, built-in `fetch`, built-in filesystem/path modules

---

## Delivery constraints

- This is a demo increment: no TDD, test framework, schema generator, simulator server, scheduler process, database client, or extra npm dependency.
- Verification uses only the smoke commands in the final task.
- Do not commit. The coordinator owns integration and commits.
- Modify only `scenario-packs/dana-demo/**`, `scenario-packs/wildfire-demo/**`, and `scripts/scenario-controller.mjs`.
- Do not modify schemas, Gateway code, Supabase files, `.env.example`, `package.json`, HappyRobot artifacts, dashboard files, or shared documentation.
- Use only `POST ${GATEWAY_URL}/api/commands`; never call Supabase, PostgREST, HappyRobot, `/api/snapshot`, or another internal endpoint.
- Emit `receive_source_input`, never `upsert_signal`. Intake owns interpretation into Signal v2.
- The CLI may emit only `receive_source_input`, `advance_clock`, `pause_run`, and `resume_run`. It does not prioritize incidents, allocate resources, author plans, or apply hidden effects.
- `hidden-truth.json` must be loaded only for pack preflight and future postmortem use. No field, canary, filename, or value from it may appear in commands or logs during an active run.
- DANA uses the fixed digest of 64 `c` characters and wildfire uses 64 `d` characters. These identities match the Supabase/Gateway seed plan and the existing v2 contract examples.

## Frozen command shape

Every emitted line in dry-run mode and every HTTP body in connected mode is this flat envelope:

```json
{
  "command_id": "cmd-run-dana-demo-demo-001-resume",
  "run_id": "run-dana-demo",
  "pack_id": "dana-demo",
  "pack_version": "1.0.0",
  "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "expected_state_version": 0,
  "actor": "scenario-controller",
  "command_type": "resume_run",
  "payload": {},
  "causation_id": null
}
```

The CLI must stop on any non-2xx response. In particular, it must not silently retry `version_conflict`: the operator must read the current snapshot, decide the new starting version, and start a new operation with a new `--operation-id`.

Every `receive_source_input` command uses one cross-workstream payload shape so Intake can run from the Router delivery alone:

```json
{
  "signal_identity": { "signal_id": "sig-dana-call-001", "revision": 1 },
  "source_input": {
    "source_input_id": "src-dana-call-001",
    "modality": "call_transcript",
    "content": "SIMULACIÓN: ...",
    "reporter_id": "caller-paiporta-01",
    "origin_reference": "fictional-call-dana-001",
    "declared_location": "paiporta-ground-floor"
  },
  "scenario_at": "2026-09-19T10:00:00.000Z",
  "received_at": "2026-09-19T10:00:00.000Z",
  "correlation_id": "corr-dana-call-trapped-001",
  "zone_catalog": [
    { "zone_id": "paiporta-ground-floor", "label": "Paiporta — planta baja" }
  ]
}
```

The command envelope supplies `run_id`, pack identity, `expected_state_version`, actor, and causation. The Gateway copies those values plus the payload above into `source_input.received`, so Intake neither reads Supabase nor invents Signal IDs.

## File map

| Path | Change | Responsibility |
| --- | --- | --- |
| `scenario-packs/dana-demo/manifest.json` | Create | Immutable identity, scenario start/duration, and declared public pack files |
| `scenario-packs/dana-demo/zones.json` | Create | Three DANA zones with generic IDs and display metadata |
| `scenario-packs/dana-demo/entities.json` | Create | Fictitious reporters/assets used by timeline inputs |
| `scenario-packs/dana-demo/resources.json` | Create | One scarce water-rescue resource, descriptive only for this front |
| `scenario-packs/dana-demo/timeline.json` | Create | Four deterministic source inputs including noise and a route-block update |
| `scenario-packs/dana-demo/hidden-truth.json` | Create | Private evaluator facts and canary; never emitted |
| `scenario-packs/wildfire-demo/manifest.json` | Create | Independent wildfire identity and time bounds |
| `scenario-packs/wildfire-demo/zones.json` | Create | Three non-DANA zones |
| `scenario-packs/wildfire-demo/entities.json` | Create | Wildfire-specific reporters/assets |
| `scenario-packs/wildfire-demo/resources.json` | Create | One scarce wildfire brigade |
| `scenario-packs/wildfire-demo/timeline.json` | Create | Four wildfire source inputs including an old-video noise item and wind change |
| `scenario-packs/wildfire-demo/hidden-truth.json` | Create | Private wildfire evaluator facts and distinct canary |
| `scripts/scenario-controller.mjs` | Create | Pack preflight, deterministic command generation, dry-run, connected run, advance, pause, resume, and injection |

### Task 1: Create the DANA demo pack

**Files:**

- Create: `scenario-packs/dana-demo/manifest.json`
- Create: `scenario-packs/dana-demo/zones.json`
- Create: `scenario-packs/dana-demo/entities.json`
- Create: `scenario-packs/dana-demo/resources.json`
- Create: `scenario-packs/dana-demo/timeline.json`
- Create: `scenario-packs/dana-demo/hidden-truth.json`

- [ ] **Step 1: Create the immutable DANA manifest**

```json
{
  "pack_id": "dana-demo",
  "pack_version": "1.0.0",
  "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "scenario_schema_version": "1.0.0-demo",
  "minimum_engine_version": "1.0.0-demo",
  "locale": "es-ES",
  "scenario_start": "2026-09-19T10:00:00Z",
  "duration_seconds": 480,
  "public_files": [
    "manifest.json",
    "zones.json",
    "entities.json",
    "resources.json",
    "timeline.json"
  ]
}
```

- [ ] **Step 2: Create the DANA zones**

```json
{
  "zones": [
    {
      "zone_id": "paiporta-ground-floor",
      "name": "Paiporta — planta baja",
      "kind": "residential",
      "display": { "x": 18, "y": 62 }
    },
    {
      "zone_id": "catarroja-health-centre",
      "name": "Catarroja — centro de salud",
      "kind": "healthcare",
      "display": { "x": 52, "y": 48 }
    },
    {
      "zone_id": "south-bridge",
      "name": "Puente Sur",
      "kind": "transport",
      "display": { "x": 78, "y": 30 }
    }
  ]
}
```

- [ ] **Step 3: Create the fictitious DANA entities**

```json
{
  "entities": [
    {
      "entity_id": "caller-paiporta-01",
      "entity_type": "resident",
      "name": "Llamante Paiporta 01",
      "zone_id": "paiporta-ground-floor",
      "source_trust": "medium",
      "fictional": true
    },
    {
      "entity_id": "clinic-ops-catarroja",
      "entity_type": "healthcare_operator",
      "name": "Operaciones Centro de Salud",
      "zone_id": "catarroja-health-centre",
      "source_trust": "high",
      "fictional": true
    },
    {
      "entity_id": "social-forward-bridge",
      "entity_type": "social_media_forward",
      "name": "Reenvío social Puente Sur",
      "zone_id": "south-bridge",
      "source_trust": "low",
      "fictional": true
    },
    {
      "entity_id": "road-sensor-paiporta",
      "entity_type": "road_sensor",
      "name": "Sensor vial Paiporta",
      "zone_id": "paiporta-ground-floor",
      "source_trust": "high",
      "fictional": true
    }
  ]
}
```

- [ ] **Step 4: Create the scarce DANA resource description**

```json
{
  "resources": [
    {
      "resource_id": "water-rescue-team-1",
      "name": "Equipo de rescate acuático 1",
      "resource_mode": "reusable",
      "capacity": 1,
      "capabilities": ["water_rescue"],
      "initial_zone_id": "catarroja-health-centre"
    }
  ]
}
```

- [ ] **Step 5: Create the deterministic DANA timeline**

All text is explicitly fictional and marked `SIMULACIÓN`. The pack allocates each future Signal ID/revision, but it does not contain a Signal v2 or interpret confidence, incidents, plans, or actions. Intake owns that interpretation.

```json
{
  "events": [
    {
      "event_id": "dana-call-trapped-001",
      "due_seconds": 0,
      "signal_identity": { "signal_id": "sig-dana-call-001", "revision": 1 },
      "source_input": {
        "source_input_id": "src-dana-call-001",
        "modality": "call_transcript",
        "content": "SIMULACIÓN: dos personas dicen estar atrapadas en una planta baja de Paiporta y el agua sigue subiendo.",
        "reporter_id": "caller-paiporta-01",
        "origin_reference": "fictional-call-dana-001",
        "declared_location": "paiporta-ground-floor"
      }
    },
    {
      "event_id": "dana-clinic-preparation-001",
      "due_seconds": 45,
      "signal_identity": { "signal_id": "sig-dana-clinic-001", "revision": 1 },
      "source_input": {
        "source_input_id": "src-dana-clinic-001",
        "modality": "webhook",
        "content": "SIMULACIÓN: el centro de salud de Catarroja informa de pacientes vulnerables y pide preparar una posible evacuación.",
        "reporter_id": "clinic-ops-catarroja",
        "origin_reference": "fictional-clinic-dana-001",
        "declared_location": "catarroja-health-centre"
      }
    },
    {
      "event_id": "dana-bridge-rumour-001",
      "due_seconds": 90,
      "signal_identity": { "signal_id": "sig-dana-rumour-001", "revision": 1 },
      "source_input": {
        "source_input_id": "src-dana-rumour-001",
        "modality": "text",
        "content": "SIMULACIÓN: un mensaje reenviado sin autor verificable afirma que el Puente Sur se ha derrumbado.",
        "reporter_id": "social-forward-bridge",
        "origin_reference": "fictional-forward-dana-001",
        "declared_location": "south-bridge"
      }
    },
    {
      "event_id": "dana-route-blocked-001",
      "due_seconds": 180,
      "signal_identity": { "signal_id": "sig-dana-road-001", "revision": 1 },
      "source_input": {
        "source_input_id": "src-dana-road-001",
        "modality": "sensor_reading",
        "content": "SIMULACIÓN: el sensor vial confirma que la ruta directa hacia Paiporta queda bloqueada desde este instante.",
        "reporter_id": "road-sensor-paiporta",
        "origin_reference": "fictional-road-dana-001",
        "declared_location": "paiporta-ground-floor"
      }
    }
  ]
}
```

- [ ] **Step 6: Create the private DANA truth**

```json
{
  "visibility": "postmortem_only",
  "canary": "DANA_TRUTH_CANARY_7XQ9",
  "facts": [
    {
      "fact_id": "truth-dana-trapped",
      "statement": "The two trapped people are real and require the scarce water-rescue team first."
    },
    {
      "fact_id": "truth-dana-clinic",
      "statement": "The clinic has a longer preparation window than the trapped residents."
    },
    {
      "fact_id": "truth-dana-bridge",
      "statement": "The bridge-collapse message is an unverified recycled rumour."
    },
    {
      "fact_id": "truth-dana-route",
      "statement": "The direct route becomes unusable at scenario second 180."
    }
  ]
}
```

### Task 2: Create the independent wildfire pack

**Files:**

- Create: `scenario-packs/wildfire-demo/manifest.json`
- Create: `scenario-packs/wildfire-demo/zones.json`
- Create: `scenario-packs/wildfire-demo/entities.json`
- Create: `scenario-packs/wildfire-demo/resources.json`
- Create: `scenario-packs/wildfire-demo/timeline.json`
- Create: `scenario-packs/wildfire-demo/hidden-truth.json`

- [ ] **Step 1: Create the wildfire manifest**

```json
{
  "pack_id": "wildfire-demo",
  "pack_version": "1.0.0",
  "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "scenario_schema_version": "1.0.0-demo",
  "minimum_engine_version": "1.0.0-demo",
  "locale": "es-ES",
  "scenario_start": "2026-09-19T12:00:00Z",
  "duration_seconds": 360,
  "public_files": [
    "manifest.json",
    "zones.json",
    "entities.json",
    "resources.json",
    "timeline.json"
  ]
}
```

- [ ] **Step 2: Create wildfire-specific zones**

```json
{
  "zones": [
    {
      "zone_id": "pinar-norte",
      "name": "Pinar Norte",
      "kind": "forest",
      "display": { "x": 22, "y": 24 }
    },
    {
      "zone_id": "urbanizacion-este",
      "name": "Urbanización Este",
      "kind": "residential",
      "display": { "x": 70, "y": 38 }
    },
    {
      "zone_id": "corredor-sur",
      "name": "Corredor Sur",
      "kind": "transport",
      "display": { "x": 46, "y": 76 }
    }
  ]
}
```

- [ ] **Step 3: Create wildfire-specific entities**

```json
{
  "entities": [
    {
      "entity_id": "tower-camera-north",
      "entity_type": "observation_camera",
      "name": "Cámara Torre Norte",
      "zone_id": "pinar-norte",
      "source_trust": "high",
      "fictional": true
    },
    {
      "entity_id": "weather-station-east",
      "entity_type": "weather_station",
      "name": "Estación Viento Este",
      "zone_id": "urbanizacion-este",
      "source_trust": "high",
      "fictional": true
    },
    {
      "entity_id": "resident-east-01",
      "entity_type": "resident",
      "name": "Residente Este 01",
      "zone_id": "urbanizacion-este",
      "source_trust": "medium",
      "fictional": true
    },
    {
      "entity_id": "old-video-forward",
      "entity_type": "social_media_forward",
      "name": "Reenvío de vídeo antiguo",
      "zone_id": "corredor-sur",
      "source_trust": "low",
      "fictional": true
    }
  ]
}
```

- [ ] **Step 4: Create the scarce wildfire resource**

```json
{
  "resources": [
    {
      "resource_id": "wildfire-brigade-1",
      "name": "Brigada forestal 1",
      "resource_mode": "reusable",
      "capacity": 1,
      "capabilities": ["wildfire_response"],
      "initial_zone_id": "corredor-sur"
    }
  ]
}
```

- [ ] **Step 5: Create the deterministic wildfire timeline**

```json
{
  "events": [
    {
      "event_id": "fire-camera-smoke-001",
      "due_seconds": 0,
      "signal_identity": { "signal_id": "sig-fire-camera-001", "revision": 1 },
      "source_input": {
        "source_input_id": "src-fire-camera-001",
        "modality": "sensor_reading",
        "content": "SIMULACIÓN: una cámara detecta una columna de humo activa en Pinar Norte.",
        "reporter_id": "tower-camera-north",
        "origin_reference": "fictional-camera-fire-001",
        "declared_location": "pinar-norte"
      }
    },
    {
      "event_id": "fire-wind-reading-001",
      "due_seconds": 40,
      "signal_identity": { "signal_id": "sig-fire-wind-001", "revision": 1 },
      "source_input": {
        "source_input_id": "src-fire-wind-001",
        "modality": "sensor_reading",
        "content": "SIMULACIÓN: la estación registra viento que empuja el frente hacia el este.",
        "reporter_id": "weather-station-east",
        "origin_reference": "fictional-weather-fire-001",
        "declared_location": "urbanizacion-este"
      }
    },
    {
      "event_id": "fire-old-video-001",
      "due_seconds": 75,
      "signal_identity": { "signal_id": "sig-fire-video-001", "revision": 1 },
      "source_input": {
        "source_input_id": "src-fire-video-001",
        "modality": "text",
        "content": "SIMULACIÓN: circula un vídeo sin fecha que supuestamente muestra llamas junto al Corredor Sur.",
        "reporter_id": "old-video-forward",
        "origin_reference": "fictional-video-fire-2022",
        "declared_location": "corredor-sur"
      }
    },
    {
      "event_id": "fire-wind-change-001",
      "due_seconds": 150,
      "signal_identity": { "signal_id": "sig-fire-wind-002", "revision": 1 },
      "source_input": {
        "source_input_id": "src-fire-wind-002",
        "modality": "sensor_reading",
        "content": "SIMULACIÓN: una nueva lectura confirma un giro del viento y mayor exposición de Urbanización Este.",
        "reporter_id": "weather-station-east",
        "origin_reference": "fictional-weather-fire-002",
        "declared_location": "urbanizacion-este"
      }
    }
  ]
}
```

- [ ] **Step 6: Create the private wildfire truth**

```json
{
  "visibility": "postmortem_only",
  "canary": "WILDFIRE_TRUTH_CANARY_4MK2",
  "facts": [
    {
      "fact_id": "truth-fire-front",
      "statement": "The active fire begins in Pinar Norte."
    },
    {
      "fact_id": "truth-fire-wind",
      "statement": "The wind change genuinely increases exposure in Urbanizacion Este."
    },
    {
      "fact_id": "truth-fire-video",
      "statement": "The social video predates this run and must not independently drive deployment."
    }
  ]
}
```

### Task 3: Implement the dependency-free Scenario Controller

**Files:**

- Create: `scripts/scenario-controller.mjs`

- [ ] **Step 1: Add argument parsing and explicit CLI usage**

The E2E-facing forms are frozen and must work exactly as written:

```text
node scripts/scenario-controller.mjs --pack <directory> --dry-run
node scripts/scenario-controller.mjs --pack <directory> --run-id <id> --gateway-url <origin> --connected --json
```

Both default to `--mode run`. Manual controls use `--mode advance|pause|resume|inject`; `advance` and `inject` also take `--to-seconds`, while `inject` takes `--source-input <json-file>`. That injection file contains exactly `{ "signal_identity": {...}, "source_input": {...} }`. All forms accept `--state-version`, `--operation-id`, and `--until-seconds`. Use `run-${pack_id}`, `0`, the selected mode, the pack duration, and `GATEWAY_URL` as defaults where applicable.

`--dry-run` and `--connected` are mutually exclusive and one is required. Connected mode requires `--json`. Standard output is always JSON/NDJSON: dry-run writes commands and connected mode writes receipts. Usage, progress, and errors go only to standard error.

For connected `--mode run`, the final stdout line is the E2E barrier: `{run_id, pack_id, pack_version, pack_digest, events_sent, state_version, status:"timeline_complete"}`. It is written only after every timeline command has been accepted. It does not abort/complete the run or drain the Router.

- [ ] **Step 2: Implement the complete controller**

```javascript
#!/usr/bin/env node

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const modes = new Set(["run", "advance", "pause", "resume", "inject"]);

const usage = () => {
  console.error([
    "Usage:",
    "  scenario-controller.mjs --pack <dir> --dry-run",
    "  scenario-controller.mjs --pack <dir> --run-id <id> --gateway-url <origin> --connected --json",
    "Manual: --mode run|advance|pause|resume|inject --to-seconds <N> --source-input <json-file>",
    "Common: --state-version <N> --operation-id <id> --until-seconds <N>"
  ].join("\n"));
};

function parseArgs(args) {
  const parsed = { dryRun: false, connected: false, json: false };
  for (let index = 0; index < args.length; index += 1) {
    const token = args[index];
    if (["--dry-run", "--connected", "--json"].includes(token)) {
      const key = token.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      parsed[key] = true;
      continue;
    }
    if (!token.startsWith("--")) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    const value = args[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`${token} requires a value`);
    parsed[key] = value;
    index += 1;
  }
  return parsed;
}

const options = parseArgs(process.argv.slice(2));
if (!options.pack) {
  usage();
  process.exit(2);
}
if (options.dryRun === options.connected) failMode("choose exactly one of --dry-run or --connected");
if (options.connected && !options.json) failMode("connected mode requires --json");
const mode = options.mode ?? "run";
if (!modes.has(mode)) failMode(`unsupported --mode: ${mode}`);

function failMode(message) {
  console.error(`[scenario-controller] ${message}`);
  usage();
  process.exit(2);
}

const readJson = async (path) => JSON.parse(await readFile(path, "utf8"));
const unique = (items) => new Set(items).size === items.length;
const fail = (message) => { throw new Error(message); };
const log = (message) => console.error(`[scenario-controller] ${message}`);

async function loadPack(directory) {
  const root = resolve(directory);
  const [manifest, zonesFile, entitiesFile, resourcesFile, timelineFile, hiddenTruth] = await Promise.all([
    readJson(resolve(root, "manifest.json")),
    readJson(resolve(root, "zones.json")),
    readJson(resolve(root, "entities.json")),
    readJson(resolve(root, "resources.json")),
    readJson(resolve(root, "timeline.json")),
    readJson(resolve(root, "hidden-truth.json"))
  ]);

  if (!manifest.pack_id || !manifest.pack_version) fail("manifest pack identity is required");
  if (!/^[a-f0-9]{64}$/.test(manifest.pack_digest)) fail("manifest pack_digest must be 64 lowercase hex characters");
  if (!Number.isInteger(manifest.duration_seconds) || manifest.duration_seconds <= 0) fail("duration_seconds must be a positive integer");
  if (Number.isNaN(Date.parse(manifest.scenario_start))) fail("scenario_start must be an ISO timestamp");
  if (!Array.isArray(zonesFile.zones) || !Array.isArray(entitiesFile.entities)) fail("zones and entities arrays are required");
  if (!Array.isArray(resourcesFile.resources) || !Array.isArray(timelineFile.events)) fail("resources and timeline arrays are required");
  if (hiddenTruth.visibility !== "postmortem_only" || !hiddenTruth.canary) fail("hidden truth needs postmortem_only visibility and a canary");

  const zoneIds = zonesFile.zones.map((item) => item.zone_id);
  const entityIds = entitiesFile.entities.map((item) => item.entity_id);
  const resourceIds = resourcesFile.resources.map((item) => item.resource_id);
  const eventIds = timelineFile.events.map((item) => item.event_id);
  const sourceInputIds = timelineFile.events.map((item) => item.source_input?.source_input_id);
  const signalIds = timelineFile.events.map((item) => item.signal_identity?.signal_id);
  if (![zoneIds, entityIds, resourceIds, eventIds, sourceInputIds, signalIds].every(unique)) fail("pack IDs must be unique inside their collection");

  const zones = new Set(zoneIds);
  const entities = new Set(entityIds);
  for (const entity of entitiesFile.entities) {
    if (!zones.has(entity.zone_id)) fail(`unknown entity zone: ${entity.zone_id}`);
  }
  for (const resource of resourcesFile.resources) {
    if (!zones.has(resource.initial_zone_id)) fail(`unknown resource zone: ${resource.initial_zone_id}`);
  }
  for (const event of timelineFile.events) {
    if (!Number.isInteger(event.due_seconds) || event.due_seconds < 0 || event.due_seconds > manifest.duration_seconds) {
      fail(`invalid due_seconds for ${event.event_id}`);
    }
    if (!event.signal_identity?.signal_id || event.signal_identity.revision !== 1) fail(`${event.event_id} needs a stable Signal identity at revision 1`);
    if (!event.source_input?.content?.startsWith("SIMULACIÓN:")) fail(`${event.event_id} must be marked SIMULACIÓN`);
    if (!entities.has(event.source_input.reporter_id)) fail(`unknown reporter in ${event.event_id}`);
    if (!event.source_input.origin_reference) fail(`origin_reference is required in ${event.event_id}`);
    if (!zones.has(event.source_input.declared_location)) fail(`unknown declared zone in ${event.event_id}`);
    if ("signal_id" in event.source_input) fail(`${event.event_id} contains an interpreted Signal`);
  }

  const publicPack = { manifest, zones: zonesFile.zones, entities: entitiesFile.entities, resources: resourcesFile.resources, events: timelineFile.events };
  if (JSON.stringify(publicPack).includes(hiddenTruth.canary)) fail("hidden-truth canary leaked into public pack files");

  return {
    manifest,
    events: [...timelineFile.events].sort((left, right) =>
      left.due_seconds - right.due_seconds || left.event_id.localeCompare(right.event_id)
    ),
    zones: zonesFile.zones.map(({ zone_id, name }) => ({ zone_id, label: name })),
    zoneIds: zones,
    entityIds: entities
  };
}

const pack = await loadPack(options.pack);
const runId = options.runId ?? `run-${pack.manifest.pack_id}`;
let stateVersion = Number(options.stateVersion ?? 0);
if (!Number.isInteger(stateVersion) || stateVersion < 0) fail("--state-version must be a non-negative integer");
const operationId = options.operationId ?? mode;
if (!/^[a-zA-Z0-9._-]+$/.test(operationId)) fail("--operation-id may contain letters, numbers, dot, underscore, and dash");
const gatewayUrl = (options.gatewayUrl ?? process.env.GATEWAY_URL ?? "").replace(/\/$/, "");
if (options.connected && !gatewayUrl) fail("GATEWAY_URL or --gateway-url is required in connected mode");
log(`pack=${pack.manifest.pack_id} run=${runId} mode=${mode} transport=${options.dryRun ? "dry-run" : "connected"}`);

let sequence = 0;
let eventsSent = 0;
const commandId = (suffix) => {
  sequence += 1;
  return `cmd-${runId}-${operationId}-${String(sequence).padStart(3, "0")}-${suffix}`;
};

const atScenarioSecond = (seconds) =>
  new Date(Date.parse(pack.manifest.scenario_start) + seconds * 1000).toISOString();

function command(commandType, payload, suffix, causationId = null) {
  return {
    command_id: commandId(suffix),
    run_id: runId,
    pack_id: pack.manifest.pack_id,
    pack_version: pack.manifest.pack_version,
    pack_digest: pack.manifest.pack_digest,
    expected_state_version: stateVersion,
    actor: "scenario-controller",
    command_type: commandType,
    payload,
    causation_id: causationId
  };
}

async function emit(nextCommand) {
  if (options.dryRun) {
    process.stdout.write(`${JSON.stringify(nextCommand)}\n`);
    stateVersion += 1;
    return;
  }

  const response = await fetch(`${gatewayUrl}/api/commands`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(nextCommand)
  });
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { message: text };
  }
  if (!response.ok || body.error) {
    fail(`command ${nextCommand.command_id} failed (${response.status}): ${JSON.stringify(body)}`);
  }
  if (!Number.isInteger(body.state_version)) fail(`command ${nextCommand.command_id} returned no state_version`);
  stateVersion = body.state_version;
  process.stdout.write(`${JSON.stringify({
    command_id: body.command_id,
    state_version: body.state_version,
    replayed: body.replayed,
    status: "accepted"
  })}\n`);
}

async function advanceTo(seconds, suffix) {
  if (!Number.isInteger(seconds) || seconds < 0 || seconds > pack.manifest.duration_seconds) {
    fail(`scenario second must be between 0 and ${pack.manifest.duration_seconds}`);
  }
  const next = command("advance_clock", { scenario_at: atScenarioSecond(seconds) }, suffix);
  await emit(next);
  return next.command_id;
}

async function emitSourceInput(event, causationId) {
  const scenarioAt = atScenarioSecond(event.due_seconds);
  const payload = {
    signal_identity: event.signal_identity,
    source_input: event.source_input,
    scenario_at: scenarioAt,
    received_at: scenarioAt,
    correlation_id: `corr-${event.event_id}`,
    zone_catalog: pack.zones
  };
  await emit(command("receive_source_input", payload, event.event_id, causationId));
  eventsSent += 1;
}

if (mode === "run") {
  const untilSeconds = Number(options.untilSeconds ?? pack.manifest.duration_seconds);
  if (!Number.isInteger(untilSeconds) || untilSeconds < 0 || untilSeconds > pack.manifest.duration_seconds) {
    fail(`--until-seconds must be between 0 and ${pack.manifest.duration_seconds}`);
  }
  await emit(command("resume_run", {}, "resume"));
  for (const event of pack.events.filter((item) => item.due_seconds <= untilSeconds)) {
    const clockCommandId = await advanceTo(event.due_seconds, `clock-${event.event_id}`);
    await emitSourceInput(event, clockCommandId);
  }
} else if (mode === "advance") {
  await advanceTo(Number(options.toSeconds), "clock-manual");
} else if (mode === "pause") {
  await emit(command("pause_run", {}, "pause"));
} else if (mode === "resume") {
  await emit(command("resume_run", {}, "resume"));
} else if (mode === "inject") {
  if (!options.sourceInput) fail("--mode inject requires --source-input <json-file>");
  const dueSeconds = Number(options.toSeconds);
  const injected = await readJson(resolve(options.sourceInput));
  const event = {
    event_id: `injected-${operationId}`,
    due_seconds: dueSeconds,
    signal_identity: injected.signal_identity,
    source_input: injected.source_input
  };
  if (!event.signal_identity?.signal_id || event.signal_identity.revision !== 1) fail("injection requires signal_identity at revision 1");
  if (!event.source_input?.content?.startsWith("SIMULACIÓN:")) fail("injected content must start with SIMULACIÓN:");
  if ("signal_id" in event.source_input) fail("injected source input cannot contain signal_id");
  if (!pack.entityIds.has(event.source_input.reporter_id)) fail("injected reporter is not in the active pack");
  if (!pack.zoneIds.has(event.source_input.declared_location)) fail("injected source zone is not in the active pack");
  const clockCommandId = await advanceTo(dueSeconds, "clock-injected");
  await emitSourceInput(event, clockCommandId);
}

if (options.connected && options.json && mode === "run") {
  process.stdout.write(`${JSON.stringify({
    run_id: runId,
    pack_id: pack.manifest.pack_id,
    pack_version: pack.manifest.pack_version,
    pack_digest: pack.manifest.pack_digest,
    events_sent: eventsSent,
    state_version: stateVersion,
    status: "timeline_complete"
  })}\n`);
}
```

- [ ] **Step 3: Confirm the CLI is syntax-valid and has no database coupling**

Run:

```bash
node --check scripts/scenario-controller.mjs
! rg -n 'SUPABASE|DATABASE_URL|postgres|from\(["'"'"']|/rest/v1|HAPPYROBOT' scripts/scenario-controller.mjs
```

Expected: both commands exit 0 and print nothing.

### Task 4: Smoke-check deterministic dry runs and pack isolation

**Files:**

- Verify only; do not create repository test files.

- [ ] **Step 1: Produce DANA twice and compare byte-for-byte**

```bash
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo \
  --dry-run > /tmp/dana-commands-1.jsonl
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo \
  --dry-run > /tmp/dana-commands-2.jsonl
diff -u /tmp/dana-commands-1.jsonl /tmp/dana-commands-2.jsonl
```

Expected: `diff` prints nothing. The stream is deterministic.

- [ ] **Step 2: Validate DANA command count, versions, and ownership boundary**

```bash
jq -s -e '
  length == 9
  and .[0].command_type == "resume_run"
  and .[0].expected_state_version == 0
  and .[8].expected_state_version == 8
  and ([.[] | select(.command_type == "receive_source_input")] | length) == 4
  and ([.[] | select(.command_type == "advance_clock")] | length) == 4
  and all(.[]; .actor == "scenario-controller")
  and all(.[]; .pack_id == "dana-demo")
  and all(.[]; .command_type != "upsert_signal")
  and all(.[] | select(.command_type == "receive_source_input");
    .payload.signal_identity.signal_id
    and .payload.signal_identity.revision == 1
    and .payload.source_input.source_input_id
    and .payload.source_input.reporter_id
    and .payload.source_input.declared_location
    and .payload.scenario_at
    and .payload.received_at
    and .payload.correlation_id
    and (.payload.zone_catalog | length) == 3
  )
' /tmp/dana-commands-1.jsonl
! rg -n 'DANA_TRUTH_CANARY_7XQ9|postmortem_only|hidden-truth' /tmp/dana-commands-1.jsonl
```

Expected: both commands exit 0 and the canary search prints nothing.

- [ ] **Step 3: Produce and validate wildfire independently**

```bash
node scripts/scenario-controller.mjs \
  --pack scenario-packs/wildfire-demo \
  --dry-run > /tmp/wildfire-commands.jsonl
jq -s -e '
  length == 9
  and .[0].expected_state_version == 0
  and .[8].expected_state_version == 8
  and all(.[]; .run_id == "run-wildfire-demo")
  and all(.[]; .pack_id == "wildfire-demo")
  and all(.[]; .pack_digest == "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd")
  and all(.[]; .command_type != "upsert_signal")
' /tmp/wildfire-commands.jsonl
! rg -ni 'paiporta|catarroja|water-rescue|inundaci[oó]n|DANA_TRUTH_CANARY|WILDFIRE_TRUTH_CANARY' /tmp/wildfire-commands.jsonl
```

Expected: all commands exit 0; the last search prints nothing. Wildfire contains no DANA IDs, resource names, scenario vocabulary, or hidden-truth canary.

- [ ] **Step 4: Smoke-check pause, resume, advance, and injection without network**

```bash
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo --mode pause --state-version 9 --operation-id pause-smoke --dry-run \
  | jq -e '.command_type == "pause_run" and .expected_state_version == 9'
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo --mode resume --state-version 10 --operation-id resume-smoke --dry-run \
  | jq -e '.command_type == "resume_run" and .expected_state_version == 10'
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo --mode advance --state-version 11 --operation-id advance-smoke --to-seconds 210 --dry-run \
  | jq -e '.command_type == "advance_clock" and .payload.scenario_at == "2026-09-19T10:03:30.000Z"'
printf '%s\n' '{"signal_identity":{"signal_id":"sig-dana-injected-001","revision":1},"source_input":{"source_input_id":"src-dana-injected-001","modality":"webhook","content":"SIMULACIÓN: entrada manual controlada.","reporter_id":"caller-paiporta-01","origin_reference":"manual-smoke-001","declared_location":"paiporta-ground-floor"}}' > /tmp/dana-injected-source.json
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo \
  --mode inject \
  --state-version 12 \
  --operation-id inject-smoke \
  --to-seconds 220 \
  --source-input /tmp/dana-injected-source.json \
  --dry-run > /tmp/dana-injected-commands.jsonl
jq -s -e '
  length == 2
  and .[0].command_type == "advance_clock"
  and .[1].command_type == "receive_source_input"
  and .[1].payload.signal_identity.signal_id == "sig-dana-injected-001"
  and .[1].payload.source_input.source_input_id == "src-dana-injected-001"
  and (.[1].payload.zone_catalog | length) == 3
  and .[1].expected_state_version == 13
' /tmp/dana-injected-commands.jsonl
```

Expected: every `jq -e` exits 0. Injection first advances scenario time and then submits raw source input.

### Task 5: Run one connected DANA smoke through the Gateway

**Files:**

- Verify only; do not create repository test files.

**Prerequisites:** The Supabase/Gateway front has applied its clean seed; `run-dana-demo` is `ready` at `state_version=0`; `GATEWAY_URL` points to the Functions origin without `/api`.

- [ ] **Step 1: Run the complete connected DANA timeline**

```bash
export GATEWAY_URL="${GATEWAY_URL:?Set GATEWAY_URL before the connected smoke}"
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo \
  --run-id run-dana-demo \
  --gateway-url "$GATEWAY_URL" \
  --connected \
  --json \
  > /tmp/dana-connected-receipts.jsonl
jq -s -e '
  length == 10
  and (.[0:9] | all(.[]; .status == "accepted" and .replayed == false))
  and .[0].state_version == 1
  and .[8].state_version == 9
  and .[9].run_id == "run-dana-demo"
  and .[9].pack_id == "dana-demo"
  and .[9].events_sent == 4
  and .[9].state_version == 9
  and .[9].status == "timeline_complete"
' /tmp/dana-connected-receipts.jsonl
```

Expected: the controller exits 0, the first nine lines are accepted command receipts, and the final JSON line is the E2E handshake with four events and state version 9.

- [ ] **Step 2: Verify only raw inputs crossed the boundary**

```bash
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=run-dana-demo" > /tmp/dana-connected-snapshot.json
jq -e '
  .run.status == "running"
  and .run.state_version == 9
  and ([.events[] | select(.event_type == "source_input.received")] | length) == 4
  and ([.events[] | select(.event_type == "clock.advanced")] | length) == 4
  and (.signals | length) == 0
' /tmp/dana-connected-snapshot.json
! rg -n 'DANA_TRUTH_CANARY_7XQ9|postmortem_only' /tmp/dana-connected-snapshot.json
```

Expected: both commands exit 0. `signals` remains empty until Intake processes the outbox; the Scenario Controller did not create one.

- [ ] **Step 3: Exercise connected pause and resume**

```bash
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo \
  --mode pause \
  --run-id run-dana-demo \
  --gateway-url "$GATEWAY_URL" \
  --connected \
  --json \
  --state-version 9 \
  --operation-id connected-pause \
  | jq -e '.state_version == 10 and .status == "accepted"'
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=run-dana-demo" \
  | jq -e '.run.status == "paused" and .run.state_version == 10'
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo \
  --mode resume \
  --run-id run-dana-demo \
  --gateway-url "$GATEWAY_URL" \
  --connected \
  --json \
  --state-version 10 \
  --operation-id connected-resume \
  | jq -e '.state_version == 11 and .status == "accepted"'
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=run-dana-demo" \
  | jq -e '.run.status == "running" and .run.state_version == 11'
```

Expected: all `jq -e` commands exit 0 and pause does not move scenario time.

- [ ] **Step 4: Run final repository checks and stop**

```bash
npm run contracts:check
node --check scripts/scenario-controller.mjs
git diff --check
git status --short -- \
  scenario-packs/dana-demo \
  scenario-packs/wildfire-demo \
  scripts/scenario-controller.mjs
```

Expected: both contract chains pass; syntax and whitespace checks exit 0; the scoped `git status --short` lists the 13 files owned by this plan, regardless of unrelated parallel work elsewhere in the shared worktree. Report file paths and smoke results to the coordinator; do not commit.

## Handoff contract

The front is complete only when:

- two DANA dry runs are byte-identical;
- DANA emits exactly four raw source inputs and four clock advances after one resume command;
- wildfire uses independent IDs, vocabulary, resource, digest, and canary;
- neither command stream contains hidden truth or a v2 Signal authored by the simulator;
- pause, resume, advance, and injection all emit the frozen flat command envelope;
- the exact E2E CLI `--pack ... --run-id ... --gateway-url ... --connected --json` uses only `GATEWAY_URL/api/commands`, reaches `state_version=9` from the clean seed, and writes a final `timeline_complete` summary line;
- every raw input carries its preallocated Signal ID/revision, normalized source transport fields, correlation/timestamps, and the active pack's zone catalog;
- the Gateway snapshot shows raw inputs but no Signal before Intake runs;
- `npm run contracts:check` and `git diff --check` pass;
- no file outside the ownership map changed and no commit was created.
