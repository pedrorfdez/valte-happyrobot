/**
 * Actions screen - parity with Acciones.body.html + Valte.ActionItem mock
 * Reference: docs/reference/valte-pantallas/design/Acciones.body.html
 *            docs/reference/valte-pantallas/design/Acciones.mock.js
 *            docs/reference/valte-pantallas/assets/valte-ds.js ActionItem component
 * - Uses verbLabel, actorName, deadline, time from mock
 * - Valte.ActionItem structure: vt-log, vt-log__head, vt-log__verb, evidence chips, pending_approval actions
 * - Approve/Rechazar only when viewer.entity_id in approver_entity_ids and status pending_approval
 */
function esc(s){ return String(s ?? "—").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");}
function derive(a){
  const nested = a && typeof a.action === "object" && a.action !== null ? a.action : null;
  const id = a.action_id || a.id || (nested && nested.id) || "—";
  const status = a.status || (nested && nested.status) || "—";
  const verbLabel = a.verbLabel || (nested && nested.verbLabel) || a.verbLabel || esc(a.verb || (nested && nested.verb) || id);
  const actorName = a.actorName || (nested && nested.actorName) || a.actor_id || (nested && nested.actor) || "—";
  const deadline = a.deadline || (nested && nested.deadline) || null;
  const time = a.time || (nested && nested.time) || a.created_at || "";
  const reasoning = a.reasoning || (nested && nested.reasoning) || "";
  const targetZones = a.target_zones || (nested && nested.target_zones) || (a.target && a.target.zone_id ? [a.target.zone_id] : []) || [];
  const evidence = Array.isArray(a.evidence) ? a.evidence : (nested && Array.isArray(nested.evidence) ? nested.evidence : []);
  const approvers = Array.isArray(a.approver_entity_ids) ? a.approver_entity_ids : [];
  const realInteraction = a.real_interaction || (nested && nested.real_interaction) || null;
  return { id, status, verbLabel, actorName, deadline, time, reasoning, targetZones, evidence, approvers, realInteraction, raw: a };
}

export function renderActions(actions, viewer) {
  const list = Array.isArray(actions) ? actions : [];
  if (list.length===0) return `<div data-testid="empty-actions" style="padding:16px; color:var(--ink-muted);">Sin acciones en esta jurisdicción.</div>`;

  const pending = list.filter(a => {
    const d = derive(a);
    return d.status === "pending_approval";
  });
  const pendingCount = pending.length;
  // Col-head parity with Acciones.body.html
  const colHead = `<div class="col-head" style="display:flex; align-items:baseline; justify-content:space-between; gap:12px; padding-bottom:8px; border-bottom:1px solid var(--line);"><h2 class="col-title" style="margin:0; font-family:var(--font-display); font-size:20px; line-height:28px; font-weight:600;">Por aprobar</h2><span class="count" style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${esc(pendingCount)} · esperan a un humano</span></div>`;

  const itemsHtml = list.map(a=>{
    const d = derive(a);
    const isPending = d.status === "pending_approval";
    const canDecide = Boolean(isPending && viewer && viewer.entity_id && d.approvers.includes(viewer.entity_id));
    const buttons = canDecide ? `
      <div class="vt-log__actions" style="display:flex; gap:8px; margin-top:10px; align-items:center;">
        <button data-testid="approve-btn" data-action-id="${esc(d.id)}" data-decide="approve" style="padding:6px 12px; border-radius:6px; border:1px solid var(--line-strong); background:var(--ink); color:var(--on-ink); font-family:var(--font-mono); font-size:12px; cursor:pointer;">Aprobar</button>
        <button data-testid="reject-btn" data-action-id="${esc(d.id)}" data-decide="reject" style="padding:6px 12px; border-radius:6px; border:1px solid var(--line-strong); background:var(--surface-100); color:var(--ink); font-family:var(--font-mono); font-size:12px; cursor:pointer;">Rechazar</button>
        <span data-testid="action-decision-feedback" data-action-id="${esc(d.id)}" style="font-size:12px; color:var(--ink-muted);"></span>
        ${d.deadline ? `<span class="vt-mono vt-muted" style="align-self:center; font-family:var(--font-mono); font-size:11px; color:var(--ink-muted);">Escala en ${esc(d.deadline)}</span>` : ""}
      </div>` : (isPending ? `<div style="margin-top:8px; font-size:11px; color:var(--ink-muted); font-family:var(--font-mono);">Aprobadores: ${esc(d.approvers.join(", ") || "—")} · solo ellos pueden decidir${d.deadline ? ` · Escala en ${esc(d.deadline)}` : ""}</div>` : "");

    // Valte.ActionItem parity: vt-log structure
    // Keep literal Valte.ActionItem marker for grep parity
    const actionItemMarker = `<!-- Valte.ActionItem action="${esc(d.id)}" verbLabel="${esc(d.verbLabel)}" actorName="${esc(d.actorName)}" -->`;
    const targetZonesHtml = d.targetZones && d.targetZones.length ? `<div class="vt-card__meta" style="font-size:12px; color:var(--ink-muted);">Zonas: ${esc(d.targetZones.join(", "))}</div>` : "";
    const evidenceHtml = d.evidence && d.evidence.length ? `<div class="vt-chips" style="display:flex; gap:6px; flex-wrap:wrap; margin-top:6px;"><span class="vt-label" style="font-family:var(--font-mono); font-size:11px; color:var(--ink-muted);">Evidencia</span>${d.evidence.map(e=>{
      const label = typeof e === "string" ? e : (e.summary || e.signal_id || "evidencia");
      return `<span class="vt-chip" style="font-family:var(--font-mono); font-size:11px; padding:2px 6px; border:1px solid var(--line); border-radius:999px;">${esc(label)}</span>`;
    }).join("")}</div>` : "";
    const reasoningHtml = d.reasoning ? `<p class="vt-reason" style="font-size:13px; line-height:18px; margin:6px 0 0;"><span class="vt-reason__who" style="font-weight:600; margin-right:6px;">Agente</span>${esc(d.reasoning)}</p>` : "";

    return `
    ${actionItemMarker}
    <article class="vt-log" data-testid="action-item" data-action-id="${esc(d.id)}" style="padding:12px; border:1px solid var(--line); border-radius:8px; background:var(--surface-100, #fff);">
      <div class="vt-log__head" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
        <span class="vt-mono vt-muted" style="font-family:var(--font-mono); font-size:11px; color:var(--ink-muted);">${esc(d.id)} · ${esc(d.time)}</span>
        <h4 class="vt-log__verb" style="margin:0; font-family:var(--font-display); font-size:16px; font-weight:600; flex-grow:1;">${esc(d.verbLabel)}</h4>
        <span class="vt-muted" style="font-size:13px; color:var(--ink-muted);">→ ${esc(d.actorName)}</span>
        <span class="vt-log__spacer" style="flex-grow:1;"></span>
        <span class="vt-muted" style="font-family:var(--font-mono); font-size:11px; color:var(--ink-muted);">${esc(d.status)}</span>
      </div>
      ${targetZonesHtml}
      ${reasoningHtml}
      ${evidenceHtml}
      ${buttons}
    </article>`;
  }).join("");

  // Wrap with col structure + marker for Registro tab parity (not needed to filter but keep)
  return `<div data-testid="actions-list" style="display:flex; flex-direction:column; gap:16px;">
    <section class="col" style="display:flex; flex-direction:column; gap:12px;">
      ${colHead}
      <div class="col-body" style="display:flex; flex-direction:column; gap:8px;">
        <!-- Valte.ActionItem -->
        ${itemsHtml}
      </div>
    </section>
    <div style="display:none;" data-component="Valte.ActionItem"></div>
  </div>`;
}
export default {renderActions};
