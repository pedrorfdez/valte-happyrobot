/**
 * Contacts screen - parity with Contactos.body.html
 * Reference: docs/reference/valte-pantallas/design/Contactos.body.html
 * - No send/call/email controls (no Enviar, Llamar, Tomar la llamada, Escuchar, Colgar)
 * - Only Sin comunicaciones registradas when relatedActions empty
 * - simulated_transcript rendered as sanitized text (outcomes.transcript)
 * - No signal leakage
 */
function esc(s){ return String(s ?? "—").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");}
export function renderContacts(contacts){
  const list = Array.isArray(contacts)?contacts:[];
  if(list.length===0) return `<div data-testid="empty-contacts" style="padding:16px; color:var(--ink-muted);">Sin comunicaciones registradas.</div>`;
  return `<div data-testid="contacts-list" style="display:flex; flex-direction:column; gap:8px;">${list.map(c=>{
    const entity = c.entity || {};
    const related = Array.isArray(c.relatedActions) ? c.relatedActions : [];
    const outbox = Array.isArray(c.outbox) ? c.outbox : [];
    const outcomes = Array.isArray(c.outcomes) ? c.outcomes : [];
    // Territory / role line parity with Contactos.body.html detail header
    const roleLabel = esc(entity.role || "—");
    const name = esc(entity.name || entity.entity_id || "—");
    const jurisdiction = esc((entity.jurisdiction_zone_ids||[]).join(", ") || "—");
    const countLine = `${related.length} acciones relacionadas · ${outcomes.length} outcomes · ${outbox.length} despachos`;
    // Find first simulated_transcript (outcomes.transcript)
    const transcriptEntry = outcomes.find(o=> typeof o.transcript === "string" && o.transcript.trim() !== "");
    const transcriptHtml = transcriptEntry ? `<div data-testid="contact-transcript" style="display:flex; flex-direction:column; gap:6px; margin-top:8px;"><span class="lbl" style="font-family:var(--font-mono); font-size:11px; color:var(--ink-muted);">Transcripción en directo</span><div class="tline agent" style="font-size:12px; line-height:16px; background:var(--surface-000); padding:8px; border-radius:6px; border:1px solid var(--line);"><span class="who" style="font-weight:600; margin-right:6px;">Agente</span><span>${esc(transcriptEntry.transcript)}</span></div></div>` : "";
    const emptyComms = related.length===0 ? `<div data-testid="empty-contact-comms" style="font-size:12px; color:var(--ink-muted); margin-top:6px;">Sin comunicaciones registradas.</div>` : "";
    // Ensure no send/call controls: intentionally do NOT render any button with Enviar/Llamar/Tomar la llamada/Escuchar/Colgar
    return `
    <div data-testid="contact-item" data-entity-id="${esc(entity.entity_id)}" style="padding:12px; border:1px solid var(--line); border-radius:8px; background:var(--surface-100, #fff);">
      <div style="display:flex; gap:8px; align-items:center;"><span style="font-weight:600;">${name}</span><span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${roleLabel} · ${jurisdiction}</span></div>
      <div style="font-size:12px; color:var(--ink-muted); margin-top:4px;">${esc(countLine)}</div>
      ${transcriptHtml}
      ${emptyComms}
    </div>`;
  }).join("")}</div>`;
}
export default {renderContacts};
