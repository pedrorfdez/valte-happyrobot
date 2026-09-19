function esc(s){ return String(s ?? "—").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}
export function renderResources(resources){
  const list = Array.isArray(resources)?resources:[];
  if(list.length===0) return `<div data-testid="empty-resources" style="padding:16px; color:var(--ink-muted);">Sin recursos en esta jurisdicción.</div>`;
  return `<div data-testid="resources-list" style="display:flex; flex-direction:column; gap:8px;">${list.map(r=>`
    <div data-testid="resource-item" data-resource-id="${esc(r.resource_id)}" style="padding:12px; border:1px solid var(--line); border-radius:8px;">
      <div style="font-weight:600;">${esc(r.name || r.resource_id)}</div>
      <div style="font-size:12px; color:var(--ink-muted);">owner: ${esc(r.owner_entity_id)} · ${esc(r.resource_mode)} · zona inicial ${esc(r.initial_zone_id)}</div>
    </div>`).join("")}</div>`;
}
export default {renderResources};
