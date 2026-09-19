function esc(s){ return String(s ?? "—").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}
export function renderContacts(contacts){
  const list = Array.isArray(contacts)?contacts:[];
  if(list.length===0) return `<div data-testid="empty-contacts" style="padding:16px; color:var(--ink-muted);">Sin comunicaciones registradas.</div>`;
  return `<div data-testid="contacts-list" style="display:flex; flex-direction:column; gap:8px;">${list.map(c=>`
    <div data-testid="contact-item" data-entity-id="${esc(c.entity.entity_id)}" style="padding:12px; border:1px solid var(--line); border-radius:8px;">
      <div style="display:flex; gap:8px; align-items:center;"><span style="font-weight:600;">${esc(c.entity.name)}</span><span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(c.entity.role)} · ${esc((c.entity.jurisdiction_zone_ids||[]).join(", "))}</span></div>
      <div style="font-size:12px; color:var(--ink-muted);">${c.relatedActions.length} acciones relacionadas · ${c.outcomes.length} outcomes · ${c.outbox.length} despachos</div>
      ${c.outcomes.some(o=>o.transcript) ? `<div style="font-size:12px; color:var(--ink-muted); font-style:italic;">${esc(c.outcomes.find(o=>o.transcript)?.transcript ?? "")}</div>` : ""}
      ${c.relatedActions.length===0 && c.outbox.length===0 && c.outcomes.length===0 ? `<div style="font-size:12px; color:var(--ink-muted);">Sin comunicaciones registradas.</div>` : ""}
    </div>`).join("")}</div>`;
}
export default {renderContacts};
