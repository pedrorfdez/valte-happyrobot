import { callRpc, jsonResponse } from "../_shared/supabase.mjs";

export default async function snapshot(context, req) {
  const runId = req.query?.run_id;
  if (!runId) {
    context.res = jsonResponse(400, { error: "run_id_required" });
    return;
  }

  try {
    const result = await callRpc("get_run_snapshot", { p_run_id: runId });
    if (!result) {
      context.res = jsonResponse(404, { error: "run_not_found", message: runId });
      return;
    }
    context.res = jsonResponse(200, result);
  } catch (error) {
    context.log.error(error);
    context.res = jsonResponse(500, { error: "snapshot_failure", message: error.message });
  }
}
