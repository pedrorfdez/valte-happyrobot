import { readFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const schemaRoot = resolve(root, "schemas/v2");

const load = async (file) => JSON.parse(await readFile(file, "utf8"));

const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
ajv.addSchema(await load(resolve(schemaRoot, "common.schema.json")));
ajv.addSchema(await load(resolve(schemaRoot, "action.schema.json")));

const validate = ajv.getSchema("https://valte.dev/schemas/v2/action.schema.json");
if (!validate) {
  console.error("action schema not found");
  process.exit(1);
}

function baseAction(overrides = {}) {
  return {
    contract_version: "2.0.0",
    run_id: "run-dana-demo",
    pack_id: "dana-demo",
    pack_version: "1.0.0",
    pack_digest: "c".repeat(64),
    scenario_at: "2026-09-19T10:00:00Z",
    received_at: "2026-09-19T10:00:01Z",
    correlation_id: "run-dana-demo",
    causation_id: null,
    action_id: "act-dana-001",
    plan_id: "plan-dana-001",
    incident_id: "inc-dana-001",
    primitive: "allocate_resource",
    status: "pending_approval",
    actor_id: "rescue-team",
    target: { zone_id: "paiporta-ground-floor" },
    params: { units: 1 },
    action_effect_fingerprint: "allocate_resource:paiporta-ground-floor:1",
    evidence: [{ kind: "signal", signal_id: "sig-dana-001", revision: 1 }],
    evidence_status: "valid",
    reasoning: "Independent sensor evidence shows immediate danger.",
    priority: "P0",
    risk: "medium",
    approval_policy: "human_required",
    approver_entity_ids: ["mayor-paiporta", "cecopi-coordination"],
    approvals_required: 1,
    reservation_id: null,
    ...overrides,
  };
}

function assertValid(label, obj, shouldBeValid) {
  const ok = validate(obj);
  if (ok !== shouldBeValid) {
    console.error(`FAIL ${label}: expected ${shouldBeValid ? "valid" : "invalid"} but got ${ok ? "valid" : "invalid"}`);
    if (validate.errors) console.error(JSON.stringify(validate.errors, null, 2));
    return false;
  }
  console.log(`PASS ${label}`);
  return true;
}

let pass = true;

// 1. human_required with approver_entity_ids should pass
pass = assertValid(
  "human_required with approver_entity_ids",
  baseAction(),
  true
) && pass;

// 2. human_required WITHOUT approver_entity_ids should FAIL per new schema (if.then required)
pass =
  assertValid(
    "human_required without approver_entity_ids should be invalid",
    (() => {
      const o = baseAction();
      delete o.approver_entity_ids;
      delete o.approvals_required;
      return o;
    })(),
    false
  ) && pass;

// 3. human_required with empty array should be invalid (minItems 1)
pass =
  assertValid(
    "human_required with empty approver_entity_ids should be invalid",
    baseAction({ approver_entity_ids: [] }),
    false
  ) && pass;

// 4. human_required with duplicate should be invalid (uniqueItems)
pass =
  assertValid(
    "human_required with duplicate approver_entity_ids should be invalid",
    baseAction({ approver_entity_ids: ["mayor-paiporta", "mayor-paiporta"] }),
    false
  ) && pass;

// 5. approvals_required must be const 1 when human_required
pass =
  assertValid(
    "human_required with approvals_required !=1 should be invalid",
    baseAction({ approvals_required: 2 }),
    false
  ) && pass;

// 6. automatic without allowlist should pass (existing fixtures)
pass =
  assertValid(
    "automatic without approver_entity_ids should be valid",
    (() => {
      const o = baseAction({
        status: "approved",
        approval_policy: "automatic",
      });
      delete o.approver_entity_ids;
      delete o.approvals_required;
      return o;
    })(),
    true
  ) && pass;

// 7. automatic with allowlist? spec says automatic actions omit allowlist or use empty list – we allow missing, but if present should still be validated? Allow optional but if present must be valid.
pass =
  assertValid(
    "automatic with empty approver_entity_ids should be valid if schema allows (optional)",
    (() => {
      const o = baseAction({
        status: "approved",
        approval_policy: "automatic",
        approver_entity_ids: [],
      });
      // approvals_required omitted – should still be valid? Depends on if clause. We'll accept either; main is that automatic doesn't require it.
      delete o.approvals_required;
      return o;
    })(),
    true
  ) && pass;

if (!pass) {
  console.error("contract.test: SOME CHECKS FAILED");
  process.exit(1);
}
console.log("contract.test: ALL CHECKS PASSED");
