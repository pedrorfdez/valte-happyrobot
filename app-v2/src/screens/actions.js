function esc(s){ return String(s ?? "—").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}
export function renderActions(actions) {
  const list = Array.isArray(actions) ? actions : [];
  if (list.length===0) return `<div data-testid="empty-actions" style="padding:16px; color:var(--ink-muted);">Sin acciones en esta jurisdicción.</div>`;
  return `<div data-testid="actions-list" style="display:flex; flex-direction:column; gap:8px;">${list.map(a=>`
    <div data-testid="action-item" data-action-id="${esc(a.action_id)}" style="padding:12px; border:1px solid var(--line); border-radius:8px;">
      <div style="display:flex; gap:8px; align-items:center;"><span style="font-weight:600;">${esc(a.action_id)}</span><span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(a.status)} · ${esc(a.approval_policy ?? "")}</span></div>
      <div style="font-size:13px;">Actor: ${esc(a.actor_id)} · Incident: ${esc(a.incident_id)}</div>
      <div style="font-size:12px; color:var(--ink-muted);">${esc(a.reasoning ?? "")}</div>
    </div>`).join("")}</div>`;
}
export default {renderActions};
