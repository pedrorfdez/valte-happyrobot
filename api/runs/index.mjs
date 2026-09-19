import { callRpc, jsonResponse, requireGatewayAuth } from "../_shared/supabase.mjs";

export default async function runs(context, req) {
  if (req.method && req.method !== "GET") {
    context.res = jsonResponse(405, { error: "method_not_allowed" });
    return;
  }
  try {
    requireGatewayAuth(req, context);
    const rows = await callRpc("list_runs", {});
    const list = Array.isArray(rows) ? rows : [];
    const mapped = list.map((r) => ({
      run_id: r.run_id,
      pack_id: r.pack_id,
      name: r.name ?? r.pack_id ?? r.run_id,
      status: r.status,
      scenario_now: r.scenario_now,
      state_version: r.state_version,
      zone_count: Number(r.zone_count ?? 0),
      active_incident_count: Number(r.active_incident_count ?? 0),
      pending_approval_count: Number(r.pending_approval_count ?? 0),
    }));
    context.res = jsonResponse(200, { runs: mapped });
  } catch (error) {
    if (error.status === 401) {
      context.res = jsonResponse(401, { error: "unauthorized", message: error.message });
      return;
    }
    context.log.error(error, error.details ?? error.message);
    const message = error.exposeMessage === false ? "internal error" : "runs failure";
    context.res = jsonResponse(500, { error: "runs_failure", message });
  }
}
