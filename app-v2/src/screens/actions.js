function esc(s){ return String(s ?? "—").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}
export function renderActions(actions, viewer) {
  const list = Array.isArray(actions) ? actions : [];
  if (list.length===0) return `<div data-testid="empty-actions" style="padding:16px; color:var(--ink-muted);">Sin acciones en esta jurisdicción.</div>`;
  return `<div data-testid="actions-list" style="display:flex; flex-direction:column; gap:8px;">${list.map(a=>{
    const isPending = a.status === "pending_approval";
    const approvers = Array.isArray(a.approver_entity_ids) ? a.approver_entity_ids : [];
    const canDecide = Boolean(isPending && viewer && viewer.entity_id && approvers.includes(viewer.entity_id));
    const buttons = canDecide ? `
      <div style="display:flex; gap:8px; margin-top:10px; align-items:center;">
        <button data-testid="approve-btn" data-action-id="${esc(a.action_id)}" data-decide="approve" style="padding:6px 12px; border-radius:6px; border:1px solid var(--line-strong); background:var(--ink); color:var(--on-ink); font-family:var(--font-mono); font-size:12px; cursor:pointer;">Aprobar</button>
        <button data-testid="reject-btn" data-action-id="${esc(a.action_id)}" data-decide="reject" style="padding:6px 12px; border-radius:6px; border:1px solid var(--line-strong); background:var(--surface-100); color:var(--ink); font-family:var(--font-mono); font-size:12px; cursor:pointer;">Rechazar</button>
        <span data-testid="action-decision-feedback" data-action-id="${esc(a.action_id)}" style="font-size:12px; color:var(--ink-muted);"></span>
      </div>` : (isPending ? `<div style="margin-top:8px; font-size:11px; color:var(--ink-muted); font-family:var(--font-mono);">Aprobadores: ${esc(approvers.join(", ") || "—")} · solo ellos pueden decidir</div>` : "");
    return `
    <div data-testid="action-item" data-action-id="${esc(a.action_id)}" style="padding:12px; border:1px solid var(--line); border-radius:8px;">
      <div style="display:flex; gap:8px; align-items:center;"><span style="font-weight:600;">${esc(a.action_id)}</span><span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(a.status)} · ${esc(a.approval_policy ?? "")}</span></div>
      <div style="font-size:13px;">Actor: ${esc(a.actor_id)} · Incident: ${esc(a.incident_id)}</div>
      <div style="font-size:12px; color:var(--ink-muted);">${esc(a.reasoning ?? "")}</div>
      ${a.evidence && a.evidence.length ? `<div style="font-size:11px; color:var(--ink-muted); font-style:italic;">${esc(a.evidence[0]?.summary ?? "")}</div>` : ""}
      ${buttons}
    </div>`;
  }).join("")}</div>`;
}
export default {renderActions};
