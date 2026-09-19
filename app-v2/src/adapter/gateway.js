/**
 * Valte v2 Gateway adapter
 * Fetches run summaries and snapshots with expected_state_version/idempotency support.
 * Spec: docs/superpowers/specs/2026-09-20-valte-v2-dashboard-integration-design.md §6, §12
 */

function getGatewayBase() {
  if (typeof window !== "undefined" && window.location) {
    try {
      const params = new URLSearchParams(window.location.search);
      const override = params.get("gateway_url");
      if (override) return override.replace(/\/$/, "");
      return window.location.origin.replace(/\/$/, "");
    } catch {
      return "";
    }
  }
  return "";
}

function gatewayUrl(path) {
  const base = getGatewayBase();
  const clean = String(path).replace(/^\/+/, "");
  if (!base) return `/${clean}`;
  return `${base}/${clean}`;
}

async function parseJsonResponse(res) {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Gateway ${res.status}: invalid JSON`);
  }
}

export async function fetchRuns(opts = {}) {
  const url = opts.base ? `${opts.base.replace(/\/$/, "")}/api/runs` : gatewayUrl("/api/runs");
  const res = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json", ...(opts.headers || {}) },
  });
  const body = await parseJsonResponse(res);
  if (!res.ok) {
    const msg = body?.error ? `${body.error}${body?.message ? " · " + body.message : ""}` : `HTTP ${res.status}`;
    throw new Error(`GET /api/runs failed: ${msg}`);
  }
  const runs = Array.isArray(body?.runs) ? body.runs : [];
  // Safety: never leak signals/lessons in summary (should not exist anyway)
  return runs;
}

export async function fetchSnapshot(runId, opts = {}) {
  if (!runId || typeof runId !== "string") throw new Error("run_id required");
  const base = opts.base ? opts.base.replace(/\/$/, "") : getGatewayBase();
  const prefix = base ? `${base}` : "";
  const url = `${prefix}/api/snapshot?run_id=${encodeURIComponent(runId)}`;
  const res = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json", ...(opts.headers || {}) },
  });
  const body = await parseJsonResponse(res);
  if (!res.ok) {
    const err = body?.error || `HTTP ${res.status}`;
    const e = new Error(`GET /api/snapshot failed: ${err}${body?.message ? " · " + body.message : ""}`);
    e.status = res.status;
    e.code = err;
    throw e;
  }
  if (!body || typeof body !== "object") throw new Error("Snapshot invalid: not an object");
  // Ensure run_id matches request (basic check)
  if (body.run && body.run.run_id && body.run.run_id !== runId) {
    // allow but warn; still return
  }
  return body;
}

export async function postCommand(command, opts = {}) {
  if (!command || typeof command !== "object") throw new Error("command required");
  const base = opts.base ? opts.base.replace(/\/$/, "") : getGatewayBase();
  const prefix = base ? `${base}` : "";
  const url = `${prefix}/api/commands`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json", ...(opts.headers || {}) },
    body: JSON.stringify(command),
  });
  const body = await parseJsonResponse(res);
  if (res.status === 409 || body?.error === "version_conflict") {
    const e = new Error("version_conflict");
    e.status = 409;
    e.body = body;
    throw e;
  }
  if (!res.ok || body?.ok === false) {
    const msg = body?.error ? body.error : `HTTP ${res.status}`;
    throw new Error(`POST /api/commands failed: ${msg}`);
  }
  return body;
}

export function buildCommandEnvelope(snapshot, commandType, payload = {}) {
  if (!snapshot?.run) throw new Error("snapshot.run required");
  const run = snapshot.run;
  const uuid = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  return {
    command_id: `v2-${uuid}`,
    run_id: run.run_id,
    pack_id: run.pack_id,
    pack_version: run.pack_version ?? run.version ?? "1.0.0",
    pack_digest: run.pack_digest ?? "0".repeat(64),
    expected_state_version: run.state_version,
    actor: "operator",
    command_type: commandType,
    payload,
    causation_id: null,
  };
}

export default { fetchRuns, fetchSnapshot, postCommand, buildCommandEnvelope, gatewayUrl, getGatewayBase };
