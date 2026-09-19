function esc(s){ return String(s ?? "—").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}

export function renderIncidents(incidents) {
  const list = Array.isArray(incidents) ? incidents : [];
  if (list.length === 0) return `<div data-testid="empty-incidents" style="padding:16px; color:var(--ink-muted);">Sin incidentes en esta jurisdicción.</div>`;
  return `<div data-testid="incidents-list" style="display:flex; flex-direction:column; gap:8px;">${list.map(i=>`
    <div data-testid="incident-item" data-incident-id="${esc(i.incident_id)}" style="padding:12px; border:1px solid var(--line); border-radius:8px;">
      <div style="display:flex; gap:8px; align-items:center;"><span style="font-weight:600;">${esc(i.incident_id)}</span><span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(i.state)} · ${esc(i.priority ?? "")}</span></div>
      <div style="font-size:13px; color:var(--ink-muted);">Zonas: ${esc((i.zone_ids||[]).join(", "))}</div>
      ${i.evidence && i.evidence.length ? `<div style="font-size:12px; color:var(--ink-muted);">${i.evidence.map(e=>esc(e.summary||e.kind)).join(", ")}</div>` : ""}
    </div>`).join("")}</div>`;
}
export default {renderIncidents};
