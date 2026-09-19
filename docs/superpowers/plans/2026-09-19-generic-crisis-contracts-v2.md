# Minimal Parallel Crisis Contracts v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the smallest shared contract needed for DANA and wildfire to use the same `Signal → Incident → Plan → Action → Outcome` pipeline.

**Architecture:** Keep the existing prototypes as v1, define six small JSON Schema files as v2, and use one plain JavaScript smoke-check script. There is no TypeScript layer, generated client, framework, unit-test suite, database, dashboard, or cloud deployment in this increment.

**Tech Stack:** Node.js 24, plain ESM JavaScript, JSON Schema 2020-12, AJV

---

## Explicit delivery constraints

- No TDD and no Vitest/Jest suite.
- One verification run after the parallel work is integrated.
- Minimum custom code: one JavaScript file.
- Parallel workers own non-overlapping files and do not commit independently.
- The coordinator commits once after the contract freeze and once after integration.
- Supabase, HappyRobot, Azure, Scenario Controller, UI, queues, reservations, and real effects remain in subsequent increments.

## Parallel execution map

```text
Wave 0 — coordinator, sequential
  preserve v1 + install AJV + freeze common envelope
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
Wave 1  Lane A     Lane B     Lane C       run simultaneously
        evidence   decisions  examples
        schemas    schemas    DANA + fire
          └──────────┼──────────┘
                     ▼
Wave 2 — coordinator, sequential
  add one validator + run smoke check + document
```

| Lane | Exclusive ownership | Depends on |
| --- | --- | --- |
| Coordinator Wave 0 | `package.json`, `package-lock.json`, `.gitignore`, `schemas/v1/**`, `schemas/v2/common.schema.json` | nothing |
| A — Evidence | `schemas/v2/signal.schema.json`, `schemas/v2/incident.schema.json` | frozen common schema |
| B — Decisions | `schemas/v2/plan.schema.json`, `schemas/v2/action.schema.json`, `schemas/v2/outcome.schema.json` | frozen common schema |
| C — Examples | `examples/contracts/dana-chain.json`, `examples/contracts/wildfire-chain.json` | field matrix in this plan |
| Coordinator Wave 2 | `scripts/validate-contracts.mjs`, `README.md` | lanes A, B, and C complete |

No lane edits another lane's files. Workers report completion without committing; the coordinator performs the integration commit.

## Field matrix frozen before parallel work

Every domain record contains:

```text
contract_version = "2.0.0"
run_id, pack_id, pack_version, pack_digest
scenario_at, received_at, correlation_id, causation_id
```

Domain-specific required fields:

| Contract | Required fields |
| --- | --- |
| Signal | `signal_id`, `revision`, `status`, `modality`, `content`, `claims`, `source`, `location`, `signal_confidence` |
| Incident | `incident_id`, `state`, `canonical_incident_id`, `priority`, `confidence`, `hazard_types`, `zone_ids`, `evidence`, `revisit_at` |
| Plan | `plan_id`, `plan_version`, `supersedes_plan_id`, `status`, `objectives`, `incident_ids`, `action_ids`, `evidence` |
| Action | `action_id`, `plan_id`, `incident_id`, `primitive`, `status`, `actor_id`, `target`, `params`, `action_effect_fingerprint`, `evidence`, `evidence_status`, `reasoning`, `priority`, `risk`, `approval_policy`, `reservation_id` |
| Outcome | `outcome_id`, `action_id`, `attempt_id`, `status`, `summary`, `observed_effects`, `evidence` |

## Wave 0: Freeze the shared boundary

**Files:**

- Modify: `.gitignore`
- Create: `package.json`, `package-lock.json`
- Move: `schemas/*.schema.json` → `schemas/v1/*.schema.json`
- Create: `schemas/v2/common.schema.json`

- [ ] **Step 1: Preserve all prototypes as v1**

```bash
mkdir -p schemas/v1 schemas/v2 examples/contracts scripts
git mv schemas/action.schema.json schemas/v1/action.schema.json
git mv schemas/entity.schema.json schemas/v1/entity.schema.json
git mv schemas/hazard.schema.json schemas/v1/hazard.schema.json
git mv schemas/signal.schema.json schemas/v1/signal.schema.json
git mv schemas/zone.schema.json schemas/v1/zone.schema.json
```

- [ ] **Step 2: Install only the runtime validator**

```bash
npm init -y
npm install ajv ajv-formats
npm pkg set type=module
npm pkg set 'scripts.contracts:check=node scripts/validate-contracts.mjs'
```

Replace `.gitignore` with:

```gitignore
.env
node_modules/
```

- [ ] **Step 3: Freeze the common schema**

Create `schemas/v2/common.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/common.schema.json",
  "$defs": {
    "id": { "type": "string", "minLength": 1 },
    "envelope": {
      "type": "object",
      "required": [
        "contract_version", "run_id", "pack_id", "pack_version", "pack_digest",
        "scenario_at", "received_at", "correlation_id", "causation_id"
      ],
      "properties": {
        "contract_version": { "const": "2.0.0" },
        "run_id": { "$ref": "#/$defs/id" },
        "pack_id": { "$ref": "#/$defs/id" },
        "pack_version": { "type": "string" },
        "pack_digest": { "type": "string", "pattern": "^[a-f0-9]{64}$" },
        "scenario_at": { "type": "string", "format": "date-time" },
        "received_at": { "type": "string", "format": "date-time" },
        "correlation_id": { "$ref": "#/$defs/id" },
        "causation_id": { "type": ["string", "null"] }
      }
    },
    "evidence": {
      "oneOf": [
        {
          "type": "object",
          "required": ["kind", "signal_id", "revision"],
          "properties": {
            "kind": { "const": "signal" },
            "signal_id": { "$ref": "#/$defs/id" },
            "revision": { "type": "integer", "minimum": 1 }
          },
          "additionalProperties": false
        },
        {
          "type": "object",
          "required": ["kind", "incident_id"],
          "properties": {
            "kind": { "const": "incident" },
            "incident_id": { "$ref": "#/$defs/id" }
          },
          "additionalProperties": false
        }
      ]
    }
  }
}
```

- [ ] **Step 4: Commit the frozen boundary before parallel work**

```bash
git add .gitignore package.json package-lock.json schemas
git commit -m "build: freeze minimal crisis contract boundary"
```

## Wave 1A: Evidence schemas

**Files:**

- Create: `schemas/v2/signal.schema.json`
- Create: `schemas/v2/incident.schema.json`

- [ ] **Step 1: Create the Signal schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/signal.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": ["signal_id", "revision", "status", "modality", "content", "claims", "source", "location", "signal_confidence"],
      "properties": {
        "signal_id": { "type": "string" },
        "revision": { "type": "integer", "minimum": 1 },
        "status": { "enum": ["active", "superseded", "retracted"] },
        "modality": { "enum": ["text", "call_transcript", "sensor_reading", "broadcast", "webhook"] },
        "content": { "type": "string", "minLength": 1 },
        "claims": { "type": "array", "items": { "type": "object" } },
        "source": {
          "type": "object",
          "required": ["reporter_id", "origin_reference", "source_cluster_id", "independence_status"],
          "properties": {
            "reporter_id": { "type": ["string", "null"] },
            "origin_reference": { "type": ["string", "null"] },
            "source_cluster_id": { "type": ["string", "null"] },
            "independence_status": { "enum": ["confirmed_independent", "likely_same_origin", "unknown"] }
          },
          "additionalProperties": false
        },
        "location": {
          "type": "object",
          "required": ["zone_id", "precision"],
          "properties": {
            "zone_id": { "type": ["string", "null"] },
            "precision": { "enum": ["exact", "street", "zone", "region", "unknown"] }
          },
          "additionalProperties": false
        },
        "signal_confidence": { "enum": ["high", "medium", "low", "unknown"] }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

- [ ] **Step 2: Create the Incident schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/incident.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": ["incident_id", "state", "canonical_incident_id", "priority", "confidence", "hazard_types", "zone_ids", "evidence", "revisit_at"],
      "properties": {
        "incident_id": { "type": "string" },
        "state": { "enum": ["candidate", "active", "closed", "dismissed", "merged", "split"] },
        "canonical_incident_id": { "type": ["string", "null"] },
        "priority": { "enum": ["P0", "P1", "P2", "P3"] },
        "confidence": { "enum": ["high", "medium", "low", "unknown"] },
        "hazard_types": { "type": "array", "minItems": 1, "items": { "type": "string" } },
        "zone_ids": { "type": "array", "items": { "type": "string" } },
        "evidence": { "type": "array", "minItems": 1, "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/evidence" } },
        "revisit_at": { "type": ["string", "null"] }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

Lane A stops after creating these files and reports their paths to the coordinator.

## Wave 1B: Decision schemas

**Files:**

- Create: `schemas/v2/plan.schema.json`
- Create: `schemas/v2/action.schema.json`
- Create: `schemas/v2/outcome.schema.json`

- [ ] **Step 1: Create the Plan schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/plan.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": ["plan_id", "plan_version", "supersedes_plan_id", "status", "objectives", "incident_ids", "action_ids", "evidence"],
      "properties": {
        "plan_id": { "type": "string" },
        "plan_version": { "type": "integer", "minimum": 1 },
        "supersedes_plan_id": { "type": ["string", "null"] },
        "status": { "enum": ["active", "superseded"] },
        "objectives": { "type": "array", "minItems": 1, "items": { "type": "string" } },
        "incident_ids": { "type": "array", "minItems": 1, "items": { "type": "string" } },
        "action_ids": { "type": "array", "items": { "type": "string" } },
        "evidence": { "type": "array", "minItems": 1, "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/evidence" } }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

- [ ] **Step 2: Create the Action schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/action.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": ["action_id", "plan_id", "incident_id", "primitive", "status", "actor_id", "target", "params", "action_effect_fingerprint", "evidence", "evidence_status", "reasoning", "priority", "risk", "approval_policy", "reservation_id"],
      "properties": {
        "action_id": { "type": "string" },
        "plan_id": { "type": "string" },
        "incident_id": { "type": "string" },
        "primitive": { "enum": ["allocate_resource", "release_resource", "update_entity", "update_edge", "contact_entity", "broadcast_message", "create_task", "schedule_review", "request_approval", "record_outcome"] },
        "status": { "enum": ["proposed", "pending_approval", "approved", "dispatching", "delivered", "accepted", "executing", "completed", "rejected", "timed_out", "unknown", "failed", "canceled"] },
        "actor_id": { "type": "string" },
        "target": { "type": "object" },
        "params": { "type": "object" },
        "action_effect_fingerprint": { "type": "string" },
        "evidence": { "type": "array", "minItems": 1, "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/evidence" } },
        "evidence_status": { "enum": ["valid", "needs_reassessment", "invalidated"] },
        "reasoning": { "type": "string", "minLength": 1 },
        "priority": { "enum": ["P0", "P1", "P2", "P3"] },
        "risk": { "enum": ["low", "medium", "high"] },
        "approval_policy": { "enum": ["automatic", "human_required"] },
        "reservation_id": { "type": ["string", "null"] }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

- [ ] **Step 3: Create the Outcome schema**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/outcome.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": ["outcome_id", "action_id", "attempt_id", "status", "summary", "observed_effects", "evidence"],
      "properties": {
        "outcome_id": { "type": "string" },
        "action_id": { "type": "string" },
        "attempt_id": { "type": "string" },
        "status": { "enum": ["success", "partial", "failed", "no_response", "unknown"] },
        "summary": { "type": "string", "minLength": 1 },
        "observed_effects": { "type": "object" },
        "evidence": { "type": "array", "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/evidence" } }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

Lane B stops after creating these files and reports their paths to the coordinator.

## Wave 1C: Two cross-scenario examples

**Files:**

- Create: `examples/contracts/dana-chain.json`
- Create: `examples/contracts/wildfire-chain.json`

- [ ] **Step 1: Create both chains with this exact identity mapping**

| Value | DANA | Wildfire |
| --- | --- | --- |
| `run_id` | `run-dana-demo` | `run-wildfire-demo` |
| `pack_id` | `dana-demo` | `wildfire-demo` |
| `pack_digest` | 64 `c` characters | 64 `d` characters |
| `signal_id` | `sig-dana-001` | `sig-fire-001` |
| `incident_id` | `inc-dana-001` | `inc-fire-001` |
| `plan_id` | `plan-dana-001` | `plan-fire-001` |
| `action_id` | `act-dana-001` | `act-fire-001` |
| `outcome_id` | `out-dana-001` | `out-fire-001` |
| hazard | `flood` | `wildfire` |
| zone | `paiporta` | `pinar-norte` |
| primitive | `allocate_resource` | `broadcast_message` |

Each file is one object with keys `signal`, `incident`, `plan`, `action`, and `outcome`. Every record repeats its chain's frozen envelope. References must form this exact graph:

```text
Signal revision 1 ← evidence in Incident, Plan, Action and Outcome
Incident ← Plan.incident_ids and Action.incident_id
Plan ← Action.plan_id
Action ← Plan.action_ids and Outcome.action_id
```

Use `active` Signal and Incident states, an `active` Plan, an `approved` Action with `evidence_status=valid`, and a successful Outcome. Neither file contains `hidden_truth`, flood-only field names, or fields outside its active hazard.

- [ ] **Step 2: Create the DANA chain**

Create `examples/contracts/dana-chain.json`:

```json
{
  "signal": {
    "contract_version": "2.0.0", "run_id": "run-dana-demo", "pack_id": "dana-demo", "pack_version": "1.0.0", "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "scenario_at": "2026-09-19T10:00:00Z", "received_at": "2026-09-19T09:00:00Z", "correlation_id": "corr-dana", "causation_id": null,
    "signal_id": "sig-dana-001", "revision": 1, "status": "active", "modality": "sensor_reading", "content": "Water is rising in the Paiporta underpass",
    "claims": [{ "claim_type": "hazard_observation", "value": "flood" }],
    "source": { "reporter_id": "sensor-paiporta", "origin_reference": "reading-dana-001", "source_cluster_id": "cluster-dana-001", "independence_status": "confirmed_independent" },
    "location": { "zone_id": "paiporta", "precision": "exact" }, "signal_confidence": "high"
  },
  "incident": {
    "contract_version": "2.0.0", "run_id": "run-dana-demo", "pack_id": "dana-demo", "pack_version": "1.0.0", "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "scenario_at": "2026-09-19T10:01:00Z", "received_at": "2026-09-19T09:01:00Z", "correlation_id": "corr-dana", "causation_id": "sig-dana-001",
    "incident_id": "inc-dana-001", "state": "active", "canonical_incident_id": "inc-dana-001", "priority": "P0", "confidence": "high",
    "hazard_types": ["flood"], "zone_ids": ["paiporta"], "evidence": [{ "kind": "signal", "signal_id": "sig-dana-001", "revision": 1 }], "revisit_at": "2026-09-19T10:06:00Z"
  },
  "plan": {
    "contract_version": "2.0.0", "run_id": "run-dana-demo", "pack_id": "dana-demo", "pack_version": "1.0.0", "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "scenario_at": "2026-09-19T10:02:00Z", "received_at": "2026-09-19T09:02:00Z", "correlation_id": "corr-dana", "causation_id": "inc-dana-001",
    "plan_id": "plan-dana-001", "plan_version": 1, "supersedes_plan_id": null, "status": "active", "objectives": ["Protect people at the underpass"],
    "incident_ids": ["inc-dana-001"], "action_ids": ["act-dana-001"], "evidence": [{ "kind": "signal", "signal_id": "sig-dana-001", "revision": 1 }]
  },
  "action": {
    "contract_version": "2.0.0", "run_id": "run-dana-demo", "pack_id": "dana-demo", "pack_version": "1.0.0", "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "scenario_at": "2026-09-19T10:02:00Z", "received_at": "2026-09-19T09:02:00Z", "correlation_id": "corr-dana", "causation_id": "plan-dana-001",
    "action_id": "act-dana-001", "plan_id": "plan-dana-001", "incident_id": "inc-dana-001", "primitive": "allocate_resource", "status": "approved", "actor_id": "rescue-team",
    "target": { "zone_ids": ["paiporta"] }, "params": { "units": 1 }, "action_effect_fingerprint": "allocate:rescue-team:paiporta:1",
    "evidence": [{ "kind": "signal", "signal_id": "sig-dana-001", "revision": 1 }], "evidence_status": "valid", "reasoning": "Independent sensor evidence shows immediate danger.",
    "priority": "P0", "risk": "medium", "approval_policy": "automatic", "reservation_id": null
  },
  "outcome": {
    "contract_version": "2.0.0", "run_id": "run-dana-demo", "pack_id": "dana-demo", "pack_version": "1.0.0", "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "scenario_at": "2026-09-19T10:05:00Z", "received_at": "2026-09-19T09:05:00Z", "correlation_id": "corr-dana", "causation_id": "act-dana-001",
    "outcome_id": "out-dana-001", "action_id": "act-dana-001", "attempt_id": "attempt-dana-001", "status": "success", "summary": "The rescue team reached Paiporta.",
    "observed_effects": { "reached_zone": "paiporta" }, "evidence": [{ "kind": "signal", "signal_id": "sig-dana-001", "revision": 1 }]
  }
}
```

- [ ] **Step 3: Create the wildfire chain**

Create `examples/contracts/wildfire-chain.json`:

```json
{
  "signal": {
    "contract_version": "2.0.0", "run_id": "run-wildfire-demo", "pack_id": "wildfire-demo", "pack_version": "1.0.0", "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "scenario_at": "2026-09-19T10:00:00Z", "received_at": "2026-09-19T09:00:00Z", "correlation_id": "corr-fire", "causation_id": null,
    "signal_id": "sig-fire-001", "revision": 1, "status": "active", "modality": "sensor_reading", "content": "A thermal sensor detects an active fire front",
    "claims": [{ "claim_type": "hazard_observation", "value": "wildfire" }],
    "source": { "reporter_id": "sensor-pinar", "origin_reference": "reading-fire-001", "source_cluster_id": "cluster-fire-001", "independence_status": "confirmed_independent" },
    "location": { "zone_id": "pinar-norte", "precision": "exact" }, "signal_confidence": "high"
  },
  "incident": {
    "contract_version": "2.0.0", "run_id": "run-wildfire-demo", "pack_id": "wildfire-demo", "pack_version": "1.0.0", "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "scenario_at": "2026-09-19T10:01:00Z", "received_at": "2026-09-19T09:01:00Z", "correlation_id": "corr-fire", "causation_id": "sig-fire-001",
    "incident_id": "inc-fire-001", "state": "active", "canonical_incident_id": "inc-fire-001", "priority": "P0", "confidence": "high",
    "hazard_types": ["wildfire"], "zone_ids": ["pinar-norte"], "evidence": [{ "kind": "signal", "signal_id": "sig-fire-001", "revision": 1 }], "revisit_at": "2026-09-19T10:06:00Z"
  },
  "plan": {
    "contract_version": "2.0.0", "run_id": "run-wildfire-demo", "pack_id": "wildfire-demo", "pack_version": "1.0.0", "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "scenario_at": "2026-09-19T10:02:00Z", "received_at": "2026-09-19T09:02:00Z", "correlation_id": "corr-fire", "causation_id": "inc-fire-001",
    "plan_id": "plan-fire-001", "plan_version": 1, "supersedes_plan_id": null, "status": "active", "objectives": ["Warn the exposed northern area"],
    "incident_ids": ["inc-fire-001"], "action_ids": ["act-fire-001"], "evidence": [{ "kind": "signal", "signal_id": "sig-fire-001", "revision": 1 }]
  },
  "action": {
    "contract_version": "2.0.0", "run_id": "run-wildfire-demo", "pack_id": "wildfire-demo", "pack_version": "1.0.0", "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "scenario_at": "2026-09-19T10:02:00Z", "received_at": "2026-09-19T09:02:00Z", "correlation_id": "corr-fire", "causation_id": "plan-fire-001",
    "action_id": "act-fire-001", "plan_id": "plan-fire-001", "incident_id": "inc-fire-001", "primitive": "broadcast_message", "status": "approved", "actor_id": "civil-protection",
    "target": { "zone_ids": ["pinar-norte"] }, "params": { "message": "Simulation: move away from the northern forest edge" }, "action_effect_fingerprint": "broadcast:civil-protection:pinar-norte",
    "evidence": [{ "kind": "signal", "signal_id": "sig-fire-001", "revision": 1 }], "evidence_status": "valid", "reasoning": "Independent thermal evidence supports a reversible warning.",
    "priority": "P0", "risk": "low", "approval_policy": "automatic", "reservation_id": null
  },
  "outcome": {
    "contract_version": "2.0.0", "run_id": "run-wildfire-demo", "pack_id": "wildfire-demo", "pack_version": "1.0.0", "pack_digest": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "scenario_at": "2026-09-19T10:05:00Z", "received_at": "2026-09-19T09:05:00Z", "correlation_id": "corr-fire", "causation_id": "act-fire-001",
    "outcome_id": "out-fire-001", "action_id": "act-fire-001", "attempt_id": "attempt-fire-001", "status": "success", "summary": "The warning was delivered to Pinar Norte.",
    "observed_effects": { "delivered_zone": "pinar-norte" }, "evidence": [{ "kind": "signal", "signal_id": "sig-fire-001", "revision": 1 }]
  }
}
```

Lane C stops after creating these two data files and reports their paths to the coordinator.

## Wave 2: Integrate once and smoke-check

**Files:**

- Create: `scripts/validate-contracts.mjs`
- Modify: `README.md`

- [ ] **Step 1: Add the only custom JavaScript file**

Create `scripts/validate-contracts.mjs`:

```javascript
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const schemaRoot = resolve("schemas/v2");
const schemaFiles = {
  signal: "signal.schema.json",
  incident: "incident.schema.json",
  plan: "plan.schema.json",
  action: "action.schema.json",
  outcome: "outcome.schema.json"
};
const exampleFiles = [
  "examples/contracts/dana-chain.json",
  "examples/contracts/wildfire-chain.json"
];
const identityFields = ["contract_version", "run_id", "pack_id", "pack_version", "pack_digest"];

const load = async (file) => JSON.parse(await readFile(file, "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
ajv.addSchema(await load(resolve(schemaRoot, "common.schema.json")));
for (const file of Object.values(schemaFiles)) {
  ajv.addSchema(await load(resolve(schemaRoot, file)));
}

const failures = [];
const signalEvidenceMatches = (evidence, signal) =>
  Array.isArray(evidence) && evidence.some((item) =>
    item.kind === "signal"
    && item.signal_id === signal.signal_id
    && item.revision === signal.revision
  );

for (const exampleFile of exampleFiles) {
  const chain = await load(resolve(exampleFile));
  const failureCountBeforeChain = failures.length;

  for (const [kind, schemaFile] of Object.entries(schemaFiles)) {
    const validate = ajv.getSchema(`https://valte.dev/schemas/v2/${schemaFile}`);
    if (!validate(chain[kind])) {
      failures.push(`${exampleFile} ${kind}: ${ajv.errorsText(validate.errors)}`);
    }
  }

  for (const kind of Object.keys(schemaFiles).filter((kind) => kind !== "signal")) {
    for (const field of identityFields) {
      if (chain[kind][field] !== chain.signal[field]) {
        failures.push(`${exampleFile}: ${kind}.${field} differs from Signal`);
      }
    }
  }

  for (const kind of ["incident", "plan", "action", "outcome"]) {
    if (!signalEvidenceMatches(chain[kind].evidence, chain.signal)) {
      failures.push(`${exampleFile}: ${kind} lacks exact Signal revision evidence`);
    }
  }

  if (!chain.plan.incident_ids.includes(chain.incident.incident_id)) {
    failures.push(`${exampleFile}: Plan does not include Incident`);
  }
  if (!chain.plan.action_ids.includes(chain.action.action_id)) {
    failures.push(`${exampleFile}: Plan does not include Action`);
  }
  if (chain.action.plan_id !== chain.plan.plan_id) {
    failures.push(`${exampleFile}: Action does not reference Plan`);
  }
  if (chain.action.incident_id !== chain.incident.incident_id) {
    failures.push(`${exampleFile}: Action does not reference Incident`);
  }
  if (chain.outcome.action_id !== chain.action.action_id) {
    failures.push(`${exampleFile}: Outcome does not reference Action`);
  }

  if (failures.length === failureCountBeforeChain) {
    console.log(`PASS ${chain.pack_id}: Signal → Incident → Plan → Action → Outcome`);
  }
}

if (failures.length > 0) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
}
```

- [ ] **Step 2: Run the single integration verification**

```bash
npm run contracts:check
git diff --check
```

Expected:

```text
PASS dana-demo: Signal → Incident → Plan → Action → Outcome
PASS wildfire-demo: Signal → Incident → Plan → Action → Outcome
```

If AJV or a reference check fails, the coordinator fixes only the owning lane's file and reruns these two commands. Do not add a test framework.

- [ ] **Step 3: Document only the commands users need**

Append to `README.md`:

````markdown
## Generic crisis contracts v2

The minimal v2 foundation validates the same operational chain for DANA and
wildfire:

```text
Signal → Incident → Plan → Action → Outcome
```

Run it with:

```bash
npm install
npm run contracts:check
```

The original DANA-oriented prototypes remain under `schemas/v1/`. The generic
contracts used by new work live under `schemas/v2/`.
````

- [ ] **Step 4: Commit the integrated increment**

```bash
git add schemas/v2 examples/contracts scripts/validate-contracts.mjs README.md
git commit -m "feat: add minimal generic crisis contracts"
```

## Completion check

- Only one custom JavaScript file exists.
- No test framework, TypeScript compiler, build system, database, or UI has been added.
- DANA and wildfire pass the same five schemas.
- Every object carries run and immutable pack identity.
- Exact Signal revisions remain traceable through Incident, Plan, Action, and Outcome.
- The two commits leave a clean worktree.
