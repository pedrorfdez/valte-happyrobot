# Generic Crisis Contracts v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and test the smallest reusable foundation of the crisis system: versioned v2 contracts for `Signal → Incident → Plan → Action → Outcome`, plus a CLI that validates DANA and wildfire payloads with the same schemas.

**Architecture:** JSON Schema 2020-12 is the runtime contract authority. A small TypeScript registry compiles the schemas with AJV, adds cross-object validation for a complete operational chain, and exposes a CLI for fixtures and future HappyRobot payloads. Existing flood-specific schemas remain available under `schemas/v1/`; no database, workflow, UI, or external effect is introduced in this phase.

**Tech Stack:** Node.js 24, TypeScript, AJV 2020, `ajv-formats`, Vitest, `tsx`, JSON Schema 2020-12

---

## Scope boundary and implementation sequence

This specification is too broad for one safe implementation plan. Deliver it through independently testable plans in this order:

1. **This plan:** generic v2 contracts and contract-chain validator.
2. Scenario Pack loader, digest, preflight, observable context, and scenario clock.
3. Supabase schema, transactional State Gateway, outbox, Event Router, reservations, and terminal fence.
4. HappyRobot Intake, Command, and Coordination workflows.
5. Azure Static Web Apps dashboard, approvals, and operator controls.
6. Six E2E Scenario Packs, real-channel fallbacks, postmortem, and live-demo rehearsal.

This plan is complete when both a DANA chain and a wildfire chain validate with identical generic schemas, cross-pack contamination fails, and the old v1 contracts remain accessible.

## File map

- Modify `.gitignore`: ignore Node build and test output.
- Create `package.json` and `package-lock.json`: project commands and pinned dependencies.
- Create `tsconfig.json`: strict ESM TypeScript configuration.
- Move `schemas/*.schema.json` to `schemas/v1/`: preserve the prototypes without accepting them as v2.
- Create `schemas/v2/common.schema.json`: shared envelope, identifiers, and typed evidence references.
- Create `schemas/v2/signal.schema.json`: observable, revisioned evidence.
- Create `schemas/v2/incident.schema.json`: operational hypotheses and canonicalization state.
- Create `schemas/v2/plan.schema.json`: immutable global plan revisions.
- Create `schemas/v2/action.schema.json`: action intent and lifecycle.
- Create `schemas/v2/outcome.schema.json`: append-only attempt outcomes.
- Create `src/contracts/registry.ts`: compile and execute JSON Schema plus record-level semantics.
- Create `src/contracts/chain.ts`: validate identity consistency and references across a complete chain.
- Create `src/cli/validate-contract.ts`: validate one JSON payload from the terminal.
- Create `tests/contracts/signal.test.ts`: Signal contract tests.
- Create `tests/contracts/domain.test.ts`: Incident, Plan, Action, and Outcome tests.
- Create `tests/contracts/chain.test.ts`: DANA/wildfire generality and contamination tests.
- Create `tests/contracts/cli.test.ts`: CLI behavior tests.
- Create `tests/fixtures/contract-chains.ts`: two generic domain chains using different hazards.
- Create `examples/contracts/dana-signal.json`: human-readable CLI example.
- Modify `README.md`: document the phase, commands, and v1/v2 boundary.

### Task 1: Bootstrap the TypeScript contract workspace

**Files:**

- Modify: `.gitignore`
- Create: `package.json`
- Create: `package-lock.json`
- Create: `tsconfig.json`

- [ ] **Step 1: Initialize the package and install exact dependencies through npm**

Run:

```bash
npm init -y
npm install ajv ajv-formats
npm install --save-dev typescript vitest tsx @types/node
npm pkg set type=module
npm pkg set 'scripts.test=vitest run'
npm pkg set 'scripts.test:watch=vitest'
npm pkg set 'scripts.typecheck=tsc --noEmit'
npm pkg set 'scripts.contracts:check=tsx src/cli/validate-contract.ts'
```

Expected: npm creates `package.json` and `package-lock.json`; all commands exit `0`.

- [ ] **Step 2: Add the strict compiler configuration**

Create `tsconfig.json` with:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "types": ["node", "vitest/globals"]
  },
  "include": ["src/**/*.ts", "tests/**/*.ts"]
}
```

- [ ] **Step 3: Ignore generated Node artifacts**

Replace `.gitignore` with:

```gitignore
.env
node_modules/
dist/
coverage/
```

- [ ] **Step 4: Verify the empty workspace**

Run:

```bash
npm run typecheck
npm test -- --passWithNoTests
```

Expected: both commands exit `0`; Vitest reports no test files without failing.

- [ ] **Step 5: Commit the workspace**

```bash
git add .gitignore package.json package-lock.json tsconfig.json
git commit -m "build: initialize crisis contract workspace"
```

### Task 2: Preserve v1 and implement the v2 Signal contract

**Files:**

- Move: `schemas/action.schema.json` → `schemas/v1/action.schema.json`
- Move: `schemas/entity.schema.json` → `schemas/v1/entity.schema.json`
- Move: `schemas/hazard.schema.json` → `schemas/v1/hazard.schema.json`
- Move: `schemas/signal.schema.json` → `schemas/v1/signal.schema.json`
- Move: `schemas/zone.schema.json` → `schemas/v1/zone.schema.json`
- Create: `schemas/v2/common.schema.json`
- Create: `schemas/v2/signal.schema.json`
- Create: `src/contracts/registry.ts`
- Test: `tests/contracts/signal.test.ts`

- [ ] **Step 1: Move the prototype schemas without editing them**

Run:

```bash
mkdir -p schemas/v1 schemas/v2
git mv schemas/action.schema.json schemas/v1/action.schema.json
git mv schemas/entity.schema.json schemas/v1/entity.schema.json
git mv schemas/hazard.schema.json schemas/v1/hazard.schema.json
git mv schemas/signal.schema.json schemas/v1/signal.schema.json
git mv schemas/zone.schema.json schemas/v1/zone.schema.json
```

Expected: `git status --short` reports five renames.

- [ ] **Step 2: Write the failing Signal tests**

Create `tests/contracts/signal.test.ts` with:

```typescript
import { describe, expect, it } from "vitest";

import { createContractRegistry } from "../../src/contracts/registry.js";

const digest = "a".repeat(64);

function validSignal(): Record<string, unknown> {
  return {
    contract_version: "2.0.0",
    signal_id: "sig-dana-001",
    revision: 1,
    status: "active",
    run_id: "run-dana-001",
    pack_id: "dana-demo",
    pack_version: "1.0.0",
    pack_digest: digest,
    scenario_at: "2026-09-19T10:00:00.000Z",
    received_at: "2026-09-19T09:00:00.000Z",
    correlation_id: "corr-001",
    causation_id: null,
    modality: "call_transcript",
    content: "Hay agua entrando en el paso inferior de Paiporta",
    claims: [{ claim_type: "hazard_observation", value: "flooding" }],
    source: {
      reporter_id: "caller-001",
      origin_reference: "call-001",
      source_trust_snapshot: "unknown",
      source_cluster_id: "cluster-001",
      independence_status: "confirmed_independent",
      content_fingerprint: "sha256:signal-001"
    },
    location: { zone_id: "paiporta", precision: "zone" },
    signal_confidence: "medium"
  };
}

describe("Signal v2", () => {
  const registry = createContractRegistry();

  it("accepts a generic observable signal", () => {
    expect(registry.validate("signal", validSignal())).toEqual({
      valid: true,
      errors: []
    });
  });

  it("rejects a missing pack digest", () => {
    const signal = validSignal();
    delete signal.pack_digest;

    const result = registry.validate("signal", signal);

    expect(result.valid).toBe(false);
    expect(result.errors.join(" ")).toContain("pack_digest");
  });

  it("rejects hidden truth in an observable contract", () => {
    const signal = { ...validSignal(), hidden_truth: { flooded: true } };

    const result = registry.validate("signal", signal);

    expect(result.valid).toBe(false);
    expect(result.errors.join(" ")).toContain("unevaluated");
  });
});
```

- [ ] **Step 3: Run the Signal tests to verify they fail**

Run:

```bash
npm test -- tests/contracts/signal.test.ts
```

Expected: FAIL because `src/contracts/registry.ts` does not exist.

- [ ] **Step 4: Create the common v2 definitions**

Create `schemas/v2/common.schema.json` with:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/common.schema.json",
  "$defs": {
    "id": {
      "type": "string",
      "minLength": 1,
      "maxLength": 160,
      "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    },
    "digest": {
      "type": "string",
      "pattern": "^[a-f0-9]{64}$"
    },
    "envelope": {
      "type": "object",
      "required": [
        "contract_version",
        "run_id",
        "pack_id",
        "pack_version",
        "pack_digest",
        "scenario_at",
        "received_at",
        "correlation_id",
        "causation_id"
      ],
      "properties": {
        "contract_version": { "const": "2.0.0" },
        "run_id": { "$ref": "#/$defs/id" },
        "pack_id": { "$ref": "#/$defs/id" },
        "pack_version": { "type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$" },
        "pack_digest": { "$ref": "#/$defs/digest" },
        "scenario_at": { "type": "string", "format": "date-time" },
        "received_at": { "type": "string", "format": "date-time" },
        "correlation_id": { "$ref": "#/$defs/id" },
        "causation_id": {
          "oneOf": [{ "$ref": "#/$defs/id" }, { "type": "null" }]
        }
      }
    },
    "evidenceRef": {
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
        },
        {
          "type": "object",
          "required": ["kind", "outcome_id"],
          "properties": {
            "kind": { "const": "outcome" },
            "outcome_id": { "$ref": "#/$defs/id" }
          },
          "additionalProperties": false
        },
        {
          "type": "object",
          "required": ["kind", "human_directive_id"],
          "properties": {
            "kind": { "const": "human_directive" },
            "human_directive_id": { "$ref": "#/$defs/id" }
          },
          "additionalProperties": false
        }
      ]
    }
  }
}
```

- [ ] **Step 5: Create the Signal v2 schema**

Create `schemas/v2/signal.schema.json` with:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/signal.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": [
        "signal_id",
        "revision",
        "status",
        "modality",
        "content",
        "claims",
        "source",
        "location",
        "signal_confidence"
      ],
      "properties": {
        "signal_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "revision": { "type": "integer", "minimum": 1 },
        "status": { "enum": ["active", "superseded", "retracted"] },
        "modality": {
          "enum": ["text", "call_transcript", "sensor_reading", "broadcast", "webhook"]
        },
        "content": { "type": "string", "minLength": 1 },
        "claims": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["claim_type", "value"],
            "properties": {
              "claim_type": { "type": "string", "minLength": 1 },
              "value": {}
            },
            "additionalProperties": false
          }
        },
        "source": {
          "type": "object",
          "required": [
            "reporter_id",
            "origin_reference",
            "source_trust_snapshot",
            "source_cluster_id",
            "independence_status",
            "content_fingerprint"
          ],
          "properties": {
            "reporter_id": { "type": ["string", "null"] },
            "origin_reference": { "type": ["string", "null"] },
            "source_trust_snapshot": { "enum": ["high", "medium", "low", "unknown"] },
            "source_cluster_id": { "type": ["string", "null"] },
            "independence_status": {
              "enum": ["confirmed_independent", "likely_same_origin", "unknown"]
            },
            "content_fingerprint": { "type": "string", "minLength": 1 }
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

- [ ] **Step 6: Implement the initial contract registry**

Create `src/contracts/registry.ts` with:

```typescript
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

export type ContractKind = "signal";

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

const schemaFiles: Record<ContractKind | "common", string> = {
  common: "common.schema.json",
  signal: "signal.schema.json"
};

function readSchema(schemaRoot: string, file: string): object {
  return JSON.parse(readFileSync(resolve(schemaRoot, file), "utf8")) as object;
}

export function createContractRegistry(
  schemaRoot = resolve(process.cwd(), "schemas/v2")
) {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);

  ajv.addSchema(readSchema(schemaRoot, schemaFiles.common));
  ajv.addSchema(readSchema(schemaRoot, schemaFiles.signal));

  return {
    validate(kind: ContractKind, value: unknown): ValidationResult {
      const schemaId = `https://valte.dev/schemas/v2/${schemaFiles[kind]}`;
      const validate = ajv.getSchema(schemaId);
      if (!validate) {
        return { valid: false, errors: [`schema not registered: ${kind}`] };
      }

      const valid = validate(value);
      const errors = (validate.errors ?? []).map(
        (error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`
      );
      return { valid: Boolean(valid), errors };
    }
  };
}

export type ContractRegistry = ReturnType<typeof createContractRegistry>;
```

- [ ] **Step 7: Run the Signal tests and typecheck**

Run:

```bash
npm test -- tests/contracts/signal.test.ts
npm run typecheck
```

Expected: 3 tests pass; TypeScript exits `0`.

- [ ] **Step 8: Commit the v1 boundary and Signal contract**

```bash
git add schemas src/contracts/registry.ts tests/contracts/signal.test.ts
git commit -m "feat: add versioned Signal v2 contract"
```

### Task 3: Add Incident, Plan, Action, and Outcome contracts

**Files:**

- Create: `schemas/v2/incident.schema.json`
- Create: `schemas/v2/plan.schema.json`
- Create: `schemas/v2/action.schema.json`
- Create: `schemas/v2/outcome.schema.json`
- Modify: `src/contracts/registry.ts`
- Test: `tests/contracts/domain.test.ts`

- [ ] **Step 1: Write failing domain contract tests**

Create `tests/contracts/domain.test.ts` with:

```typescript
import { describe, expect, it } from "vitest";

import { createContractRegistry } from "../../src/contracts/registry.js";

const envelope = {
  contract_version: "2.0.0",
  run_id: "run-001",
  pack_id: "generic-demo",
  pack_version: "1.0.0",
  pack_digest: "b".repeat(64),
  scenario_at: "2026-09-19T10:01:00.000Z",
  received_at: "2026-09-19T09:01:00.000Z",
  correlation_id: "corr-001",
  causation_id: "sig-001"
};

const evidence = [{ kind: "signal", signal_id: "sig-001", revision: 1 }];

describe("core domain contracts", () => {
  const registry = createContractRegistry();

  it("accepts a canonical active Incident", () => {
    const result = registry.validate("incident", {
      ...envelope,
      incident_id: "inc-001",
      state: "active",
      canonical_incident_id: "inc-001",
      priority: "P0",
      confidence: "high",
      hazard_types: ["flood"],
      zone_ids: ["zone-a"],
      evidence,
      revisit_at: "2026-09-19T10:06:00.000Z"
    });

    expect(result).toEqual({ valid: true, errors: [] });
  });

  it("rejects a merged Incident without another canonical id", () => {
    const result = registry.validate("incident", {
      ...envelope,
      incident_id: "inc-duplicate",
      state: "merged",
      canonical_incident_id: "inc-duplicate",
      priority: "P1",
      confidence: "medium",
      hazard_types: ["flood"],
      zone_ids: ["zone-a"],
      evidence,
      revisit_at: null
    });

    expect(result.valid).toBe(false);
    expect(result.errors.join(" ")).toContain("canonical_incident_id");
  });

  it("requires an exact Signal revision in Action evidence", () => {
    const result = registry.validate("action", {
      ...envelope,
      action_id: "act-001",
      plan_id: "plan-001",
      incident_id: "inc-001",
      primitive: "allocate_resource",
      status: "proposed",
      actor_id: "fire-unit",
      target: { zone_ids: ["zone-a"], entity_ids: [] },
      params: { units: 1 },
      action_effect_fingerprint: "sha256:effect-001",
      evidence: [{ kind: "signal", signal_id: "sig-001" }],
      evidence_status: "valid",
      reasoning: "A confirmed life threat needs the nearest valid unit.",
      priority: "P0",
      risk: "high",
      approval_policy: "human_required",
      reservation_id: null
    });

    expect(result.valid).toBe(false);
    expect(result.errors.join(" ")).toContain("revision");
  });
});
```

- [ ] **Step 2: Run the domain tests to verify they fail**

Run:

```bash
npm test -- tests/contracts/domain.test.ts
```

Expected: FAIL because `incident` and `action` are not registered contract kinds.

- [ ] **Step 3: Create the Incident schema**

Create `schemas/v2/incident.schema.json` with:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/incident.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": [
        "incident_id",
        "state",
        "canonical_incident_id",
        "priority",
        "confidence",
        "hazard_types",
        "zone_ids",
        "evidence",
        "revisit_at"
      ],
      "properties": {
        "incident_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "state": { "enum": ["candidate", "active", "closed", "dismissed", "merged", "split"] },
        "canonical_incident_id": {
          "oneOf": [
            { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
            { "type": "null" }
          ]
        },
        "priority": { "enum": ["P0", "P1", "P2", "P3"] },
        "confidence": { "enum": ["high", "medium", "low", "unknown"] },
        "hazard_types": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": { "type": "string", "minLength": 1 }
        },
        "zone_ids": {
          "type": "array",
          "uniqueItems": true,
          "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" }
        },
        "evidence": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/evidenceRef" }
        },
        "revisit_at": { "type": ["string", "null"], "format": "date-time" }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

- [ ] **Step 4: Create the Plan schema**

Create `schemas/v2/plan.schema.json` with:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/plan.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": [
        "plan_id",
        "plan_version",
        "supersedes_plan_id",
        "status",
        "objectives",
        "assumptions",
        "incident_ids",
        "action_ids",
        "evidence",
        "active_human_directive_ids"
      ],
      "properties": {
        "plan_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "plan_version": { "type": "integer", "minimum": 1 },
        "supersedes_plan_id": {
          "oneOf": [
            { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
            { "type": "null" }
          ]
        },
        "status": { "enum": ["active", "superseded"] },
        "objectives": { "type": "array", "minItems": 1, "items": { "type": "string", "minLength": 1 } },
        "assumptions": { "type": "array", "items": { "type": "string", "minLength": 1 } },
        "incident_ids": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" }
        },
        "action_ids": {
          "type": "array",
          "uniqueItems": true,
          "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" }
        },
        "evidence": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/evidenceRef" }
        },
        "active_human_directive_ids": {
          "type": "array",
          "uniqueItems": true,
          "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" }
        }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

- [ ] **Step 5: Create the Action schema**

Create `schemas/v2/action.schema.json` with:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/action.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": [
        "action_id",
        "plan_id",
        "incident_id",
        "primitive",
        "status",
        "actor_id",
        "target",
        "params",
        "action_effect_fingerprint",
        "evidence",
        "evidence_status",
        "reasoning",
        "priority",
        "risk",
        "approval_policy",
        "reservation_id"
      ],
      "properties": {
        "action_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "plan_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "incident_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "primitive": {
          "enum": [
            "allocate_resource",
            "release_resource",
            "update_entity",
            "update_edge",
            "contact_entity",
            "broadcast_message",
            "create_task",
            "schedule_review",
            "request_approval",
            "record_outcome"
          ]
        },
        "status": {
          "enum": [
            "proposed",
            "pending_approval",
            "approved",
            "dispatching",
            "delivered",
            "accepted",
            "executing",
            "completed",
            "rejected",
            "timed_out",
            "unknown",
            "failed",
            "canceled"
          ]
        },
        "actor_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "target": {
          "type": "object",
          "required": ["zone_ids", "entity_ids"],
          "properties": {
            "zone_ids": { "type": "array", "uniqueItems": true, "items": { "type": "string" } },
            "entity_ids": { "type": "array", "uniqueItems": true, "items": { "type": "string" } }
          },
          "additionalProperties": false
        },
        "params": { "type": "object" },
        "action_effect_fingerprint": { "type": "string", "minLength": 1 },
        "evidence": {
          "type": "array",
          "minItems": 1,
          "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/evidenceRef" }
        },
        "evidence_status": { "enum": ["valid", "needs_reassessment", "invalidated"] },
        "reasoning": { "type": "string", "minLength": 1 },
        "priority": { "enum": ["P0", "P1", "P2", "P3"] },
        "risk": { "enum": ["low", "medium", "high"] },
        "approval_policy": { "enum": ["automatic", "human_required"] },
        "reservation_id": {
          "oneOf": [
            { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
            { "type": "null" }
          ]
        }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

- [ ] **Step 6: Create the Outcome schema**

Create `schemas/v2/outcome.schema.json` with:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://valte.dev/schemas/v2/outcome.schema.json",
  "allOf": [
    { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/envelope" },
    {
      "type": "object",
      "required": [
        "outcome_id",
        "action_id",
        "attempt_id",
        "status",
        "summary",
        "observed_effects",
        "evidence"
      ],
      "properties": {
        "outcome_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "action_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "attempt_id": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/id" },
        "status": { "enum": ["success", "partial", "failed", "no_response", "unknown"] },
        "summary": { "type": "string", "minLength": 1 },
        "observed_effects": { "type": "object" },
        "evidence": {
          "type": "array",
          "items": { "$ref": "https://valte.dev/schemas/v2/common.schema.json#/$defs/evidenceRef" }
        }
      }
    }
  ],
  "unevaluatedProperties": false
}
```

- [ ] **Step 7: Expand the registry and add Incident semantic checks**

Replace `src/contracts/registry.ts` with:

```typescript
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

export type ContractKind = "signal" | "incident" | "plan" | "action" | "outcome";

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

const schemaFiles: Record<ContractKind | "common", string> = {
  common: "common.schema.json",
  signal: "signal.schema.json",
  incident: "incident.schema.json",
  plan: "plan.schema.json",
  action: "action.schema.json",
  outcome: "outcome.schema.json"
};

function readSchema(schemaRoot: string, file: string): object {
  return JSON.parse(readFileSync(resolve(schemaRoot, file), "utf8")) as object;
}

function semanticErrors(kind: ContractKind, value: unknown): string[] {
  if (kind !== "incident" || typeof value !== "object" || value === null) {
    return [];
  }

  const incident = value as Record<string, unknown>;
  const id = incident.incident_id;
  const state = incident.state;
  const canonical = incident.canonical_incident_id;
  const selfCanonicalStates = new Set(["candidate", "active", "closed", "dismissed"]);

  if (typeof state === "string" && selfCanonicalStates.has(state) && canonical !== id) {
    return ["/canonical_incident_id must equal incident_id for a canonical Incident"];
  }
  if (state === "merged" && (typeof canonical !== "string" || canonical === id)) {
    return ["/canonical_incident_id must identify another Incident when state is merged"];
  }
  if (state === "split" && canonical !== null) {
    return ["/canonical_incident_id must be null when state is split"];
  }
  return [];
}

export function createContractRegistry(
  schemaRoot = resolve(process.cwd(), "schemas/v2")
) {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);

  for (const file of Object.values(schemaFiles)) {
    ajv.addSchema(readSchema(schemaRoot, file));
  }

  return {
    validate(kind: ContractKind, value: unknown): ValidationResult {
      const schemaId = `https://valte.dev/schemas/v2/${schemaFiles[kind]}`;
      const validate = ajv.getSchema(schemaId);
      if (!validate) {
        return { valid: false, errors: [`schema not registered: ${kind}`] };
      }

      const schemaValid = validate(value);
      const errors = (validate.errors ?? []).map(
        (error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`
      );
      errors.push(...semanticErrors(kind, value));
      return { valid: Boolean(schemaValid) && errors.length === 0, errors };
    }
  };
}

export type ContractRegistry = ReturnType<typeof createContractRegistry>;
```

- [ ] **Step 8: Run the domain and Signal suites**

Run:

```bash
npm test -- tests/contracts/signal.test.ts tests/contracts/domain.test.ts
npm run typecheck
```

Expected: 6 tests pass; TypeScript exits `0`.

- [ ] **Step 9: Commit the domain contracts**

```bash
git add schemas/v2 src/contracts/registry.ts tests/contracts/domain.test.ts
git commit -m "feat: define generic crisis domain contracts"
```

### Task 4: Validate complete DANA and wildfire chains

**Files:**

- Create: `src/contracts/chain.ts`
- Create: `tests/fixtures/contract-chains.ts`
- Test: `tests/contracts/chain.test.ts`

- [ ] **Step 1: Create reusable DANA and wildfire fixtures**

Create `tests/fixtures/contract-chains.ts` with:

```typescript
import type { ContractChain } from "../../src/contracts/chain.js";

interface ChainOptions {
  packId: string;
  digestCharacter: string;
  hazardType: string;
  zoneId: string;
  observation: string;
  primitive: "allocate_resource" | "broadcast_message";
}

function buildChain(options: ChainOptions): ContractChain {
  const packDigest = options.digestCharacter.repeat(64);
  const envelope = {
    contract_version: "2.0.0",
    run_id: `run-${options.packId}`,
    pack_id: options.packId,
    pack_version: "1.0.0",
    pack_digest: packDigest,
    scenario_at: "2026-09-19T10:00:00.000Z",
    received_at: "2026-09-19T09:00:00.000Z",
    correlation_id: `corr-${options.packId}`,
    causation_id: null
  };
  const signalId = `sig-${options.packId}`;
  const incidentId = `inc-${options.packId}`;
  const planId = `plan-${options.packId}`;
  const actionId = `act-${options.packId}`;
  const evidence = [{ kind: "signal", signal_id: signalId, revision: 1 }];

  return {
    signal: {
      ...envelope,
      signal_id: signalId,
      revision: 1,
      status: "active",
      modality: "sensor_reading",
      content: options.observation,
      claims: [{ claim_type: "hazard_observation", value: options.hazardType }],
      source: {
        reporter_id: `sensor-${options.zoneId}`,
        origin_reference: `reading-${options.packId}`,
        source_trust_snapshot: "high",
        source_cluster_id: `cluster-${options.packId}`,
        independence_status: "confirmed_independent",
        content_fingerprint: `sha256:${options.packId}`
      },
      location: { zone_id: options.zoneId, precision: "exact" },
      signal_confidence: "high"
    },
    incident: {
      ...envelope,
      causation_id: signalId,
      incident_id: incidentId,
      state: "active",
      canonical_incident_id: incidentId,
      priority: "P0",
      confidence: "high",
      hazard_types: [options.hazardType],
      zone_ids: [options.zoneId],
      evidence,
      revisit_at: "2026-09-19T10:05:00.000Z"
    },
    plan: {
      ...envelope,
      causation_id: incidentId,
      plan_id: planId,
      plan_version: 1,
      supersedes_plan_id: null,
      status: "active",
      objectives: ["Protect life with reversible action"],
      assumptions: ["The reported hazard remains active"],
      incident_ids: [incidentId],
      action_ids: [actionId],
      evidence,
      active_human_directive_ids: []
    },
    action: {
      ...envelope,
      causation_id: planId,
      action_id: actionId,
      plan_id: planId,
      incident_id: incidentId,
      primitive: options.primitive,
      status: "approved",
      actor_id: `responder-${options.packId}`,
      target: { zone_ids: [options.zoneId], entity_ids: [] },
      params: { units: 1 },
      action_effect_fingerprint: `sha256:effect-${options.packId}`,
      evidence,
      evidence_status: "valid",
      reasoning: "Independent sensor evidence supports a reversible immediate response.",
      priority: "P0",
      risk: "medium",
      approval_policy: "automatic",
      reservation_id: null
    },
    outcome: {
      ...envelope,
      causation_id: actionId,
      outcome_id: `out-${options.packId}`,
      action_id: actionId,
      attempt_id: `attempt-${options.packId}`,
      status: "success",
      summary: "The action reached its intended target.",
      observed_effects: { reached_zone: options.zoneId },
      evidence
    }
  };
}

export const danaChain = buildChain({
  packId: "dana-demo",
  digestCharacter: "c",
  hazardType: "flood",
  zoneId: "paiporta",
  observation: "Water level is rising at the Paiporta underpass",
  primitive: "allocate_resource"
});

export const wildfireChain = buildChain({
  packId: "wildfire-demo",
  digestCharacter: "d",
  hazardType: "wildfire",
  zoneId: "pinar-norte",
  observation: "A thermal sensor detects an active fire front",
  primitive: "broadcast_message"
});
```

- [ ] **Step 2: Write the failing chain tests**

Create `tests/contracts/chain.test.ts` with:

```typescript
import { describe, expect, it } from "vitest";

import { validateContractChain } from "../../src/contracts/chain.js";
import { createContractRegistry } from "../../src/contracts/registry.js";
import { danaChain, wildfireChain } from "../fixtures/contract-chains.js";

describe("generic contract chain", () => {
  const registry = createContractRegistry();

  it.each([
    ["DANA", danaChain],
    ["wildfire", wildfireChain]
  ])("validates the %s chain with the same schemas", (_name, chain) => {
    expect(validateContractChain(registry, chain)).toEqual({
      valid: true,
      errors: []
    });
  });

  it("rejects cross-pack contamination", () => {
    const contaminated = structuredClone(wildfireChain);
    contaminated.action.pack_id = danaChain.action.pack_id;
    contaminated.action.pack_digest = danaChain.action.pack_digest;

    const result = validateContractChain(registry, contaminated);

    expect(result.valid).toBe(false);
    expect(result.errors.join(" ")).toContain("action.pack_id");
    expect(result.errors.join(" ")).toContain("action.pack_digest");
  });

  it("rejects a dangling Action evidence revision", () => {
    const broken = structuredClone(danaChain);
    broken.action.evidence = [{ kind: "signal", signal_id: broken.signal.signal_id, revision: 2 }];

    const result = validateContractChain(registry, broken);

    expect(result.valid).toBe(false);
    expect(result.errors.join(" ")).toContain("action evidence");
  });
});
```

- [ ] **Step 3: Run the chain tests to verify they fail**

Run:

```bash
npm test -- tests/contracts/chain.test.ts
```

Expected: FAIL because `src/contracts/chain.ts` does not exist.

- [ ] **Step 4: Implement cross-contract validation**

Create `src/contracts/chain.ts` with:

```typescript
import type { ContractKind, ContractRegistry, ValidationResult } from "./registry.js";

export type ContractRecord = Record<string, unknown>;

export interface ContractChain {
  signal: ContractRecord;
  incident: ContractRecord;
  plan: ContractRecord;
  action: ContractRecord;
  outcome: ContractRecord;
}

const identityFields = [
  "contract_version",
  "run_id",
  "pack_id",
  "pack_version",
  "pack_digest"
] as const;

function evidenceHasSignal(
  value: unknown,
  signalId: unknown,
  revision: unknown
): boolean {
  if (!Array.isArray(value)) {
    return false;
  }
  return value.some((item) => {
    if (typeof item !== "object" || item === null) {
      return false;
    }
    const evidence = item as ContractRecord;
    return evidence.kind === "signal"
      && evidence.signal_id === signalId
      && evidence.revision === revision;
  });
}

export function validateContractChain(
  registry: ContractRegistry,
  chain: ContractChain
): ValidationResult {
  const errors: string[] = [];
  const entries = Object.entries(chain) as Array<[ContractKind, ContractRecord]>;

  for (const [kind, value] of entries) {
    const result = registry.validate(kind, value);
    errors.push(...result.errors.map((error) => `${kind}: ${error}`));
  }

  for (const [kind, value] of entries.slice(1)) {
    for (const field of identityFields) {
      if (value[field] !== chain.signal[field]) {
        errors.push(`${kind}.${field} must match signal.${field}`);
      }
    }
  }

  if (!evidenceHasSignal(chain.incident.evidence, chain.signal.signal_id, chain.signal.revision)) {
    errors.push("incident evidence must reference the chain Signal revision");
  }
  if (!evidenceHasSignal(chain.action.evidence, chain.signal.signal_id, chain.signal.revision)) {
    errors.push("action evidence must reference the chain Signal revision");
  }
  if (!evidenceHasSignal(chain.plan.evidence, chain.signal.signal_id, chain.signal.revision)) {
    errors.push("plan evidence must reference the chain Signal revision");
  }
  if (!Array.isArray(chain.plan.incident_ids)
      || !chain.plan.incident_ids.includes(chain.incident.incident_id)) {
    errors.push("plan must include the chain Incident");
  }
  if (!Array.isArray(chain.plan.action_ids)
      || !chain.plan.action_ids.includes(chain.action.action_id)) {
    errors.push("plan must include the chain Action");
  }
  if (chain.action.plan_id !== chain.plan.plan_id) {
    errors.push("action.plan_id must reference the chain Plan");
  }
  if (chain.action.incident_id !== chain.incident.incident_id) {
    errors.push("action.incident_id must reference the chain Incident");
  }
  if (chain.outcome.action_id !== chain.action.action_id) {
    errors.push("outcome.action_id must reference the chain Action");
  }

  return { valid: errors.length === 0, errors };
}
```

- [ ] **Step 5: Run all contract tests**

Run:

```bash
npm test -- tests/contracts
npm run typecheck
```

Expected: 10 tests pass; TypeScript exits `0`.

- [ ] **Step 6: Commit the generic chain validator**

```bash
git add src/contracts/chain.ts tests/contracts/chain.test.ts tests/fixtures/contract-chains.ts
git commit -m "feat: validate generic crisis contract chains"
```

### Task 5: Add a contract validation CLI

**Files:**

- Create: `src/cli/validate-contract.ts`
- Create: `examples/contracts/dana-signal.json`
- Test: `tests/contracts/cli.test.ts`

- [ ] **Step 1: Add one valid example payload**

Create `examples/contracts/dana-signal.json` with:

```json
{
  "contract_version": "2.0.0",
  "signal_id": "sig-dana-example",
  "revision": 1,
  "status": "active",
  "run_id": "run-dana-example",
  "pack_id": "dana-demo",
  "pack_version": "1.0.0",
  "pack_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "scenario_at": "2026-09-19T10:00:00.000Z",
  "received_at": "2026-09-19T09:00:00.000Z",
  "correlation_id": "corr-dana-example",
  "causation_id": null,
  "modality": "call_transcript",
  "content": "El agua está entrando en el paso inferior",
  "claims": [
    { "claim_type": "hazard_observation", "value": "flooding" }
  ],
  "source": {
    "reporter_id": "caller-example",
    "origin_reference": "call-example",
    "source_trust_snapshot": "unknown",
    "source_cluster_id": "cluster-example",
    "independence_status": "confirmed_independent",
    "content_fingerprint": "sha256:dana-example"
  },
  "location": { "zone_id": "paiporta", "precision": "zone" },
  "signal_confidence": "medium"
}
```

- [ ] **Step 2: Write the failing CLI tests**

Create `tests/contracts/cli.test.ts` with:

```typescript
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { main } from "../../src/cli/validate-contract.js";

const temporaryDirectories: string[] = [];

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((directory) =>
    rm(directory, { recursive: true, force: true })
  ));
});

describe("validate-contract CLI", () => {
  it("returns zero for the checked-in DANA Signal", async () => {
    const output: string[] = [];
    const exitCode = await main(
      ["signal", resolve("examples/contracts/dana-signal.json")],
      (line) => output.push(line),
      (line) => output.push(line)
    );

    expect(exitCode).toBe(0);
    expect(output).toEqual(["PASS signal examples/contracts/dana-signal.json"]);
  });

  it("returns one and useful errors for invalid JSON data", async () => {
    const directory = await mkdtemp(join(tmpdir(), "valte-contract-"));
    temporaryDirectories.push(directory);
    const file = join(directory, "invalid-signal.json");
    await writeFile(file, JSON.stringify({ contract_version: "2.0.0" }));
    const errors: string[] = [];

    const exitCode = await main(["signal", file], () => undefined, (line) => errors.push(line));

    expect(exitCode).toBe(1);
    expect(errors.join(" ")).toContain("signal_id");
    expect(errors.join(" ")).toContain("pack_digest");
  });
});
```

- [ ] **Step 3: Run the CLI tests to verify they fail**

Run:

```bash
npm test -- tests/contracts/cli.test.ts
```

Expected: FAIL because `src/cli/validate-contract.ts` does not exist.

- [ ] **Step 4: Implement the CLI**

Create `src/cli/validate-contract.ts` with:

```typescript
import { readFile } from "node:fs/promises";
import { relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import {
  createContractRegistry,
  type ContractKind
} from "../contracts/registry.js";

type Writer = (line: string) => void;

const kinds = new Set<ContractKind>([
  "signal",
  "incident",
  "plan",
  "action",
  "outcome"
]);

export async function main(
  args: string[],
  write: Writer = console.log,
  writeError: Writer = console.error
): Promise<number> {
  const [kindInput, fileInput] = args;
  if (!kindInput || !kinds.has(kindInput as ContractKind) || !fileInput) {
    writeError("Usage: npm run contracts:check -- <signal|incident|plan|action|outcome> <file.json>");
    return 2;
  }

  const kind = kindInput as ContractKind;
  const file = resolve(fileInput);
  let value: unknown;
  try {
    value = JSON.parse(await readFile(file, "utf8")) as unknown;
  } catch (error) {
    writeError(`Cannot read JSON: ${error instanceof Error ? error.message : String(error)}`);
    return 2;
  }

  const result = createContractRegistry().validate(kind, value);
  if (!result.valid) {
    for (const error of result.errors) {
      writeError(`FAIL ${kind} ${error}`);
    }
    return 1;
  }

  write(`PASS ${kind} ${relative(process.cwd(), file)}`);
  return 0;
}

const invokedFile = process.argv[1];
if (invokedFile && import.meta.url === pathToFileURL(invokedFile).href) {
  process.exitCode = await main(process.argv.slice(2));
}
```

- [ ] **Step 5: Run the CLI tests and the real command**

Run:

```bash
npm test -- tests/contracts/cli.test.ts
npm run contracts:check -- signal examples/contracts/dana-signal.json
```

Expected:

```text
PASS signal examples/contracts/dana-signal.json
```

- [ ] **Step 6: Commit the CLI**

```bash
git add src/cli/validate-contract.ts tests/contracts/cli.test.ts examples/contracts/dana-signal.json
git commit -m "feat: add crisis contract validation CLI"
```

### Task 6: Document and verify the first vertical foundation

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Add the v2 contracts section to README**

Append this section to `README.md`:

````markdown
## Generic crisis contracts v2

The current implementation starts with the shared domain language:

```text
Signal → Incident → Plan → Action → Outcome
```

Schemas under `schemas/v2/` are generic across DANA, wildfire, blackout,
chemical leak, earthquake, and humanitarian scenarios. The earlier DANA-oriented
prototypes remain unchanged under `schemas/v1/` and are not accepted as v2.

Install and verify:

```bash
npm install
npm test
npm run typecheck
npm run contracts:check -- signal examples/contracts/dana-signal.json
```

This phase validates contracts only. Supabase, the State Gateway, HappyRobot
workflows, Scenario Packs, Azure UI, and real external effects are introduced in
their own implementation phases.
````

- [ ] **Step 2: Run the complete verification suite**

Run:

```bash
npm test
npm run typecheck
npm run contracts:check -- signal examples/contracts/dana-signal.json
git diff --check
```

Expected:

- Vitest reports 12 passing tests.
- TypeScript exits `0` with no diagnostics.
- The CLI prints `PASS signal examples/contracts/dana-signal.json`.
- `git diff --check` produces no output.

- [ ] **Step 3: Confirm scope isolation**

Run:

```bash
test -f schemas/v1/signal.schema.json
test -f schemas/v2/signal.schema.json
git check-ignore -q node_modules
test -z "$(git ls-files node_modules)"
git status --short
```

Expected: both schema generations exist, no dependency directory is tracked, and only the README change is uncommitted after earlier task commits.

- [ ] **Step 4: Commit the documentation**

```bash
git add README.md
git commit -m "docs: explain generic crisis contracts v2"
```

## Plan self-review result

- **Spec coverage:** This phase covers contract versioning, pack/run identity, typed Signal revisions, Incident canonicalization, plan/action/outcome traceability, closed primitives, DANA/fire generality, and cross-pack rejection.
- **Deliberate exclusions:** Persistence, atomic commands, outbox, reservations, clock, backpressure, HappyRobot, dashboard, integrations, Scenario Pack files, hidden truth storage, and full E2E evaluation belong to the next five plans listed above.
- **Type consistency:** `ContractKind`, schema filenames, fixture keys, CLI values, and chain-validator record names match across all tasks.
- **No placeholder behavior:** Every command, file body, expected failure, expected pass, and commit boundary is explicit.
