/**
 * List screen: renders run summaries from GET /api/runs
 * Clicking a run always enters as Coordination (spec §6, §13)
 */

export function renderList(runs, onSelect) {
  const list = Array.isArray(runs) ? runs : [];
  if (list.length === 0) {
    return `<div data-testid="empty-runs" style="padding:24px; color: var(--ink-muted);">Sin escenarios registrados.</div>`;
  }
  const items = list.map((run, idx) => {
    const name = run.name || run.run_id;
    const status = run.status || "—";
    const zones = run.zone_count ?? 0;
    const incidents = run.active_incident_count ?? 0;
    const pending = run.pending_approval_count ?? 0;
    const num = String(idx + 1).padStart(2, "0");
    // data-run-id used by browser test click simulation
    return `
      <a href="#" data-run-id="${run.run_id}" data-testid="run-item" class="row" style="text-decoration:none; display:flex; align-items:center; gap:32px; padding:28px 0; border-bottom:1px solid var(--line, #222);">
        <span style="font-family:var(--font-mono); font-size:13px; color:var(--ink-muted); width:24px;">${num}</span>
        <span class="row-name" style="flex-grow:1; font-family:var(--font-display); font-size:32px; line-height:32px;">${name}</span>
        <span style="font-family:var(--font-mono); font-size:12px; color:var(--ink-muted);">${status} · ${zones} zonas · ${incidents} activas · ${pending} por aprobar</span>
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M5 12h14"></path><path d="M13 6l6 6-6 6"></path></svg>
      </a>`;
  }).join("");
  return `<nav data-testid="runs-list" style="display:flex; flex-direction:column; border-top:1px solid var(--line-strong);">${items}</nav>`;
}

// DOM helper to attach click handlers (used by main.js in browser)
export function attachListHandlers(container, onSelect) {
  if (!container) return;
  container.addEventListener("click", (e) => {
    const link = e.target.closest("a[data-run-id]");
    if (!link) return;
    e.preventDefault();
    const runId = link.getAttribute("data-run-id");
    if (onSelect) onSelect(runId);
  });
}

export default { renderList, attachListHandlers };
