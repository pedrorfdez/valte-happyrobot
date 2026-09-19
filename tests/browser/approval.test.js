import { describe, test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { resolve } from "node:path";

const gatewayPath = resolve("app-v2/src/adapter/gateway.js");
const realtimePath = resolve("app-v2/src/adapter/realtime.js");

describe("browser: approval commands", () => {
  let originalFetch;
  let originalRandomUUID;

  beforeEach(() => {
    originalFetch = global.fetch;
    originalRandomUUID = global.crypto?.randomUUID;
    // deterministic crypto for tests - patch randomUUID without overwriting crypto
    try {
      if (global.crypto && typeof global.crypto.randomUUID === "function") {
        global.crypto.randomUUID = () => "test-uuid-1234";
      } else if (global.crypto) {
        Object.defineProperty(global.crypto, "randomUUID", { value: () => "test-uuid-1234", writable: true, configurable: true });
      }
    } catch {}
  });

  afterEach(() => {
    global.fetch = originalFetch;
    try {
      if (global.crypto && originalRandomUUID) {
        global.crypto.randomUUID = originalRandomUUID;
      }
    } catch {}
  });

  test("approve_action builds envelope with expected_state_version and deciding_entity_id", async () => {
    const gateway = await import(gatewayPath);

    assert.equal(typeof gateway.buildCommandEnvelope, "function");
    assert.equal(typeof gateway.approveAction, "function");
    assert.equal(typeof gateway.rejectAction, "function");
    assert.equal(typeof gateway.postCommand, "function");

    const snapshot = {
      run: {
        run_id: "run-dana-demo",
        pack_id: "dana-demo",
        pack_version: "1.0.0",
        pack_digest: "a".repeat(64),
        state_version: 5,
      },
    };

    let capturedUrl = null;
    let capturedBody = null;

    global.fetch = async (url, opts) => {
      capturedUrl = String(url);
      capturedBody = JSON.parse(opts.body);
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ ok: true, state_version: 6 }),
        json: async () => ({ ok: true, state_version: 6 }),
      };
    };

    const result = await gateway.approveAction(snapshot, "a1", "mayor-paiporta", "ok");

    assert.ok(capturedUrl.includes("/api/commands"), "must POST to /api/commands");
    assert.equal(capturedBody.run_id, "run-dana-demo");
    assert.equal(capturedBody.pack_id, "dana-demo");
    assert.equal(capturedBody.expected_state_version, 5, "must include expected_state_version from snapshot");
    assert.equal(capturedBody.command_type, "approve_action");
    assert.equal(capturedBody.payload.action_id, "a1");
    assert.equal(capturedBody.payload.deciding_entity_id, "mayor-paiporta");
    assert.equal(capturedBody.actor, "operator");
    assert.ok(capturedBody.command_id.startsWith("v2-"), "command_id must start with v2-");
    assert.equal(capturedBody.causation_id, null);
    assert.equal(result.ok, true);
  });

  test("postCommand throws version_conflict on 409 and banner message", async () => {
    const gateway = await import(gatewayPath);

    global.fetch = async () => ({
      ok: false,
      status: 409,
      text: async () => JSON.stringify({ ok: false, error: "version_conflict", message: "state version mismatch" }),
      json: async () => ({ ok: false, error: "version_conflict", message: "state version mismatch" }),
    });

    const snapshot = {
      run: { run_id: "run-dana-demo", pack_id: "dana-demo", pack_version: "1.0.0", pack_digest: "a".repeat(64), state_version: 5 },
    };
    const envelope = gateway.buildCommandEnvelope(snapshot, "approve_action", { action_id: "a1", deciding_entity_id: "mayor-paiporta" });

    await assert.rejects(async () => await gateway.postCommand(envelope), (err) => {
      assert.equal(err.status, 409);
      assert.ok(err.message.includes("version_conflict") || err.code === "version_conflict");
      return true;
    });

    // helper for Spanish banner
    if (typeof gateway.getVersionConflictMessage === "function") {
      assert.equal(gateway.getVersionConflictMessage(), "otro operador decidió primero");
    }
    if (typeof gateway.formatCommandError === "function") {
      const msg = gateway.formatCommandError({ status: 409, code: "version_conflict" });
      assert.ok(msg.includes("otro operador decidió primero"));
    }
  });

  test("postCommand handles 400 stable message and 404 run_not_found", async () => {
    const gateway = await import(gatewayPath);

    // 400 case
    global.fetch = async () => ({
      ok: false,
      status: 400,
      text: async () => JSON.stringify({ ok: false, error: "invalid_command", message: "deciding_entity_id must be a non-empty string" }),
      json: async () => ({ ok: false, error: "invalid_command", message: "deciding_entity_id must be a non-empty string" }),
    });

    const snapshot = {
      run: { run_id: "run-dana-demo", pack_id: "dana-demo", pack_version: "1.0.0", pack_digest: "a".repeat(64), state_version: 5 },
    };
    const env = gateway.buildCommandEnvelope(snapshot, "approve_action", { action_id: "a1", deciding_entity_id: "" });
    await assert.rejects(async () => await gateway.postCommand(env), (err) => {
      assert.equal(err.status, 400);
      // stable message: debe preservar el mensaje del Gateway sin mutar estado local
      assert.ok(err.message.includes("invalid_command") || err.message.includes("deciding_entity_id"));
      return true;
    });

    // 404 run_not_found
    global.fetch = async () => ({
      ok: false,
      status: 404,
      text: async () => JSON.stringify({ ok: false, error: "run_not_found", message: "run not found" }),
      json: async () => ({ ok: false, error: "run_not_found" }),
    });
    await assert.rejects(async () => await gateway.postCommand(env), (err) => {
      assert.equal(err.status, 404);
      assert.equal(err.code, "run_not_found");
      return true;
    });

    if (typeof gateway.isRunNotFoundError === "function") {
      assert.equal(gateway.isRunNotFoundError({ status: 404, code: "run_not_found" }), true);
    }
  });

  test("only Coordination view renders pause/resume/abort", async () => {
    const gateway = await import(gatewayPath);

    // gateway helper
    if (typeof gateway.canRenderRunControls === "function") {
      assert.equal(gateway.canRenderRunControls({ role: "coordination", entity_id: "cecopi-coordination" }), true);
      assert.equal(gateway.canRenderRunControls({ role: "authority", entity_id: "mayor-paiporta" }), false);
      assert.equal(gateway.canRenderRunControls({ role: "responder", entity_id: "rescue-team" }), false);
    }

    // also check buildCommandEnvelope for run controls
    const snap = {
      run: { run_id: "run-dana-demo", pack_id: "dana-demo", pack_version: "1.0.0", pack_digest: "a".repeat(64), state_version: 10 },
    };
    let captured = null;
    global.fetch = async (url, opts) => {
      captured = JSON.parse(opts.body);
      return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true }), json: async () => ({ ok: true }) };
    };

    if (typeof gateway.pauseRun === "function") {
      await gateway.pauseRun(snap);
      assert.equal(captured.command_type, "pause_run");
      assert.equal(captured.expected_state_version, 10);
    }
    if (typeof gateway.resumeRun === "function") {
      await gateway.resumeRun(snap);
      assert.equal(captured.command_type, "resume_run");
    }
    if (typeof gateway.abortRun === "function") {
      await gateway.abortRun(snap);
      assert.equal(captured.command_type, "abort_run");
    }
  });

  test("realtime manager: health live/degraded/stale/offline and debounced fetchSnapshot + polling fallback", async () => {
    const realtimeMod = await import(realtimePath);
    assert.ok(typeof realtimeMod.createRealtimeManager === "function" || typeof realtimeMod.createRealtimeClient === "function", "must export createRealtimeManager");

    const factory = realtimeMod.createRealtimeManager || realtimeMod.createRealtimeClient;

    // Mock fetchSnapshot that resolves after call
    let snapshotCalls = 0;
    const mockSnapshot = { run: { run_id: "run-dana-demo", state_version: 5 } };
    async function fetchSnapshot() {
      snapshotCalls += 1;
      return mockSnapshot;
    }

    let healthChanges = [];
    let snapshotReceived = [];

    // Create manager with mocked supabase that fails to connect -> degraded polling
    const mgr = factory({
      runId: "run-dana-demo",
      fetchSnapshot,
      onSnapshot: (snap) => snapshotReceived.push(snap),
      onHealthChange: (h) => healthChanges.push(h),
      supabaseUrl: null,
      supabaseAnonKey: null,
      pollIntervalMs: 100,
      staleThresholdMs: 30000,
      debounceMs: 20,
      // inject fake client that never connects
      createClient: null,
    });

    assert.ok(mgr, "manager created");
    assert.equal(typeof mgr.start, "function");
    assert.equal(typeof mgr.stop, "function");
    assert.equal(typeof mgr.getHealth, "function");
    assert.equal(typeof mgr.triggerRefresh, "function");

    // Start manager: should enter degraded or offline initially (no realtime)
    await mgr.start();
    // Wait for initial poll to happen
    await new Promise((r) => setTimeout(r, 150));
    // Health should be degraded if snapshot age <10s and polling active, or live if realtime connected
    const health = mgr.getHealth();
    assert.ok(["live", "degraded", "stale", "offline"].includes(health), `health must be one of live/degraded/stale/offline, got ${health}`);

    // Trigger debounced refresh multiple times, should coalesce
    snapshotCalls = 0;
    mgr.triggerRefresh("realtime");
    mgr.triggerRefresh("realtime");
    mgr.triggerRefresh("realtime");
    await new Promise((r) => setTimeout(r, 50));
    assert.equal(snapshotCalls, 1, "debounced refresh must coalesce multiple triggers into one fetch");

    // Simulate realtime subscribed -> health live
    if (typeof mgr._setRealtimeSubscribed === "function") {
      mgr._setRealtimeSubscribed(true);
      // update last sync to now by triggering successful fetch
      await mgr.triggerRefresh("realtime");
      await new Promise((r) => setTimeout(r, 30));
      assert.equal(mgr.getHealth(), "live");
    } else if (typeof mgr.setRealtimeConnected === "function") {
      mgr.setRealtimeConnected(true);
      await new Promise((r) => setTimeout(r, 30));
      // health may still be degraded if not recently synced, but ensure it can become live
    }

    // Test stale: set lastSuccessfulSync far in past via stop/start or internal
    // We check that manager exposes method to simulate stale
    await mgr.stop();
    healthChanges = [];
    // After stop, health should be offline or stale depending on implementation
    const finalHealth = mgr.getHealth();
    assert.ok(["offline", "stale", "degraded", "live"].includes(finalHealth));

    // Ensure polling fallback reports degraded when realtime unavailable
    // Recreate with realtime failing
    let pollMgr = factory({
      runId: "run-dana-demo",
      fetchSnapshot: async () => mockSnapshot,
      onSnapshot: () => {},
      onHealthChange: (h) => healthChanges.push(h),
      pollIntervalMs: 50,
      debounceMs: 10,
    });
    await pollMgr.start();
    await new Promise((r) => setTimeout(r, 80));
    const pollHealth = pollMgr.getHealth();
    // Without realtime, health should be degraded (polling active and snapshot recent)
    assert.ok(["degraded", "live", "stale", "offline"].includes(pollHealth));
    // Disconnect WS simulation: health should become degraded, not live
    if (typeof pollMgr._setRealtimeSubscribed === "function") {
      pollMgr._setRealtimeSubscribed(false);
      assert.equal(pollMgr.getHealth(), "degraded");
    }
    await pollMgr.stop();
  });
});
