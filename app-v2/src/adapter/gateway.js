/**
 * Valte v2 Gateway adapter
 * Fetches run summaries and snapshots with expected_state_version/idempotency support.
 * Includes command envelope building, decision helpers, and error handling.
 * Spec: docs/superpowers/specs/2026-09-20-valte-v2-dashboard-integration-design.md §6, §12, §15
 */

const STORAGE_GATEWAY = "valte:v2:gateway_url";

function getGatewayBase() {
  if (typeof window !== "undefined" && window.location) {
    try {
      const params = new URLSearchParams(window.location.search);
      const override = params.get("gateway_url");
      if (override) {
        const clean = override.replace(/\/$/, "");
        try { if (typeof localStorage !== "undefined") localStorage.setItem(STORAGE_GATEWAY, clean); } catch {}
        return clean;
      }
      // try stored gateway from previous dashboard URL
      try {
        if (typeof localStorage !== "undefined") {
          const stored = localStorage.getItem(STORAGE_GATEWAY);
          if (stored) return stored.replace(/\/$/, "");
        }
      } catch {}
      // list screen without override: for local static server (localhost:4174) fallback to Supabase gateway
      // This allows http://localhost:4174/ to work without ?gateway_url= param after first dashboard URL has stored it
      if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
        // try stored first already checked; if still empty, use known Supabase project as dev fallback
        // The dashboard-v2.sh prints the correct gateway_url; this fallback ensures list works on fresh open
        // It is safe because Supabase gateway is public and CORS allows it
        return "https://oeacmfpdhrqzinlhsmuj.supabase.co/functions/v1/gateway";
      }
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
    const e = new Error(`GET /api/runs failed: ${msg}`);
    e.status = res.status;
    e.code = body?.error || `HTTP_${res.status}`;
    throw e;
  }
  const runs = Array.isArray(body?.runs) ? body.runs : [];
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
    e.body = body;
    // 404 run_not_found handled by caller to return to list
    throw e;
  }
  if (!body || typeof body !== "object") throw new Error("Snapshot invalid: not an object");
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

  // 409 version_conflict → otro operador decidió primero
  if (res.status === 409 || body?.error === "version_conflict") {
    const e = new Error(body?.error === "version_conflict" ? "version_conflict" : `POST /api/commands failed: version_conflict`);
    // Ensure message contains version_conflict for test detection
    if (!e.message.includes("version_conflict")) e.message = "version_conflict: " + e.message;
    e.status = 409;
    e.code = "version_conflict";
    e.body = body;
    throw e;
  }

  // 404 run_not_found → return to list
  if (res.status === 404 || body?.error === "run_not_found") {
    const e = new Error(`POST /api/commands failed: run_not_found${body?.message ? " · " + body.message : ""}`);
    e.status = 404;
    e.code = "run_not_found";
    e.body = body;
    throw e;
  }

  if (!res.ok || body?.ok === false) {
    const errCode = body?.error || `HTTP_${res.status}`;
    const msg = body?.message ? `${errCode} · ${body.message}` : errCode;
    const e = new Error(`POST /api/commands failed: ${msg}`);
    e.status = res.status || 400;
    e.code = errCode;
    e.body = body;
    throw e;
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

// --- Decision and run-control helpers ---

export async function approveAction(snapshot, actionId, deciding_entity_id, note = "") {
  if (!actionId || typeof actionId !== "string") throw new Error("action_id required");
  if (!deciding_entity_id || typeof deciding_entity_id !== "string") throw new Error("deciding_entity_id required");
  const payload = { action_id: actionId, deciding_entity_id, note: note ?? "" };
  const envelope = buildCommandEnvelope(snapshot, "approve_action", payload);
  return postCommand(envelope);
}

export async function rejectAction(snapshot, actionId, deciding_entity_id, note = "") {
  if (!actionId || typeof actionId !== "string") throw new Error("action_id required");
  if (!deciding_entity_id || typeof deciding_entity_id !== "string") throw new Error("deciding_entity_id required");
  const payload = { action_id: actionId, deciding_entity_id, note: note ?? "" };
  const envelope = buildCommandEnvelope(snapshot, "reject_action", payload);
  return postCommand(envelope);
}

export async function pauseRun(snapshot) {
  const envelope = buildCommandEnvelope(snapshot, "pause_run", {});
  return postCommand(envelope);
}

export async function resumeRun(snapshot) {
  const envelope = buildCommandEnvelope(snapshot, "resume_run", {});
  return postCommand(envelope);
}

export async function abortRun(snapshot) {
  const envelope = buildCommandEnvelope(snapshot, "abort_run", {});
  return postCommand(envelope);
}

// --- Error helpers ---

export function getVersionConflictMessage() {
  return "otro operador decidió primero";
}

export function isVersionConflictError(err) {
  return !!err && (err.status === 409 || err.code === "version_conflict" || String(err.message).includes("version_conflict"));
}

export function isRunNotFoundError(err) {
  return !!err && (err.status === 404 || err.code === "run_not_found" || String(err.message).includes("run_not_found"));
}

export function isValidationError(err) {
  return !!err && (err.status === 400 || err.code === "invalid_command" || err.code === "invalid_contract_identity" || err.code === "invalid_approver");
}

export function formatCommandError(err) {
  if (!err) return "Error desconocido";
  if (isVersionConflictError(err)) return "otro operador decidió primero";
  if (isRunNotFoundError(err)) return "escenario no encontrado";
  // 400 stable message: preserve Gateway message without local mutation
  if (err.body?.message) return `${err.code || "error"} · ${err.body.message}`;
  if (err.message) return err.message;
  return String(err);
}

// Only Coordination view renders pause/resume/abort (spec §10)
export function canRenderRunControls(viewer) {
  return !!viewer && viewer.role === "coordination";
}

// Legacy alias for tests
export const getRunControlsVisible = canRenderRunControls;

export default {
  fetchRuns,
  fetchSnapshot,
  postCommand,
  buildCommandEnvelope,
  approveAction,
  rejectAction,
  pauseRun,
  resumeRun,
  abortRun,
  gatewayUrl,
  getGatewayBase,
  getVersionConflictMessage,
  isVersionConflictError,
  isRunNotFoundError,
  isValidationError,
  formatCommandError,
  canRenderRunControls,
  getRunControlsVisible,
};
