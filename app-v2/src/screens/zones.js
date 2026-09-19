/**
 * Zones screen: uses display.x/y from pack catalogue (spec §5.1, §13)
 */

function esc(v) {
  return String(v ?? "—").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

export function renderZones(zones) {
  const list = Array.isArray(zones) ? zones : [];
  if (list.length === 0) {
    return `<div data-testid="empty-zones" style="padding:24px; color: var(--ink-muted);">Sin zonas en esta jurisdicción.</div>`;
  }
  const items = list.map((z) => {
    const x = z.display?.x ?? "—";
    const y = z.display?.y ?? "—";
    const kind = z.kind || "—";
    // use display coordinates for map positioning: data-x/data-y + inline style left/top
    return `
      <div data-testid="zone-item" data-zone-id="${esc(z.zone_id)}" data-x="${esc(x)}" data-y="${esc(y)}" style="position:relative; display:flex; flex-direction:column; gap:4px; padding:12px 0; border-bottom:1px solid var(--line);">
        <div style="display:flex; align-items:center; gap:12px;">
          <span style="font-family:var(--font-display); font-size:18px; font-weight:600;">${esc(z.name || z.zone_id)}</span>
          <span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(z.zone_id)}</span>
          <span style="margin-left:auto; font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">x:${esc(x)} y:${esc(y)}</span>
        </div>
        <span style="font-size:13px; color:var(--ink-muted);">${esc(kind)}</span>
      </div>`;
  }).join("");

  // map container uses fixed 1440*900 projection, zones positioned via percentages
  const mapDots = list.map((z) => {
    const x = typeof z.display?.x === "number" ? z.display.x : null;
    const y = typeof z.display?.y === "number" ? z.display.y : null;
    if (x == null || y == null) return "";
    const left = `${x}%`;
    const top = `${y}%`;
    return `<div data-testid="zone-dot" data-zone-id="${esc(z.zone_id)}" title="${esc(z.name)} · x:${x} y:${y}" style="position:absolute; left:${left}; top:${top}; width:10px; height:10px; border-radius:50%; background:var(--critical, #e00); transform:translate(-50%,-50%); border:2px solid white; box-shadow:0 1px 4px rgba(0,0,0,.2);"></div>`;
  }).join("");

  return `
    <section data-testid="zones-screen" style="display:flex; flex-direction:column; gap:16px;">
      <div style="position:relative; width:100%; height:260px; background:var(--surface-100, #f6f6f6); border:1px solid var(--line); border-radius:var(--radius-md); overflow:hidden;">
        <span style="position:absolute; inset:8px auto auto 8px; font-family:var(--font-mono); font-size:11px; color:var(--ink-muted);">Mapa · coordenadas display.x/y</span>
        ${mapDots}
      </div>
      <div data-testid="zones-list" style="display:flex; flex-direction:column;">
        ${items}
      </div>
    </section>`;
}

export default { renderZones };
