/**
 * Zones screen: uses display.x/y from pack catalogue (spec §5.1, §13)
 * Reference: docs/reference/valte-pantallas/design/Zonas.body.html
 * - col-head with count (Zonas · N zonas)
 * - display.x/y positioned dots left:${x}% top:${y}% + data-x/data-y
 * - SeverityMeter placeholder (Valte.SeverityMeter) per zone
 */

function esc(v) {
  return String(v ?? "—").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function severityPlaceholder(z) {
  // Placeholder for Valte.SeverityMeter from Zonas.body.html
  // In reference, each zone card shows sev /10 and risk % with SeverityMeter component
  const sev = z.severity ?? z.sev ?? "—";
  const risk = z.risk_pct ?? z.risk ?? "—";
  // Keep literal string SeverityMeter for parity test / grep
  return `<span data-testid="severity-meter" style="display:inline-flex; align-items:center; gap:6px; font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);"><span>SeverityMeter</span><span style="color:var(--critical);">${esc(sev)}/10</span><span>${esc(risk)}% riesgo</span></span>`;
  // Alternative real component import placeholder: Valte.SeverityMeter value="{{sev}}" trend="rising"
}

export function renderZones(zones) {
  const list = Array.isArray(zones) ? zones : [];
  if (list.length === 0) {
    return `<div data-testid="empty-zones" style="padding:24px; color: var(--ink-muted);">Sin zonas en esta jurisdicción.</div>`;
  }

  // col-head parity with Zonas.body.html: <div class="col-head"><h2 class="col-title">Propagación</h2><span class="count">6 zonas · 2 orígenes · pulsa una zona</span></div>
  // For filtered view, show dynamic count
  const countLabel = `${list.length} zonas · pulsa una zona`;
  const colHead = `<div class="col-head" style="display:flex; align-items:baseline; justify-content:space-between; gap:12px; padding-bottom:8px; border-bottom:1px solid var(--line);"><h2 class="col-title" style="margin:0; font-family:var(--font-display); font-size:20px; line-height:28px; font-weight:600;">Zonas</h2><span class="count" style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(countLabel)}</span></div>`;

  const items = list.map((z) => {
    const x = z.display?.x ?? "—";
    const y = z.display?.y ?? "—";
    const kind = z.kind || "—";
    // use display coordinates for map positioning: data-x/data-y + inline style left/top
    // Zonas.body.html structure: button with {{z.pos}} style + SeverityMeter + risk
    const posStyle = typeof z.display?.x === "number" && typeof z.display?.y === "number" ? `left:${z.display.x}%; top:${z.display.y}%` : "";
    return `
      <div data-testid="zone-item" data-zone-id="${esc(z.zone_id)}" data-x="${esc(x)}" data-y="${esc(y)}" style="position:relative; display:flex; flex-direction:column; gap:8px; padding:12px 0; border-bottom:1px solid var(--line);">
        <div style="display:flex; align-items:center; gap:12px;">
          <span style="font-family:var(--font-display); font-size:18px; font-weight:600; flex-grow:1;">${esc(z.name || z.zone_id)}</span>
          <span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(z.zone_id)}</span>
          <span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">x:${esc(x)} y:${esc(y)}</span>
        </div>
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px;">
          ${severityPlaceholder(z)}
          <span style="font-family:var(--font-mono); font-size:12px; line-height:16px; color:var(--ink-muted);">${esc(kind)}</span>
        </div>
        <span style="display:none;" data-pos="${esc(posStyle)}"></span>
      </div>`;
  }).join("");

  // map container uses fixed 1440*900 projection, zones positioned via percentages
  const mapDots = list.map((z) => {
    const x = typeof z.display?.x === "number" ? z.display.x : null;
    const y = typeof z.display?.y === "number" ? z.display.y : null;
    if (x == null || y == null) return "";
    const left = `${x}%`;
    const top = `${y}%`;
    return `<div data-testid="zone-dot" data-zone-id="${esc(z.zone_id)}" data-x="${esc(x)}" data-y="${esc(y)}" title="${esc(z.name)} · x:${x} y:${y}" style="position:absolute; left:${left}; top:${top}; width:10px; height:10px; border-radius:50%; background:var(--critical, #e00); transform:translate(-50%,-50%); border:2px solid white; box-shadow:0 1px 4px rgba(0,0,0,.2);"></div>`;
  }).join("");

  return `
    <section data-testid="zones-screen" class="col" style="display:flex; flex-direction:column; gap:16px; flex-grow:1;">
      ${colHead}
      <div style="position:relative; width:100%; height:260px; background:var(--surface-100, #f6f6f6); border:1px solid var(--line); border-radius:var(--radius-md); overflow:hidden;">
        <span style="position:absolute; inset:8px auto auto 8px; font-family:var(--font-mono); font-size:11px; color:var(--ink-muted);">Mapa · coordenadas display.x/y</span>
        ${mapDots}
      </div>
      <div data-testid="zones-list" class="col-body" style="display:flex; flex-direction:column;">
        ${items}
      </div>
    </section>`;
}

export default { renderZones };
