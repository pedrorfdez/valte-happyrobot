/**
 * Valte v2 Dashboard main entry
 * Wires: GET /api/runs → list → coordination → role switcher → jurisdiction projection
 * Adapter: fetchRuns/fetchSnapshot (gateway.js) + buildViewerProjection (projection.js)
 * Header switcher filters entities where role != source (spec §5.2, §7)
 * Zones uses display.x/y (spec §5.1, §13)
 * Re-renders all screens and KPIs on switcher change (spec §16.3)
 */

import {
  fetchRuns,
  fetchSnapshot,
  approveAction,
  rejectAction,
  pauseRun,
  resumeRun,
  abortRun,
  canRenderRunControls,
  isVersionConflictError,
  formatCommandError,
  getVersionConflictMessage,
} from "./adapter/gateway.js";
import { createRealtimeManager, HEALTH } from "./adapter/realtime.js";
import { buildViewerProjection } from "./adapter/projection.js";
import { renderList, attachListHandlers } from "./screens/list.js";
import { renderZones } from "./screens/zones.js";
import { renderIncidents } from "./screens/incidents.js";
import { renderActions } from "./screens/actions.js";
import { renderResources } from "./screens/resources.js";
import { renderContacts } from "./screens/contacts.js";

// Re-export for tests
export { fetchRuns, fetchSnapshot, buildViewerProjection };

const STORAGE_RUN = "valte:v2:run_id";
const STORAGE_VIEWER = "valte:v2:viewer";

// State
let currentRunId = null;
let snapshotCache = null;
let viewer = { role: "coordination", entity_id: "cecopi-coordination" };
let projection = null;
let realtimeManager = null;
let realtimeHealth = HEALTH.OFFLINE;

function updateRealtimeBar(health) {
  realtimeHealth = health;
  if (typeof document === "undefined") return;
  const el = byId("v2-realtime-status");
  const bar = byId("v2-realtime-bar");
  const dot = bar?.querySelector("span[aria-hidden]");
  if (el) {
    el.textContent = health;
    el.dataset.health = health;
    const colors = {
      live: "var(--success, #0a0)",
      degraded: "var(--warning, #c79a00)",
      stale: "var(--critical, #e00)",
      offline: "var(--ink-muted)",
    };
    el.style.color = colors[health] || "var(--ink-muted)";
    if (dot) dot.style.background = colors[health] || "var(--ink-muted)";
  }
  if (bar) bar.style.display = snapshotCache ? "flex" : "none";
  // keep legacy header health in sync
  setText("v2-health", health);
}

function startRealtime(runId) {
  if (typeof document === "undefined") return;
  if (realtimeManager) {
    try { realtimeManager.stop(); } catch {}
    realtimeManager = null;
  }
  if (!runId) {
    updateRealtimeBar(HEALTH.OFFLINE);
    return;
  }
  // Resolve Supabase URL/key from meta/env if available (optional, polling fallback otherwise)
  let supabaseUrl = null;
  let supabaseAnonKey = null;
  try {
    supabaseUrl = (typeof window !== "undefined" && (window.SUPABASE_URL || window.__SUPABASE_URL)) || null;
    supabaseAnonKey = (typeof window !== "undefined" && (window.SUPABASE_ANON_KEY || window.__SUPABASE_ANON_KEY)) || null;
    // also try from localStorage injected by dashboard-v2.sh query? fallback to null → polling degraded
  } catch {}
  realtimeManager = createRealtimeManager({
    runId,
    fetchSnapshot: async () => {
      const snap = await fetchSnapshot(runId);
      return snap;
    },
    onSnapshot: (snap) => {
      snapshotCache = snap;
      projection = buildViewerProjection(snap, viewer);
      renderAll();
    },
    onHealthChange: (h) => updateRealtimeBar(h),
    onError: (err) => {
      if (err && (err.status === 404 || err.code === "run_not_found")) {
        updateRealtimeBar(HEALTH.OFFLINE);
      }
    },
    supabaseUrl,
    supabaseAnonKey,
    pollIntervalMs: 5000,
    staleThresholdMs: 30000,
    debounceMs: 250,
  });
  updateRealtimeBar(HEALTH.OFFLINE);
  realtimeManager.start().catch(() => updateRealtimeBar(realtimeManager.getHealth()));
}

function stopRealtime() {
  if (realtimeManager) {
    try { realtimeManager.stop(); } catch {}
    realtimeManager = null;
  }
  updateRealtimeBar(HEALTH.OFFLINE);
  const bar = typeof document !== "undefined" ? byId("v2-realtime-bar") : null;
  if (bar && !snapshotCache) bar.style.display = "none";
}

// Helpers safe for node tests (no window/document)
function getStorage(key) {
  try {
    if (typeof localStorage !== "undefined") return localStorage.getItem(key);
  } catch {}
  return null;
}
function setStorage(key, val) {
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(key, val);
  } catch {}
}

export function getViewer() {
  return { ...viewer };
}

export function getSwitcherEntities(snap) {
  const src = snap || snapshotCache;
  if (!src || !Array.isArray(src.entities)) return [];
  // Only operational entities: role != source
  return src.entities.filter((e) => e.role !== "source");
}

export function getCurrentRunId() {
  return currentRunId || getStorage(STORAGE_RUN);
}

function resolveCoordinationEntity(snap) {
  if (!snap || !Array.isArray(snap.entities)) return null;
  const coord = snap.entities.find((e) => e.role === "coordination");
  return coord || null;
}

export async function selectRun(runId) {
  if (!runId) throw new Error("run_id required");
  // Always enter as Coordination regardless of previous role (spec §6)
  currentRunId = runId;
  setStorage(STORAGE_RUN, runId);
  // fetch snapshot to resolve coordination entity
  const snap = await fetchSnapshot(runId);
  snapshotCache = snap;
  const coord = resolveCoordinationEntity(snap);
  if (coord) {
    viewer = { role: "coordination", entity_id: coord.entity_id };
  } else {
    // fallback: first operational or keep previous but force coordination role
    viewer = { role: "coordination", entity_id: viewer.entity_id };
  }
  setStorage(STORAGE_VIEWER, JSON.stringify(viewer));
  projection = buildViewerProjection(snap, viewer);
  if (typeof document !== "undefined") {
    renderAll();
    startRealtime(runId);
  }
  return { snapshot: snap, projection, viewer: { ...viewer } };
}

export function switchViewer(next) {
  if (!next || !next.entity_id || !next.role) throw new Error("viewer required");
  if (next.role === "source") throw new Error("source role not selectable");
  viewer = { role: next.role, entity_id: next.entity_id };
  setStorage(STORAGE_VIEWER, JSON.stringify(viewer));
  if (snapshotCache) {
    projection = buildViewerProjection(snapshotCache, viewer);
    if (typeof document !== "undefined") renderAll();
  }
  return { ...viewer };
}

// DOM rendering (guarded for node import)
function byId(id) {
  if (typeof document === "undefined") return null;
  return document.getElementById(id);
}

function setText(id, text) {
  const el = byId(id);
  if (el) el.textContent = text ?? "—";
}

function renderHeader(proj) {
  if (typeof document === "undefined") return;
  const snapshot = snapshotCache;
  // scenario identity + simulated time
  const run = snapshot?.run;
  setText("v2-run-name", run?.run_id ? `${run.run_id}` : "—");
  setText("v2-scenario-now", snapshot?.run?.scenario_now ? new Date(snapshot.run.scenario_now).toISOString() : run?.scenario_now || "—");
  setText("v2-viewer", `${viewer.role} · ${viewer.entity_id}`);
  // health ahora lo maneja realtime bar; mantenemos v2-health sincronizado
  if (realtimeManager) {
    setText("v2-health", realtimeManager.getHealth());
  } else {
    setText("v2-health", snapshot ? "degraded" : "offline");
  }
  // actualizar barra tiempo real debajo del header
  if (snapshot && realtimeManager) {
    updateRealtimeBar(realtimeManager.getHealth());
  } else if (snapshot) {
    updateRealtimeBar(HEALTH.DEGRADED);
    const bar = byId("v2-realtime-bar");
    if (bar) bar.style.display = "flex";
  } else {
    const bar = byId("v2-realtime-bar");
    if (bar) bar.style.display = "none";
  }
  // KPIs computed after filtering (spec §7.2)
  const k = proj?.kpis;
  if (k) {
    setText("kpi-zones", String(k.zoneCount ?? 0));
    setText("kpi-incidents", String(k.incidentCount ?? 0));
    setText("kpi-actions", String(k.actionCount ?? 0));
    setText("kpi-resources", String(k.resourceCount ?? 0));
    setText("kpi-contacts", String(k.contactCount ?? 0));
    // explicitly never show signals KPI
    const sigEl = byId("kpi-signals");
    if (sigEl) sigEl.style.display = "none";
  }
  // role switcher: entities where role != source
  const sel = byId("v2-role-switcher");
  if (sel && snapshot) {
    const ops = getSwitcherEntities(snapshot);
    const prev = sel.value;
    sel.innerHTML = "";
    for (const e of ops) {
      const opt = document.createElement("option");
      opt.value = e.entity_id;
      opt.textContent = `${e.name || e.entity_id} · ${e.role}`;
      opt.dataset.role = e.role;
      if (e.entity_id === viewer.entity_id) opt.selected = true;
      sel.appendChild(opt);
    }
    // ensure switcher reflects current viewer even if not in list (should not happen)
    if (!ops.some((e) => e.entity_id === viewer.entity_id) && viewer.entity_id) {
      const opt = document.createElement("option");
      opt.value = viewer.entity_id;
      opt.textContent = `${viewer.entity_id} · ${viewer.role}`;
      opt.selected = true;
      sel.appendChild(opt);
    }
  }
  // Run controls: only Coordination view renders pause/resume/abort (spec §10)
  let controlsEl = byId("v2-run-controls");
  const headerEl = byId("v2-run-name")?.closest("header") || document.querySelector("header");
  if (!controlsEl && headerEl) {
    controlsEl = document.createElement("div");
    controlsEl.id = "v2-run-controls";
    controlsEl.setAttribute("data-testid", "run-controls");
    controlsEl.style.cssText = "display:flex; gap:8px; align-items:center; margin-left:12px;";
    // insert after viewer/switcher row: append to header first row container
    const firstRow = headerEl.querySelector("div");
    if (firstRow) firstRow.appendChild(controlsEl);
    else headerEl.appendChild(controlsEl);
  }
  if (controlsEl) {
    const canControl = canRenderRunControls(viewer) && !!snapshot;
    if (!canControl) {
      controlsEl.style.display = "none";
      controlsEl.innerHTML = "";
    } else {
      controlsEl.style.display = "flex";
      const status = snapshot?.run?.status || "unknown";
      controlsEl.innerHTML = `
        <button data-testid="pause-btn" data-action="pause" style="padding:4px 10px; border-radius:6px; border:1px solid var(--line-strong); background:var(--surface-100); color:var(--ink); font-family:var(--font-mono); font-size:11px; cursor:pointer;" ${status==="paused" ? "disabled" : ""}>Pausar</button>
        <button data-testid="resume-btn" data-action="resume" style="padding:4px 10px; border-radius:6px; border:1px solid var(--line-strong); background:var(--surface-100); color:var(--ink); font-family:var(--font-mono); font-size:11px; cursor:pointer;" ${status==="running" ? "disabled" : status==="ready" || status==="paused" ? "" : "disabled"}>Reanudar</button>
        <button data-testid="abort-btn" data-action="abort" style="padding:4px 10px; border-radius:6px; border:1px solid var(--critical, #e00); background:var(--surface-100); color:var(--critical, #e00); font-family:var(--font-mono); font-size:11px; cursor:pointer;">Abortar</button>
        <span data-testid="run-control-feedback" style="font-family:var(--font-mono); font-size:11px; color:var(--ink-muted); margin-left:4px;"></span>
      `;
      // attach once
      if (!controlsEl.dataset.bound) {
        controlsEl.dataset.bound = "1";
        controlsEl.addEventListener("click", async (e) => {
          const btn = e.target.closest("button[data-action]");
          if (!btn) return;
          const action = btn.dataset.action;
          const feedback = controlsEl.querySelector('[data-testid="run-control-feedback"]');
          const setFeedback = (msg, isError) => { if (feedback) { feedback.textContent = msg; feedback.style.color = isError ? "var(--critical, #e00)" : "var(--ink-muted)"; } };
          // disable all during request
          const allBtns = controlsEl.querySelectorAll("button");
          allBtns.forEach((b) => (b.disabled = true));
          setFeedback("enviando…", false);
          try {
            let res;
            if (action === "pause") res = await pauseRun(snapshotCache);
            else if (action === "resume") res = await resumeRun(snapshotCache);
            else if (action === "abort") res = await abortRun(snapshotCache);
            setFeedback("ok", false);
            await refreshSnapshot("run-control");
          } catch (err) {
            if (isVersionConflictError(err)) {
              setFeedback(getVersionConflictMessage(), true);
              await refreshSnapshot("version_conflict");
            } else {
              setFeedback(formatCommandError(err), true);
            }
          } finally {
            // re-enable via rerender; renderHeader will rebuild buttons
            setTimeout(() => renderHeader(projection), 300);
          }
        });
      }
    }
  }
}

async function refreshSnapshot(reason = "manual") {
  if (!currentRunId) return null;
  // si realtime manager está activo, usa su refreshNow para mantener health coherente
  if (realtimeManager && typeof realtimeManager.refreshNow === "function") {
    try {
      const snap = await realtimeManager.refreshNow(reason);
      snapshotCache = snap;
      projection = buildViewerProjection(snap, viewer);
      if (typeof document !== "undefined") renderAll();
      return snap;
    } catch {
      // fallback a fetch directo
    }
  }
  const snap = await fetchSnapshot(currentRunId);
  snapshotCache = snap;
  projection = buildViewerProjection(snap, viewer);
  if (typeof document !== "undefined") renderAll();
  return snap;
}

function renderScreens(proj) {
  if (typeof document === "undefined") return;
  const zonesEl = byId("v2-zones");
  if (zonesEl) zonesEl.innerHTML = renderZones(proj?.zones || []);
  const incEl = byId("v2-incidents");
  if (incEl) incEl.innerHTML = renderIncidents(proj?.incidents || []);
  const actEl = byId("v2-actions");
  if (actEl) {
    actEl.innerHTML = renderActions(proj?.actions || [], viewer);
    // attach approve/reject delegation once
    if (!actEl.dataset.bound) {
      actEl.dataset.bound = "1";
      actEl.addEventListener("click", async (e) => {
        const btn = e.target.closest("button[data-decide]");
        if (!btn) return;
        const actionId = btn.dataset.actionId || btn.getAttribute("data-action-id");
        const decide = btn.dataset.decide;
        if (!actionId || !decide) return;
        const feedback = actEl.querySelector(`[data-testid="action-decision-feedback"][data-action-id="${actionId}"]`) || btn.parentElement?.querySelector('[data-testid="action-decision-feedback"]');
        const setFeedback = (msg, isError) => { if (feedback) { feedback.textContent = msg; feedback.style.color = isError ? "var(--critical, #e00)" : "var(--ink-muted)"; } };
        const allBtns = actEl.querySelectorAll(`button[data-action-id="${actionId}"]`);
        allBtns.forEach((b) => (b.disabled = true));
        setFeedback("enviando…", false);
        try {
          if (decide === "approve") await approveAction(snapshotCache, actionId, viewer.entity_id);
          else await rejectAction(snapshotCache, actionId, viewer.entity_id);
          setFeedback("ok", false);
          await refreshSnapshot(decide);
        } catch (err) {
          if (isVersionConflictError(err)) {
            setFeedback(getVersionConflictMessage(), true);
            try { await refreshSnapshot("version_conflict"); } catch {}
          } else {
            setFeedback(formatCommandError(err), true);
          }
        } finally {
          // re-enable via rerender
          setTimeout(() => { if (projection) renderScreens(projection); }, 400);
        }
      });
    }
  }
  const resEl = byId("v2-resources");
  if (resEl) resEl.innerHTML = renderResources(proj?.resources || []);
  const contEl = byId("v2-contacts");
  if (contEl) contEl.innerHTML = renderContacts(proj?.contacts || []);
  const planEl = byId("v2-plan");
  if (planEl) {
    const plan = proj?.plan || snapshotCache?.plan;
    if (!plan) planEl.innerHTML = `<div data-testid="empty-plan" style="padding:16px; color:var(--ink-muted);">Sin plan activo.</div>`;
    else planEl.innerHTML = `<div data-testid="plan-item" style="padding:12px; border:1px solid var(--line); border-radius:8px;"><div style="font-weight:600;">${plan.plan_id || "Plan"}</div><div style="font-size:12px; color:var(--ink-muted);">estado ${plan.status || "—"} · acciones ${(plan.action_ids||[]).join(", ")}</div></div>`;
  }
  // update counters in headers
  setText("v2-zones-count", String(proj?.zones?.length ?? 0));
  setText("v2-incidents-count", String(proj?.incidents?.length ?? 0));
  setText("v2-actions-count", String(proj?.actions?.length ?? 0));
  setText("v2-resources-count", String(proj?.resources?.length ?? 0));
  setText("v2-contacts-count", String(proj?.contacts?.length ?? 0));
}

function renderAll() {
  if (!projection) return;
  renderHeader(projection);
  renderScreens(projection);
}

async function renderListScreen() {
  if (typeof document === "undefined") return;
  const contentEl = byId("v2-content");
  const statusEl = byId("v2-status");
  if (statusEl) statusEl.textContent = "cargando escenarios…";
  try {
    const runs = await fetchRuns();
    if (statusEl) statusEl.textContent = `v2 · ${runs.length} escenarios`;
    if (contentEl) {
      contentEl.innerHTML = `<div style="flex:1; display:flex; flex-direction:column; min-width:0;">${renderList(runs, selectRun)}</div>`;
      attachListHandlers(contentEl, async (runId) => {
        try {
          await selectRun(runId);
          // after select, hide list and show dashboard panels
          const listWrap = byId("v2-list-screen");
          if (listWrap) listWrap.style.display = "none";
          const dash = byId("v2-dashboard");
          if (dash) dash.style.display = "flex";
          if (statusEl) statusEl.textContent = `v2 · ${runId} · ${viewer.role}`;
        } catch (e) {
          if (statusEl) statusEl.textContent = `error: ${e.message}`;
        }
      });
      // Also wire fallback click via delegation if attachListHandlers not catching due to innerHTML structure
      contentEl.onclick = async (e) => {
        const a = e.target.closest?.("a[data-run-id]");
        if (a) {
          e.preventDefault();
          const rid = a.getAttribute("data-run-id");
          try {
            await selectRun(rid);
            const listWrap = byId("v2-list-screen");
            if (listWrap) listWrap.style.display = "none";
            const dash = byId("v2-dashboard");
            if (dash) dash.style.display = "flex";
            if (statusEl) statusEl.textContent = `v2 · ${rid} · ${viewer.role}`;
          } catch (err) {
            if (statusEl) statusEl.textContent = `error: ${err.message}`;
          }
        }
      };
    }
    // If we already have a selected run (from storage), auto-enter as coordination
    const storedRun = getStorage(STORAGE_RUN);
    if (storedRun && runs.some((r) => r.run_id === storedRun)) {
      // don't auto-switch during initial list render if user hasn't clicked? But spec says selecting run stores run_id and enters as coordination.
      // For session restore, also enter dashboard directly.
      if (currentRunId === null) {
        // show dashboard directly
        try {
          await selectRun(storedRun);
          const listWrap = byId("v2-list-screen");
          if (listWrap) listWrap.style.display = "none";
          const dash = byId("v2-dashboard");
          if (dash) dash.style.display = "flex";
        } catch {}
      }
    }
  } catch (e) {
    if (contentEl) contentEl.innerHTML = `<div role="alert" style="padding:24px; color:var(--critical);">Error cargando escenarios: ${e.message}</div>`;
    if (statusEl) statusEl.textContent = "offline · sin escenarios";
  }
}

function installSwitcher() {
  if (typeof document === "undefined") return;
  const sel = byId("v2-role-switcher");
  if (sel && !sel.dataset.bound) {
    sel.dataset.bound = "1";
    sel.addEventListener("change", () => {
      const entityId = sel.value;
      const opt = sel.options[sel.selectedIndex];
      const role = opt?.dataset?.role || "authority";
      switchViewer({ role, entity_id: entityId });
      const statusEl = byId("v2-status");
      if (statusEl && currentRunId) statusEl.textContent = `v2 · ${currentRunId} · ${role}`;
    });
  }
  const backBtn = byId("v2-back-to-list");
  if (backBtn && !backBtn.dataset.bound) {
    backBtn.dataset.bound = "1";
    backBtn.addEventListener("click", (e) => {
      e.preventDefault();
      stopRealtime();
      currentRunId = null;
      snapshotCache = null;
      projection = null;
      try { localStorage.removeItem(STORAGE_RUN); } catch {}
      const listWrap = byId("v2-list-screen");
      const dash = byId("v2-dashboard");
      if (listWrap) listWrap.style.display = "flex";
      if (dash) dash.style.display = "none";
      const bar = byId("v2-realtime-bar");
      if (bar) bar.style.display = "none";
      setText("v2-health", "offline");
      setText("v2-run-name", "—");
      setText("v2-scenario-now", "—");
      renderListScreen();
    });
  }
}

async function init() {
  if (typeof document === "undefined") return;
  const statusEl = byId("v2-status");
  if (statusEl) statusEl.textContent = "v2 shell · tokens ok";
  const contentEl = byId("v2-content");
  if (contentEl) contentEl.setAttribute("data-v2-ready", "true");

  // Restore viewer from storage if available
  try {
    const storedViewer = getStorage(STORAGE_VIEWER);
    if (storedViewer) {
      const parsed = JSON.parse(storedViewer);
      if (parsed?.role && parsed?.entity_id) viewer = parsed;
    }
    const storedRun = getStorage(STORAGE_RUN);
    if (storedRun) currentRunId = storedRun;
  } catch {}

  // Quick token check mirrors earlier shell
  try {
    const styles = getComputedStyle(document.documentElement);
    const surface = styles.getPropertyValue("--surface-000").trim();
    if (surface && statusEl) statusEl.textContent = `v2 shell · tokens ${surface.slice(0, 7)} · cargando…`;
  } catch {}

  // Prepare containers
  installSwitcher();

  // Wire initial view: if run selected show dashboard else list
  // Our index.html has both list screen and dashboard containers; we handle visibility
  const dash = byId("v2-dashboard");
  const listWrap = byId("v2-list-screen");
  if (currentRunId) {
    // try to fetch snapshot immediately and show dashboard
    try {
      await selectRun(currentRunId);
      if (listWrap) listWrap.style.display = "none";
      if (dash) dash.style.display = "flex";
    } catch {
      // fallback to list
      if (dash) dash.style.display = "none";
      if (listWrap) listWrap.style.display = "flex";
      await renderListScreen();
    }
  } else {
    if (dash) dash.style.display = "none";
    if (listWrap) listWrap.style.display = "flex";
    await renderListScreen();
  }

  // Also support view via URL param ?run_id= for deep linking (optional)
  try {
    const params = new URLSearchParams(window.location.search);
    const urlRun = params.get("run_id");
    if (urlRun && urlRun !== currentRunId) {
      await selectRun(urlRun);
      if (listWrap) listWrap.style.display = "none";
      if (dash) dash.style.display = "flex";
    }
  } catch {}
}

// Only auto-init in browser environment with DOM ready
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => init());
  } else {
    init();
  }
  if (import.meta.hot) import.meta.hot.accept();
}
