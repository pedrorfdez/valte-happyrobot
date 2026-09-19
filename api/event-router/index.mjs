import { callRpc, jsonResponse, requireGatewayAuth, requiredEnv } from "../_shared/supabase.mjs";

const HAPPYROBOT_TIMEOUT_MS = 20_000;
const interactionModes = new Set(["dry-run", "web_voice", "email", "pstn"]);

const workflowSettingByDestination = {
  "crisis-intake": "HAPPYROBOT_INTAKE_WORKFLOW_ID",
  "crisis-command": "HAPPYROBOT_COMMAND_WORKFLOW_ID",
  "crisis-response-coordination": "HAPPYROBOT_COORDINATION_WORKFLOW_ID"
};

async function happyRobot(path, options = {}) {
  const baseUrl = requiredEnv("HAPPYROBOT_BASE_URL").replace(/\/$/, "");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), HAPPYROBOT_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: {
        authorization: `Bearer ${requiredEnv("HAPPYROBOT_KEY")}`,
        "content-type": "application/json",
        accept: "application/json",
        ...options.headers
      },
      signal: controller.signal
    });
  } finally {
    clearTimeout(timeout);
  }
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!response.ok) throw new Error(`HappyRobot ${response.status}: ${text}`);
  return data;
}

export default async function eventRouter(context, req) {
  try {
    requireGatewayAuth(req, context);
  } catch (error) {
    if (error.status === 401) {
      context.res = jsonResponse(401, { error: "unauthorized", message: error.message });
      return;
    }
    throw error;
  }
  let body;
  try {
    body = typeof req.body === "string" ? JSON.parse(req.body) : (req.body ?? {});
  } catch {
    context.res = jsonResponse(400, { error: "invalid_request", message: "body must be valid JSON" });
    return;
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    context.res = jsonResponse(400, { error: "invalid_request", message: "body must be an object" });
    return;
  }

  const limit = 1;
  const runId = body.run_id ?? null;
  if (runId !== null && (typeof runId !== "string" || !runId.trim())) {
    context.res = jsonResponse(400, { error: "invalid_request", message: "run_id must be a non-empty string" });
    return;
  }
  const interactionMode = body.interaction_mode ?? "dry-run";
  if (!interactionModes.has(interactionMode)) {
    context.res = jsonResponse(400, {
      error: "invalid_request",
      message: "interaction_mode must be dry-run, web_voice, email, or pstn"
    });
    return;
  }

  try {
    const jobs = await callRpc("claim_outbox", { p_limit: limit, p_run_id: runId });
    if (!jobs.length) {
      context.res = jsonResponse(200, { claimed: 0, dispatched: 0, failed: 0, results: [] });
      return;
    }

    const job = jobs[0];
    let succeeded = false;
    let errorMessage = null;
    let workflowRunId = null;
    try {
      const settingName = workflowSettingByDestination[job.destination];
      if (!settingName) throw new Error(`destination is not allowlisted: ${job.destination}`);
      const workflowId = requiredEnv(settingName);
      const workflowPayload = {
        dispatch_id: job.dispatch_id,
        run_id: job.run_id,
        event: job.payload
      };
      if (job.destination === "crisis-response-coordination") {
        workflowPayload.interaction_mode = interactionMode;
      }
      const launched = await happyRobot(`/workflows/${workflowId}/runs`, {
        method: "POST",
        body: JSON.stringify({
          environment: requiredEnv("HAPPYROBOT_ENV"),
          payload: workflowPayload
        })
      });
      workflowRunId = launched?.run_id
        ?? launched?.queued_run_ids?.[0]
        ?? launched?.id
        ?? launched?.data?.run_id
        ?? launched?.data?.queued_run_ids?.[0]
        ?? launched?.data?.id
        ?? launched?.data?.run?.run_id
        ?? launched?.data?.run?.id
        ?? null;
      succeeded = true;
    } catch (error) {
      errorMessage = error.message;
    }

    const retryable = !(
      job.destination === "crisis-response-coordination"
      && interactionMode !== "dry-run"
    );
    const receipt = await callRpc("finish_outbox", {
      p_outbox_id: job.outbox_id,
      p_dispatch_id: job.dispatch_id,
      p_succeeded: succeeded,
      p_error: errorMessage,
      p_retryable: retryable
    });
    const results = [{
      outbox_id: job.outbox_id,
      destination: job.destination,
      dispatch_id: job.dispatch_id,
      workflow_run_id: workflowRunId,
      succeeded,
      receipt
    }];

    context.res = jsonResponse(200, {
      claimed: results.length,
      dispatched: results.filter((item) => item.succeeded).length,
      failed: results.filter((item) => !item.succeeded).length,
      results
    });
  } catch (error) {
    if (error.status === 401) {
      context.res = jsonResponse(401, { error: "unauthorized", message: error.message });
      return;
    }
    context.log.error(error, error.details ?? error.message);
    const message = error.exposeMessage === false ? "internal error" : "event router failure";
    context.res = jsonResponse(500, { error: "event_router_failure", message });
  }
}
