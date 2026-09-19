import { callRpc, jsonResponse, requireGatewayAuth } from "../_shared/supabase.mjs";

export default async function snapshot(context, req) {
  const runId = req.query?.run_id;
  if (!runId) {
    context.res = jsonResponse(400, { error: "run_id_required" });
    return;
  }

  try {
    requireGatewayAuth(req, context);
    const result = await callRpc("get_run_snapshot", { p_run_id: runId });
    if (!result) {
      context.res = jsonResponse(404, { error: "run_not_found", message: runId });
      return;
    }
    context.res = jsonResponse(200, result);
  } catch (error) {
    if (error.status === 401) {
      context.res = jsonResponse(401, { error: "unauthorized", message: error.message });
      return;
    }
    context.log.error(error, error.details ?? error.message);
    const message = error.exposeMessage === false ? "internal error" : "snapshot failure";
    context.res = jsonResponse(500, { error: "snapshot_failure", message });
  }
}
