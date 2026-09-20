/**
 * Incidents column parity with PanelCoordinacion.body.html
 * Reference: docs/reference/valte-pantallas/design/PanelCoordinacion.body.html
 * - col-head with count (N active · M)
 * - StatusBadge per incident (tone/glyph/label derived from state/priority)
 */

function esc(s){ return String(s ?? "—").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");}

function badgeForIncident(inc) {
  const state = String(inc.state || "").toLowerCase();
  const pri = String(inc.priority || "").toUpperCase();
  // Map to Valte.StatusBadge parity: active P0 critical, active other warning, closed success
  let tone = "info";
  let glyph = "●";
  let label = esc(inc.state || "—");
  if (state === "closed" || state === "resolved" || state === "finalizado") {
    tone = "success"; glyph = "✓"; label = "Cerrado";
  } else if (state === "active" && pri === "P0") {
    tone = "critical"; glyph = "●"; label = "Crítico";
  } else if (state === "active") {
    tone = "warning-solid"; glyph = "◐"; label = "Activo";
  } else if (state === "pending") {
    tone = "warning"; glyph = "◐"; label = "Pendiente";
  }
  // Keep literal string StatusBadge for parity / grep, matches Zonas/PanelCoordinacion Valte.StatusBadge component
  // In real DOM, this would be <x-import component-from-global-scope="Valte.StatusBadge" tone="{{tone}}" glyph="{{glyph}}" label="{{label}}"></x-import>
  return `<span data-testid="status-badge" data-tone="${esc(tone)}" style="display:inline-flex; align-items:center; gap:6px; font-family:var(--font-mono); font-size:12px; padding:2px 8px; border-radius:999px; border:1px solid var(--line); background:var(--surface-100); color:var(--ink-muted);"><span>StatusBadge</span><span>${esc(glyph)}</span><span>${esc(label)}</span></span>`;
}

export function renderIncidents(incidents) {
  const list = Array.isArray(incidents) ? incidents : [];
  if (list.length === 0) return `<div data-testid="empty-incidents" style="padding:16px; color:var(--ink-muted);">Sin incidentes en esta jurisdicción.</div>`;
  const active = list.filter(i => String(i.state).toLowerCase() === "active").length;
  const closed = list.length - active;
  const countLabel = `${active} activos · ${list.length} en total${closed ? ` · ${closed} cerrados` : ""}`;
  const colHead = `<div class="col-head" style="display:flex; align-items:baseline; justify-content:space-between; gap:12px; padding-bottom:8px; border-bottom:1px solid var(--line);"><h2 class="col-title" style="margin:0; font-family:var(--font-display); font-size:20px; line-height:28px; font-weight:600;">Incidentes</h2><span class="count" style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(countLabel)}</span></div>`;
  return `<section data-testid="incidents-screen" class="col" style="display:flex; flex-direction:column; gap:12px; width:360px; flex-shrink:0;">
    ${colHead}
    <div data-testid="incidents-list" class="col-body" style="display:flex; flex-direction:column; gap:8px;">${list.map(i=>`
    <div data-testid="incident-item" data-incident-id="${esc(i.incident_id)}" style="display:flex; flex-direction:column; gap:8px; padding:12px 0; border-bottom:1px solid var(--line);">
      <div style="display:flex; align-items:center; gap:12px;"><span style="font-size:16px; line-height:24px; font-weight:600; flex-grow:1;">${esc(i.incident_id)}</span>${badgeForIncident(i)}</div>
      <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;"><span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(i.state)} · ${esc(i.priority ?? "")}</span><span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">Zonas: ${esc((i.zone_ids||[]).join(", "))}</span></div>
      ${i.evidence && i.evidence.length ? `<div style="font-size:12px; color:var(--ink-muted);">${i.evidence.map(e=>esc(e.summary||e.kind)).join(", ")}</div>` : ""}
    </div>`).join("")}</div>
  </section>`;
}
export default {renderIncidents};
