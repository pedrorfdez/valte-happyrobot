import { callRpc, jsonResponse, requireGatewayAuth } from "../_shared/supabase.mjs";

const RATE_WINDOW_MS = 60_000;
const RATE_MAX = 60;
const rateBuckets = new Map();

const actors = new Set(["scenario-controller", "happyrobot", "operator"]);
const commandTypes = new Set([
  "receive_source_input", "upsert_signal", "replace_plan",
  "approve_action", "reject_action", "record_outcome",
  "advance_clock", "pause_run", "resume_run", "abort_run", "complete_run", "create_lesson"
]);
const requiredFields = [
  "command_id", "run_id", "pack_id", "pack_version", "pack_digest",
  "expected_state_version", "actor", "command_type", "payload", "causation_id"
];

const parseBody = (body) => typeof body === "string" ? JSON.parse(body) : body;

function checkRateLimit(req) {
  const ip = req.headers?.["x-forwarded-for"]?.split(",")[0]?.trim() || req.headers?.["x-real-ip"] || "unknown";
  const now = Date.now();
  const entry = rateBuckets.get(ip);
  if (!entry || now - entry.start > RATE_WINDOW_MS) {
    rateBuckets.set(ip, { count: 1, start: now });
    return null;
  }
  entry.count += 1;
  if (entry.count > RATE_MAX) return `rate limit exceeded for ${ip}`;
  return null;
}

function invalid(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return "body must be an object";
  const allowed = new Set(requiredFields);
  const extra = Object.keys(body).filter((k) => !allowed.has(k));
  if (extra.length) return `unexpected fields: ${extra.join(", ")}`;
  const missing = requiredFields.filter((field) => !(field in body));
  if (missing.length) return `missing fields: ${missing.join(", ")}`;
  if (typeof body.command_id !== "string" || !/^[A-Za-z0-9._:-]{8,128}$/.test(body.command_id)) return "command_id must match ^[A-Za-z0-9._:-]{8,128}$";
  if (typeof body.run_id !== "string" || !body.run_id.trim()) return "run_id must be a non-empty string";
  if (typeof body.causation_id !== "string" && body.causation_id !== null) return "causation_id must be string or null";
  if (!actors.has(body.actor)) return "actor is not allowlisted";
  if (!commandTypes.has(body.command_type)) return "command_type is not allowlisted";
  if (!Number.isSafeInteger(body.expected_state_version) || body.expected_state_version < 0) return "expected_state_version must be a non-negative safe integer";
  if (!/^[a-f0-9]{64}$/.test(body.pack_digest)) return "pack_digest must be 64 lowercase hexadecimal characters";
  if (!body.payload || typeof body.payload !== "object" || Array.isArray(body.payload)) return "payload must be an object";
  // Límites defensivos contra payloads gigantes
  if (JSON.stringify(body).length > 200_000) return "command payload too large";
  return null;
}

const isObject = (value) => value && typeof value === "object" && !Array.isArray(value);

function recordsFor(command) {
  if (command.command_type === "upsert_signal") return [["signal", command.payload.signal]];
  if (command.command_type === "record_outcome") return [["outcome", command.payload.outcome]];
  if (command.command_type !== "replace_plan") return [];
  if (!Array.isArray(command.payload.incidents) || !Array.isArray(command.payload.actions)) {
    return { error: "replace_plan requires incident and action arrays" };
  }
  return [
    ...command.payload.incidents.map((record) => ["incident", record]),
    ["plan", command.payload.plan],
    ...command.payload.actions.map((record) => ["action", record])
  ];
}

function validateDomainIdentity(command) {
  const records = recordsFor(command);
  if (records.error) return records.error;
  for (const [kind, record] of records) {
    if (!isObject(record)) return `${kind} must be an object`;
    if (record.contract_version !== "2.0.0") return `${kind}.contract_version must be 2.0.0`;
    for (const field of ["run_id", "pack_id", "pack_version", "pack_digest"]) {
      if (record[field] !== command[field]) return `${kind}.${field} differs from command`;
    }
  }
  return null;
}

function validateApproverAllowlist(command) {
  if (command.command_type !== "replace_plan") return null;
  const actions = command.payload?.actions;
  if (!Array.isArray(actions)) return null;
  for (const action of actions) {
    if (!isObject(action)) continue;
    if (action.status === "pending_approval" && action.approval_policy === "human_required") {
      const ids = action.approver_entity_ids;
      if (!Array.isArray(ids) || ids.length === 0) {
        return `action ${action.action_id ?? ""} approver_entity_ids must be non-empty unique`;
      }
      if (new Set(ids).size !== ids.length) {
        return `action ${action.action_id ?? ""} approver_entity_ids must be unique`;
      }
      if (ids.some((id) => typeof id !== "string" || !id.trim())) {
        return `action ${action.action_id ?? ""} approver_entity_ids must be non-empty strings`;
      }
      if (action.approvals_required !== 1) {
        return `action ${action.action_id ?? ""} approvals_required must be 1`;
      }
    }
  }
  return null;
}

const errorStatus = (code) => {
  if (code === "run_not_found") return 404;
  if (["version_conflict", "idempotency_mismatch", "pack_context_mismatch"].includes(code)) return 409;
  return 400;
};

export default async function commands(context, req) {
  try {
    requireGatewayAuth(req, context);
    const rateError = checkRateLimit(req);
    if (rateError) {
      context.res = jsonResponse(429, { ok: false, error: "rate_limited", message: rateError });
      return;
    }
    let command;
    try {
      command = parseBody(req.body);
    } catch {
      context.res = jsonResponse(400, { ok: false, error: "invalid_command", message: "body must be valid JSON" });
      return;
    }
    const transportError = invalid(command);
    if (transportError) {
      context.res = jsonResponse(400, { ok: false, error: "invalid_command", message: transportError });
      return;
    }

    const domainError = validateDomainIdentity(command);
    if (domainError) {
      context.res = jsonResponse(400, { ok: false, error: "invalid_contract_identity", message: domainError });
      return;
    }

    const approverError = validateApproverAllowlist(command);
    if (approverError) {
      context.res = jsonResponse(400, { ok: false, error: "invalid_approver", message: approverError });
      return;
    }

    const result = await callRpc("apply_command", { p_command: command });
    context.res = jsonResponse(result.error ? errorStatus(result.error) : 200, result);
  } catch (error) {
    context.log.error(error, error.details ?? error.message);
    if (error.status === 401) {
      context.res = jsonResponse(401, { ok: false, error: "unauthorized", message: error.message });
      return;
    }
    const message = error.exposeMessage === false
      ? "internal error"
      : "gateway failure";
    context.res = jsonResponse(500, {
      ok: false,
      error: "gateway_failure",
      message
    });
  }
}
