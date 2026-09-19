const state = {
  config: null,
  snapshot: null,
  realtime: null,
  realtimeClient: null,
  pollTimer: null,
  refreshTimer: null,
  healthTimer: null,
  recoveryNoticeTimer: null,
  snapshotPromise: null,
  refreshWaiters: [],
  inFlight: new Set(),
  lastSuccessfulSync: 0,
  consecutiveFailures: 0,
  realtimeSubscribed: false
};

const COLLECTION_KEYS = [
  "signals",
  "incidents",
  "actions",
  "outcomes",
  "resources",
  "events",
  "outbox"
];

const timeFormatter = new Intl.DateTimeFormat("es-ES", {
  dateStyle: "short",
  timeStyle: "medium",
  timeZone: "UTC"
});

function byId(id) {
  return document.getElementById(id);
}

function normalizeUrl(value, name) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${name} no es una URL válida.`);
  }

  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error(`${name} debe usar http o https.`);
  }

  return parsed.href.replace(/\/$/, "");
}

function gatewayApiUrl(path) {
  const cleanPath = String(path).replace(/^\/+/, "");
  const url = new URL(state.config.gatewayUrl);
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/${cleanPath}`;
  url.hash = "";
  return url;
}

function readConfig() {
  const params = new URLSearchParams(location.search);
  const runId = params.get("run_id")?.trim();
  if (!runId) {
    throw new Error("Falta el parámetro requerido run_id para abrir la simulación.");
  }

  // The dashboard may run locally while the Gateway uses a stable public Edge URL.
  // gateway_url is an explicit override; same-origin remains useful for other hosts.
  const gatewayUrl = normalizeUrl(
    params.get("gateway_url")?.trim() || location.origin,
    "gateway_url"
  );
  const supabaseUrlValue = params.get("supabase_url")?.trim();
  const supabaseAnonKey = params.get("supabase_anon_key")?.trim();

  const result = {
    runId,
    gatewayUrl,
    supabaseUrl: supabaseUrlValue
      ? normalizeUrl(supabaseUrlValue, "supabase_url")
      : null,
    supabaseAnonKey: supabaseUrlValue && supabaseAnonKey ? supabaseAnonKey : null,
    realtimeEnabled: Boolean(supabaseUrlValue && supabaseAnonKey)
  };

  // Limpia anon_key de la URL para evitar leak en history/Referer/screenshots
  if (supabaseUrlValue || supabaseAnonKey) {
    try {
      const cleanUrl = new URL(location.href);
      cleanUrl.searchParams.delete("supabase_url");
      cleanUrl.searchParams.delete("supabase_anon_key");
      history.replaceState(null, "", cleanUrl.toString());
    } catch {
      // noop: si falla el replace, la app sigue funcionando con polling
    }
  }

  return result;
}

function responseError(status, body) {
  const code = typeof body?.error === "string" ? body.error : "gateway_error";
  const detail = typeof body?.message === "string" ? ` · ${body.message}` : "";
  return new Error(`Gateway ${status}: ${code}${detail}`);
}

function validateSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
    throw new Error("Snapshot inválido: la respuesta no es un objeto.");
  }

  const run = snapshot.run;
  if (!run || typeof run !== "object" || Array.isArray(run)) {
    throw new Error("Snapshot inválido: falta run.");
  }

  for (const field of ["run_id", "pack_id", "pack_version", "pack_digest"]) {
    if (typeof run[field] !== "string" || !run[field]) {
      throw new Error(`Snapshot inválido: falta run.${field}.`);
    }
  }

  if (!Number.isSafeInteger(run.state_version) || run.state_version < 0) {
    throw new Error("Snapshot inválido: run.state_version no es válido.");
  }

  if (run.run_id !== state.config.runId) {
    throw new Error("Snapshot inválido: el run_id recibido no coincide con el solicitado.");
  }

  for (const key of COLLECTION_KEYS) {
    snapshot[key] = Array.isArray(snapshot[key]) ? snapshot[key] : [];
  }

  return snapshot;
}

async function fetchSnapshot() {
  if (state.snapshotPromise) {
    return state.snapshotPromise;
  }

  state.snapshotPromise = (async () => {
    const url = gatewayApiUrl("api/snapshot");
    url.searchParams.set("run_id", state.config.runId);
    const response = await fetch(url, { headers: { Accept: "application/json" } });

    let body;
    try {
      body = await response.json();
    } catch {
      throw new Error(`Gateway ${response.status}: la respuesta no es JSON válido.`);
    }

    if (!response.ok) {
      throw responseError(response.status, body);
    }

    return validateSnapshot(body);
  })();

  try {
    return await state.snapshotPromise;
  } finally {
    state.snapshotPromise = null;
  }
}

function showBanner(message, kind = "error") {
  const banner = byId("error-banner");
  banner.textContent = message;
  banner.dataset.kind = kind;
  banner.hidden = false;
}

function hideBanner() {
  const banner = byId("error-banner");
  banner.hidden = true;
  banner.textContent = "";
  delete banner.dataset.kind;
}

function announceRecovery() {
  clearTimeout(state.recoveryNoticeTimer);
  showBanner("Conexión recuperada. Snapshot de la simulación actualizado.", "notice");
  state.recoveryNoticeTimer = window.setTimeout(() => {
    if (byId("error-banner").dataset.kind === "notice") {
      hideBanner();
    }
  }, 4000);
}

async function refreshSnapshot(reason) {
  const failuresBeforeRequest = state.consecutiveFailures;

  try {
    const nextSnapshot = await fetchSnapshot();
    state.lastSuccessfulSync = Date.now();
    state.consecutiveFailures = 0;

    const currentVersion = state.snapshot?.run?.state_version;
    const nextVersion = nextSnapshot.run.state_version;
    // Outbox dispatch can change after the domain transaction without increasing
    // state_version, so equal-version snapshots remain authoritative and renderable.
    if (currentVersion === undefined || nextVersion >= currentVersion) {
      state.snapshot = nextSnapshot;
      render();
    }

    if (failuresBeforeRequest > 0) {
      announceRecovery();
    }

    updateHealth();
    return state.snapshot;
  } catch (error) {
    state.consecutiveFailures += 1;
    showBanner(`No se pudo actualizar la simulación (${reason}): ${error.message}`);
    updateHealth();
    throw error;
  }
}

function scheduleRefresh(reason) {
  const result = new Promise((resolve, reject) => {
    state.refreshWaiters.push({ resolve, reject });
  });

  if (state.refreshTimer === null) {
    state.refreshTimer = window.setTimeout(async () => {
      state.refreshTimer = null;
      const waiters = state.refreshWaiters.splice(0);
      try {
        const snapshot = await refreshSnapshot(reason);
        for (const waiter of waiters) waiter.resolve(snapshot);
      } catch (error) {
        for (const waiter of waiters) waiter.reject(error);
      }
    }, 250);
  }

  return result;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function appendText(node, tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text ?? "—";
  if (className) element.className = className;
  node.append(element);
  return element;
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : `${timeFormatter.format(date)} UTC`;
}

function formatEvidence(evidence) {
  if (!Array.isArray(evidence) || evidence.length === 0) return "Sin evidencia";
  return evidence.map((item) => {
    if (item?.kind === "signal" || item?.signal_id) {
      return `${item.signal_id ?? "signal"}@${item.revision ?? "?"}`;
    }
    if (item?.kind === "incident" || item?.incident_id) {
      return String(item.incident_id ?? "incident");
    }
    return String(item?.kind ?? "evidencia");
  }).join(", ");
}

function isBlockedField(key) {
  return ["hidden_truth", "service_role", "service_role_key", "supabase_anon_key"]
    .includes(String(key).toLowerCase());
}

function formatObject(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, (key, nestedValue) => (
      isBlockedField(key) ? undefined : nestedValue
    ));
  } catch {
    return String(value);
  }
}

function formatList(value) {
  if (!Array.isArray(value) || value.length === 0) return "—";
  return value.map((item) => (
    typeof item === "object" ? formatObject(item) : String(item)
  )).join(", ");
}

function renderEmpty(container, message) {
  clear(container);
  const empty = byId("empty-template").content.firstElementChild.cloneNode(true);
  empty.textContent = message;
  container.append(empty);
}

function cloneRecord(templateId = "record-template") {
  return byId(templateId).content.firstElementChild.cloneNode(true);
}

function setCount(id, value) {
  byId(id).textContent = String(value);
}

function addBadge(container, text, tone) {
  const badge = appendText(container, "span", String(text), "badge");
  if (tone) badge.dataset.tone = tone;
  return badge;
}

function badgeTone(value) {
  if (["P0", "failed", "rejected", "aborted", "invalidated"].includes(value)) {
    return "urgent";
  }
  if (["P1", "pending_approval", "partial", "needs_reassessment"].includes(value)) {
    return "warning";
  }
  if (["active", "approved", "completed", "success", "delivered"].includes(value)) {
    return "positive";
  }
  return null;
}

function addField(fields, label, value, className) {
  const row = document.createElement("div");
  appendText(row, "dt", label);
  appendText(row, "dd", value ?? "—", className);
  fields.append(row);
}

function addBodyLine(body, label, value, className = "") {
  const line = document.createElement("p");
  line.className = `labelled-text ${className}`.trim();
  appendText(line, "strong", `${label}: `);
  line.append(document.createTextNode(value ?? "—"));
  body.append(line);
}

function setRecordTitle(record, title) {
  record.querySelector("[data-title]").textContent = title;
}

function renderRun() {
  const run = state.snapshot.run;
  const summary = byId("run-summary");
  clear(summary);
  addField(summary, "Pack", `${run.pack_id} · ${run.pack_version}`);
  addField(summary, "Run ID", run.run_id, "technical");
  addField(summary, "Estado", run.status ?? "—");
  addField(summary, "Reloj de escenario", formatTime(run.scenario_now));
  addField(summary, "State version", run.state_version);
  updateRunControls();
}

function renderSignals() {
  const container = byId("signals-list");
  const signals = [...state.snapshot.signals].sort((left, right) => (
    Date.parse(right.scenario_at ?? 0) - Date.parse(left.scenario_at ?? 0)
  ));
  setCount("signals-count", signals.length);
  clear(container);
  if (signals.length === 0) {
    renderEmpty(container, "Sin signals observables.");
    return;
  }

  for (const signal of signals) {
    const record = cloneRecord();
    setRecordTitle(record, `${signal.signal_id ?? "Signal"} · revisión ${signal.revision ?? "—"}`);
    const badges = record.querySelector("[data-badges]");
    for (const value of [signal.status, signal.modality, signal.signal_confidence]) {
      if (value) addBadge(badges, value, badgeTone(value));
    }
    const fields = record.querySelector("[data-fields]");
    addField(fields, "Revisión", signal.revision);
    addField(fields, "Modalidad", signal.modality);
    addField(
      fields,
      "Ubicación",
      `${signal.location?.zone_id ?? "sin zona"} · ${signal.location?.precision ?? "precisión desconocida"}`
    );
    addField(fields, "Confianza", signal.signal_confidence);
    addField(fields, "Escenario", formatTime(signal.scenario_at));
    const body = record.querySelector("[data-body]");
    addBodyLine(body, "Contenido", signal.content);
    addBodyLine(body, "Claims", formatList(signal.claims));
    addBodyLine(body, "Origen", signal.source?.independence_status ?? "—");
    container.append(record);
  }
}

function renderIncidents() {
  const container = byId("incidents-list");
  const incidents = state.snapshot.incidents;
  setCount("incidents-count", incidents.length);
  clear(container);
  if (incidents.length === 0) {
    renderEmpty(container, "Sin incidents canónicos.");
    return;
  }

  for (const incident of incidents) {
    const record = cloneRecord();
    record.dataset.priority = incident.priority ?? "";
    setRecordTitle(record, incident.incident_id ?? "Incident");
    const badges = record.querySelector("[data-badges]");
    for (const value of [incident.priority, incident.state, incident.confidence]) {
      if (value) addBadge(badges, value, badgeTone(value));
    }
    const fields = record.querySelector("[data-fields]");
    addField(fields, "Estado canónico", incident.state);
    addField(fields, "Prioridad", incident.priority);
    addField(fields, "Confianza", incident.confidence);
    addField(fields, "Revisar", formatTime(incident.revisit_at));
    const body = record.querySelector("[data-body]");
    addBodyLine(body, "Riesgos", formatList(incident.hazard_types));
    addBodyLine(body, "Zonas", formatList(incident.zone_ids));
    addBodyLine(body, "Evidencia", formatEvidence(incident.evidence), "technical");
    container.append(record);
  }
}

function renderPlan() {
  const container = byId("plan-panel");
  const plan = state.snapshot.plan;
  setCount("plan-count", plan ? 1 : 0);
  clear(container);
  if (!plan) {
    renderEmpty(container, "Sin plan activo.");
    return;
  }

  const record = cloneRecord();
  record.removeAttribute("role");
  setRecordTitle(record, plan.plan_id ?? "Plan activo");
  const badges = record.querySelector("[data-badges]");
  if (plan.status) addBadge(badges, plan.status, badgeTone(plan.status));
  addBadge(badges, `v${plan.plan_version ?? "—"}`);
  const fields = record.querySelector("[data-fields]");
  addField(fields, "Plan ID", plan.plan_id, "technical");
  addField(fields, "Versión", plan.plan_version);
  addField(fields, "Estado", plan.status);
  const body = record.querySelector("[data-body]");
  addBodyLine(body, "Objetivos", formatList(plan.objectives));
  addBodyLine(body, "Incidents", formatList(plan.incident_ids), "technical");
  addBodyLine(body, "Actions", formatList(plan.action_ids), "technical");
  addBodyLine(body, "Evidencia", formatEvidence(plan.evidence), "technical");
  container.append(record);
}

function renderActions() {
  const container = byId("actions-list");
  const actions = state.snapshot.actions;
  setCount("actions-count", actions.length);
  clear(container);
  if (actions.length === 0) {
    renderEmpty(container, "Sin actions observables.");
    return;
  }

  for (const action of actions) {
    const record = cloneRecord("action-template");
    record.dataset.priority = action.priority ?? "";
    setRecordTitle(record, action.action_id ?? "Action");
    const badges = record.querySelector("[data-badges]");
    for (const value of [action.priority, action.status, action.risk]) {
      if (value) addBadge(badges, value, badgeTone(value));
    }
    const fields = record.querySelector("[data-fields]");
    addField(fields, "Primitiva", action.primitive);
    addField(fields, "Estado", action.status);
    addField(fields, "Policy", action.approval_policy);
    addField(fields, "Actor", action.actor_id, "technical");
    addField(fields, "Reserva", action.reservation_id ?? "Sin reserva", "technical");
    addField(fields, "Evidencia", action.evidence_status);
    const body = record.querySelector("[data-body]");
    addBodyLine(body, "Razonamiento", action.reasoning);
    addBodyLine(body, "Target", formatObject(action.target), "technical");
    addBodyLine(body, "Params", formatObject(action.params), "technical");
    addBodyLine(body, "Evidencia", formatEvidence(action.evidence), "technical");

    if (action.status === "pending_approval") {
      const controls = record.querySelector("[data-action-controls]");
      controls.hidden = false;
      for (const [decision, label] of [["approve", "Aprobar"], ["reject", "Rechazar"]]) {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.actionId = action.action_id;
        button.dataset.decision = decision;
        button.textContent = label;
        button.setAttribute("aria-label", `${label} ${action.action_id} · SIMULACIÓN`);
        button.disabled = state.inFlight.has(
          `${decision === "approve" ? "approve_action" : "reject_action"}:${action.action_id}`
        );
        controls.append(button);
      }
    }
    container.append(record);
  }
}

function renderOutcomes() {
  const container = byId("outcomes-list");
  const outcomes = state.snapshot.outcomes;
  setCount("outcomes-count", outcomes.length);
  clear(container);
  if (outcomes.length === 0) {
    renderEmpty(container, "Sin outcomes registrados.");
    return;
  }

  for (const outcome of outcomes) {
    const record = cloneRecord();
    setRecordTitle(record, outcome.outcome_id ?? "Outcome");
    const badges = record.querySelector("[data-badges]");
    if (outcome.status) addBadge(badges, outcome.status, badgeTone(outcome.status));
    const fields = record.querySelector("[data-fields]");
    addField(fields, "Action", outcome.action_id, "technical");
    addField(fields, "Intento", outcome.attempt_id, "technical");
    addField(fields, "Resultado", outcome.status);
    addField(fields, "Escenario", formatTime(outcome.scenario_at));
    const body = record.querySelector("[data-body]");
    addBodyLine(body, "Resumen", outcome.summary);
    addBodyLine(body, "Efectos observados", formatObject(outcome.observed_effects), "technical");
    addBodyLine(body, "Evidencia", formatEvidence(outcome.evidence), "technical");
    container.append(record);
  }
}

function renderResources() {
  const container = byId("resources-list");
  const resources = state.snapshot.resources;
  setCount("resources-count", resources.length);
  clear(container);
  if (resources.length === 0) {
    renderEmpty(container, "Sin recursos observables.");
    return;
  }

  for (const resource of resources) {
    const record = cloneRecord();
    setRecordTitle(record, resource.resource_id ?? resource.name ?? "Recurso");
    const badges = record.querySelector("[data-badges]");
    if (resource.resource_mode) addBadge(badges, resource.resource_mode);
    const fields = record.querySelector("[data-fields]");
    for (const [key, value] of Object.entries(resource)) {
      if (key === "resource_id" || isBlockedField(key)) continue;
      addField(
        fields,
        key.replaceAll("_", " "),
        Array.isArray(value) ? formatList(value) : formatObject(value),
        typeof value === "object" && value !== null ? "technical" : ""
      );
    }
    container.append(record);
  }
}

function eventSequence(event, index) {
  return event.sequence ?? event.event_id ?? event.state_version ?? index;
}

function compareSequence(left, right) {
  const leftNumber = Number(left.sequence);
  const rightNumber = Number(right.sequence);
  if (Number.isFinite(leftNumber) && Number.isFinite(rightNumber) && leftNumber !== rightNumber) {
    return leftNumber - rightNumber;
  }
  const sequenceOrder = String(left.sequence).localeCompare(String(right.sequence), undefined, {
    numeric: true
  });
  if (sequenceOrder !== 0) return sequenceOrder;
  return Date.parse(left.timestamp ?? 0) - Date.parse(right.timestamp ?? 0);
}

function eventAggregateId(event) {
  const payload = event.payload ?? {};
  return event.aggregate_id
    ?? payload.aggregate_id
    ?? payload.signal_id
    ?? payload.incident_id
    ?? payload.plan_id
    ?? payload.action_id
    ?? payload.outcome_id
    ?? "—";
}

function eventSummary(event) {
  const payload = event.payload;
  if (!payload || typeof payload !== "object") return "Evento persistido";
  return payload.summary
    ?? payload.message
    ?? payload.reasoning
    ?? payload.status
    ?? formatObject(payload);
}

function buildTimeline(snapshot) {
  if (snapshot.events.length > 0) {
    const outboxByEvent = new Map();
    for (const item of snapshot.outbox) {
      for (const key of [item.event_id, item.causation_id]) {
        if (key !== null && key !== undefined) outboxByEvent.set(String(key), item);
      }
    }

    return snapshot.events.map((event, index) => {
      const relatedOutbox = outboxByEvent.get(String(event.event_id))
        ?? outboxByEvent.get(String(event.causation_id));
      return {
        kind: "Event",
        id: event.event_id ?? `event-${index + 1}`,
        sequence: eventSequence(event, index),
        type: event.event_type ?? event.type ?? "event",
        timestamp: event.scenario_at
          ?? event.created_at
          ?? event.payload?.scenario_at
          ?? event.payload?.received_at,
        aggregateId: eventAggregateId(event),
        summary: eventSummary(event),
        dispatchStatus: relatedOutbox?.status ?? null
      };
    }).sort(compareSequence);
  }

  const entries = [];
  for (const signal of snapshot.signals) {
    entries.push({
      kind: "Signal",
      id: `${signal.signal_id}@${signal.revision}`,
      type: "signal",
      timestamp: signal.scenario_at,
      receivedAt: signal.received_at,
      summary: signal.content ?? signal.status ?? "Signal observable"
    });
  }
  for (const action of snapshot.actions) {
    entries.push({
      kind: "Action",
      id: action.action_id,
      type: action.primitive ?? "action",
      timestamp: action.scenario_at,
      receivedAt: action.received_at,
      summary: `${action.status ?? "sin estado"} · ${action.reasoning ?? "sin resumen"}`
    });
  }
  for (const outcome of snapshot.outcomes) {
    entries.push({
      kind: "Outcome",
      id: outcome.outcome_id,
      type: outcome.status ?? "outcome",
      timestamp: outcome.scenario_at,
      receivedAt: outcome.received_at,
      summary: outcome.summary ?? "Outcome observable"
    });
  }

  return entries.sort((left, right) => {
    const scenarioOrder = Date.parse(left.timestamp ?? 0) - Date.parse(right.timestamp ?? 0);
    if (scenarioOrder !== 0) return scenarioOrder;
    return Date.parse(left.receivedAt ?? 0) - Date.parse(right.receivedAt ?? 0);
  });
}

function renderTimeline() {
  const container = byId("timeline-list");
  const timeline = buildTimeline(state.snapshot);
  const visible = timeline.length > 100 ? timeline.slice(-100) : timeline;
  setCount("timeline-count", timeline.length);
  byId("timeline-note").textContent = timeline.length > 100
    ? `Mostrando 100 de ${timeline.length} entradas, en orden persistido.`
    : "Orden autoritativo persistido.";
  clear(container);
  if (visible.length === 0) {
    renderEmpty(container, "Sin eventos, signals, actions ni outcomes en el timeline.");
    return;
  }

  for (const entry of visible) {
    const record = cloneRecord();
    setRecordTitle(record, `${entry.kind} · ${entry.id ?? "—"}`);
    const badges = record.querySelector("[data-badges]");
    addBadge(badges, entry.type, badgeTone(entry.type));
    if (entry.dispatchStatus) addBadge(badges, `dispatch: ${entry.dispatchStatus}`, badgeTone(entry.dispatchStatus));
    const fields = record.querySelector("[data-fields]");
    if (entry.sequence !== undefined) addField(fields, "Secuencia", entry.sequence);
    if (entry.aggregateId !== undefined) addField(fields, "Agregado", entry.aggregateId, "technical");
    addField(fields, "Tiempo persistido", formatTime(entry.timestamp));
    const body = record.querySelector("[data-body]");
    addBodyLine(body, "Resumen", entry.summary);
    container.append(record);
  }
}

function render() {
  if (!state.snapshot) return;

  const focused = document.activeElement;
  const actionFocus = focused?.dataset?.actionId
    ? { actionId: focused.dataset.actionId, decision: focused.dataset.decision }
    : null;

  renderRun();
  renderSignals();
  renderIncidents();
  renderPlan();
  renderActions();
  renderOutcomes();
  renderResources();
  renderTimeline();

  if (actionFocus) {
    const replacement = [...document.querySelectorAll("button[data-action-id]")].find((button) => (
      button.dataset.actionId === actionFocus.actionId
      && button.dataset.decision === actionFocus.decision
    ));
    replacement?.focus();
  }
}

function updateRunControls() {
  const status = state.snapshot?.run?.status;
  for (const button of byId("run-controls").querySelectorAll("button[data-command]")) {
    const enabled = (
      (button.dataset.command === "pause_run" && status === "running")
      || (button.dataset.command === "resume_run" && status === "paused")
      || (button.dataset.command === "abort_run" && ["ready", "running", "paused"].includes(status))
    );
    button.disabled = !enabled || state.inFlight.has(button.dataset.command);
  }
}

function updateHealth() {
  const connection = byId("connection-status");
  const age = state.lastSuccessfulSync ? Date.now() - state.lastSuccessfulSync : Infinity;
  let health = "offline";
  let text = "offline · sin snapshot correcto";

  if (age <= 10_000 && state.realtimeSubscribed) {
    health = "live";
    text = "live · Realtime y snapshot al día";
  } else if (age <= 10_000) {
    health = "degraded";
    text = "degraded · polling activo";
  } else if (age <= 30_000) {
    health = "stale";
    text = `stale · último snapshot hace ${Math.floor(age / 1000)} s`;
  } else if (state.consecutiveFailures > 0 || !state.lastSuccessfulSync) {
    health = "offline";
    text = "offline · sin snapshot reciente";
  } else {
    health = "stale";
    text = `stale · último snapshot hace ${Math.floor(age / 1000)} s`;
  }

  connection.dataset.state = health;
  connection.textContent = text;
}

async function startRealtime() {
  if (!state.config.realtimeEnabled) return;

  try {
    // Producción: vendorizar supabase-js en /vendor para SRI local (pin 2.45.4, no floating @2)
    // dynamic import no soporta integrity nativo; alternativa es <script type="importmap"> con hash
    const { createClient } = await import(
      "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm"
    );
    state.realtimeClient = createClient(
      state.config.supabaseUrl,
      state.config.supabaseAnonKey,
      {
        auth: {
          persistSession: false,
          autoRefreshToken: false,
          detectSessionInUrl: false
        }
      }
    );
    state.realtime = state.realtimeClient
      .channel(`ops-events-${state.config.runId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "events",
          filter: `run_id=eq.${state.config.runId}`
        },
        () => {
          void scheduleRefresh("realtime").catch(() => {});
        }
      )
      .subscribe((status) => {
        state.realtimeSubscribed = status === "SUBSCRIBED";
        if (["CHANNEL_ERROR", "TIMED_OUT", "CLOSED"].includes(status)) {
          state.realtimeSubscribed = false;
        }
        updateHealth();
      });
  } catch {
    state.realtimeSubscribed = false;
    showBanner("Realtime no está disponible; la simulación continúa con polling.");
    updateHealth();
  }
}

function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = window.setInterval(() => {
    const needsReconciliation = Date.now() - state.lastSuccessfulSync >= 30_000;
    if (!state.realtimeSubscribed || needsReconciliation) {
      void scheduleRefresh(state.realtimeSubscribed ? "reconcile" : "poll").catch(() => {});
    }
  }, 5000);
}

function buildCommand(commandType, payload) {
  const snapshot = state.snapshot;
  if (!snapshot) throw new Error("No hay un snapshot válido para construir el comando.");
  return {
    command_id: `ops-${crypto.randomUUID()}`,
    run_id: snapshot.run.run_id,
    pack_id: snapshot.run.pack_id,
    pack_version: snapshot.run.pack_version,
    pack_digest: snapshot.run.pack_digest,
    expected_state_version: snapshot.run.state_version,
    actor: "operator",
    command_type: commandType,
    payload,
    causation_id: null
  };
}

async function sendCommand(commandType, payload, control, affectedPanel) {
  const inFlightKey = payload.action_id
    ? `${commandType}:${payload.action_id}`
    : commandType;
  if (!state.snapshot || state.inFlight.has(inFlightKey)) return;

  const command = buildCommand(commandType, payload);
  const originalText = control.textContent;
  state.inFlight.add(inFlightKey);
  control.disabled = true;
  control.textContent = "Enviando… · SIMULACIÓN";

  try {
    const url = gatewayApiUrl("api/commands");
    const response = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json"
      },
      body: JSON.stringify(command)
    });
    let body;
    try {
      body = await response.json();
    } catch {
      throw new Error(`Gateway ${response.status}: la respuesta no es JSON válido.`);
    }

    if (response.status === 409 || body?.error === "version_conflict") {
      try {
        await scheduleRefresh("version_conflict");
      } catch {
        // El mensaje de conflicto sigue siendo la instrucción segura para el operador.
      }
      showBanner("El estado cambió; revisa la versión actual y vuelve a decidir.");
      affectedPanel?.focus();
      return;
    }

    if (!response.ok || body?.ok === false) {
      throw responseError(response.status, body);
    }

    await scheduleRefresh("command");
    showBanner(`Comando ${commandType} aceptado · SIMULACIÓN.`, "notice");
  } catch (error) {
    showBanner(`No se pudo enviar ${commandType} · SIMULACIÓN: ${error.message}`);
  } finally {
    state.inFlight.delete(inFlightKey);
    if (control.isConnected) {
      control.textContent = originalText;
    }
    updateRunControls();
    const replacement = [...document.querySelectorAll("button[data-action-id]")].find((button) => (
      button.dataset.actionId === payload.action_id
      && button.dataset.decision === control.dataset.decision
    ));
    if (replacement) replacement.disabled = false;
  }
}

function installListeners() {
  byId("actions-list").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action-id][data-decision]");
    if (!button || button.disabled) return;
    const actionId = button.dataset.actionId;
    const decision = button.dataset.decision;
    if (
      decision === "reject"
      && !window.confirm(`SIMULACIÓN: rechazar la Action ${actionId}. ¿Continuar?`)
    ) return;

    const commandType = decision === "approve" ? "approve_action" : "reject_action";
    void sendCommand(
      commandType,
      { action_id: actionId },
      button,
      byId("actions-panel")
    );
  });

  byId("run-controls").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-command]");
    if (!button || button.disabled) return;
    const commandType = button.dataset.command;
    if (
      commandType === "abort_run"
      && !window.confirm("SIMULACIÓN: abortar cierra el run y no puede deshacerse. ¿Continuar?")
    ) return;
    void sendCommand(commandType, {}, button, byId("run-panel"));
  });

  window.addEventListener("pagehide", () => {
    clearInterval(state.pollTimer);
    clearInterval(state.healthTimer);
    clearTimeout(state.refreshTimer);
    clearTimeout(state.recoveryNoticeTimer);
    if (state.realtimeClient && state.realtime) {
      void state.realtimeClient.removeChannel(state.realtime);
    }
  }, { once: true });
}

async function main() {
  try {
    state.config = readConfig();
  } catch (error) {
    showBanner(error.message);
    updateHealth();
    return;
  }

  installListeners();
  try {
    await refreshSnapshot("initial");
  } catch {
    // Polling mantiene la pantalla viva y reintentará sin habilitar mutaciones.
  }

  await startRealtime();
  startPolling();
  state.healthTimer = window.setInterval(updateHealth, 1000);
  updateHealth();
}

void main();
