import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

function makeContext() {
  const logs = [];
  return {
    log: { error: (...a) => logs.push(a), warn: (...a) => logs.push(a) },
    res: null,
    logs,
  };
}

function makeReq(body, headers = {}) {
  return { body: JSON.stringify(body), headers };
}

const baseCommand = {
  command_id: "test-cmd-0001",
  run_id: "run-dana-demo",
  pack_id: "dana-demo",
  pack_version: "1.0.0",
  pack_digest: "c".repeat(64),
  expected_state_version: 5,
  actor: "operator",
  causation_id: null,
};

describe("decision: eligible approver and first-decision-wins", () => {
  test("migration enforces eligible approver and first-decision-wins", async () => {
    // Check that apply_command migration contains eligibility and serialization logic
    const migrationPath = resolve(root, "supabase/migrations/202609190006_eligible_approver_first_decision_wins.sql");
    let content;
    try {
      content = await readFile(migrationPath, "utf8");
    } catch {
      assert.fail("migration 202609190006_eligible_approver_first_decision_wins.sql not found");
    }
    assert.match(content, /not_eligible_approver/, "should return not_eligible_approver for ineligible approver");
    assert.match(content, /FOR UPDATE/, "should use SELECT FOR UPDATE to serialize decisions");
    assert.match(content, /pending_approval/, "should check action is pending_approval");
    assert.match(content, /approver_entity_ids/, "should check deciding_entity_id in approver_entity_ids");
    assert.match(content, /deciding_entity_id/, "should persist deciding_entity_id");
  });

  test("gateway validates deciding_entity_id required string and note optional", async () => {
    const handlerPath = resolve(root, "api/commands/index.mjs");
    const handlerContent = await readFile(handlerPath, "utf8");
    assert.match(handlerContent, /deciding_entity_id/, "gateway should validate deciding_entity_id");
    // Also check that handler validates approve/reject payload
    assert.match(handlerContent, /approve_action/, "gateway should handle approve_action");
    assert.match(handlerContent, /reject_action/, "gateway should handle reject_action");
  });

  test("approve_action with ineligible deciding_entity_id should be rejected", async () => {
    // Set dummy env for supabase to avoid throw
    process.env.SUPABASE_URL = process.env.SUPABASE_URL || "https://dummy.supabase.co";
    process.env.SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || "dummy-key";
    delete process.env.GATEWAY_TOKEN;
    // Stub fetch to simulate DB behavior: if we reach RPC, return not_eligible_approver for intruder
    const originalFetch = globalThis.fetch;
    let rpcCalled = false;
    // We need to test gateway's own validation without hitting real DB
    // For ineligible case we expect gateway to reject before or via RPC error
    // We'll mock fetch to return not_eligible_approver for intruder, success for eligible
    globalThis.fetch = async (url, opts) => {
      rpcCalled = true;
      const body = opts?.body ? JSON.parse(opts.body) : {};
      const cmd = body.p_command;
      const deciding = cmd?.payload?.deciding_entity_id;
      if (deciding === "intruder-entity") {
        return {
          ok: true,
          status: 200,
          text: async () => JSON.stringify({ ok: false, error: "not_eligible_approver", message: "deciding entity not in approver list" }),
        };
      }
      if (deciding === "mayor-paiporta") {
        return {
          ok: true,
          status: 200,
          text: async () => JSON.stringify({ ok: true, command_id: cmd.command_id, state_version: 6, result: { action_id: cmd.payload.action_id } }),
        };
      }
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ ok: false, error: "invalid_payload", message: "missing deciding_entity_id" }),
      };
    };

    const { default: handler } = await import(resolve(root, "api/commands/index.mjs"));

    // ineligible
    const ctx1 = makeContext();
    const req1 = makeReq({ ...baseCommand, command_id: "test-cmd-0002", command_type: "approve_action", payload: { action_id: "act-dana-001", deciding_entity_id: "intruder-entity", note: "try hack" } });
    await handler(ctx1, req1);
    const res1 = JSON.parse(ctx1.res.body);
    assert.equal(ctx1.res.status, 400, "ineligible should be 400");
    assert.equal(res1.error, "not_eligible_approver");

    // eligible should succeed
    const ctx2 = makeContext();
    const req2 = makeReq({ ...baseCommand, command_id: "test-cmd-0003", command_type: "approve_action", payload: { action_id: "act-dana-001", deciding_entity_id: "mayor-paiporta", note: "ok" } });
    rpcCalled = false;
    await handler(ctx2, req2);
    assert.equal(ctx2.res.status, 200);
    const res2 = JSON.parse(ctx2.res.body);
    assert.equal(res2.ok, true);

    // missing deciding_entity_id should be rejected as invalid_command (400) without RPC
    let fetchCalledForMissing = false;
    globalThis.fetch = async () => { fetchCalledForMissing = true; return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true }) }; };
    const ctx3 = makeContext();
    const req3 = makeReq({ ...baseCommand, command_id: "test-cmd-0004", command_type: "approve_action", payload: { action_id: "act-dana-001" } });
    await handler(ctx3, req3);
    assert.equal(ctx3.res.status, 400);
    const res3 = JSON.parse(ctx3.res.body);
    assert.equal(res3.error, "invalid_command");
    assert.equal(fetchCalledForMissing, false, "missing deciding_entity_id should not call RPC");

    globalThis.fetch = originalFetch;
  });

  test("second decision cannot change first (first valid decision final)", async () => {
    process.env.SUPABASE_URL = process.env.SUPABASE_URL || "https://dummy.supabase.co";
    process.env.SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || "dummy-key";
    delete process.env.GATEWAY_TOKEN;
    const originalFetch = globalThis.fetch;
    // Simulate DB: first approve succeeds, second approve on same action returns invalid_transition regardless of version
    let callCount = 0;
    globalThis.fetch = async (url, opts) => {
      callCount++;
      const body = opts?.body ? JSON.parse(opts.body) : {};
      const cmd = body.p_command;
      if (callCount === 1) {
        return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true, command_id: cmd.command_id, state_version: 6 }) };
      } else {
        return { ok: true, status: 200, text: async () => JSON.stringify({ ok: false, error: "invalid_transition", message: "action cannot be approved" }) };
      }
    };
    const { default: handler } = await import(resolve(root, "api/commands/index.mjs"));
    const ctx1 = makeContext();
    await handler(ctx1, makeReq({ ...baseCommand, command_id: "test-cmd-0010", command_type: "approve_action", payload: { action_id: "act-dana-001", deciding_entity_id: "mayor-paiporta" } }));
    assert.equal(ctx1.res.status, 200);
    const ctx2 = makeContext();
    // second attempt with different entity, same action, new version (6)
    await handler(ctx2, makeReq({ ...baseCommand, command_id: "test-cmd-0011", expected_state_version: 6, command_type: "reject_action", payload: { action_id: "act-dana-001", deciding_entity_id: "cecopi-coordination" } }));
    assert.equal(ctx2.res.status, 400);
    const res2 = JSON.parse(ctx2.res.body);
    assert.equal(res2.error, "invalid_transition");

    globalThis.fetch = originalFetch;
  });

  test("concurrent decisions produce one success and one version_conflict", async () => {
    process.env.SUPABASE_URL = process.env.SUPABASE_URL || "https://dummy.supabase.co";
    process.env.SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || "dummy-key";
    delete process.env.GATEWAY_TOKEN;
    const originalFetch = globalThis.fetch;
    let callIdx = 0;
    globalThis.fetch = async (url, opts) => {
      callIdx++;
      const body = opts?.body ? JSON.parse(opts.body) : {};
      const cmd = body.p_command;
      // Simulate serialization: first wins, second sees stale version
      if (callIdx === 1) {
        return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true, command_id: cmd.command_id, state_version: 6 }) };
      } else {
        return { ok: true, status: 200, text: async () => JSON.stringify({ ok: false, error: "version_conflict", message: "expected_state_version is stale", actual_state_version: 6 }) };
      }
    };
    // Need fresh import to avoid cache? reuse same handler
    const { default: handler } = await import(resolve(root, "api/commands/index.mjs"));
    const reqA = makeReq({ ...baseCommand, command_id: "test-cmd-conc-a", command_type: "approve_action", payload: { action_id: "act-dana-001", deciding_entity_id: "mayor-paiporta" } });
    const reqB = makeReq({ ...baseCommand, command_id: "test-cmd-conc-b", command_type: "approve_action", payload: { action_id: "act-dana-001", deciding_entity_id: "cecopi-coordination" } });
    const ctxA = makeContext();
    const ctxB = makeContext();
    const [rA, rB] = await Promise.all([handler(ctxA, reqA), handler(ctxB, reqB)]);
    const statuses = [ctxA.res.status, ctxB.res.status].sort();
    assert.deepEqual(statuses, [200, 409], `expected one 200 and one 409, got ${statuses}`);
    const bodies = [JSON.parse(ctxA.res.body), JSON.parse(ctxB.res.body)];
    const hasVersionConflict = bodies.some((b) => b.error === "version_conflict");
    assert.equal(hasVersionConflict, true, "one should be version_conflict");

    globalThis.fetch = originalFetch;
  });
});
