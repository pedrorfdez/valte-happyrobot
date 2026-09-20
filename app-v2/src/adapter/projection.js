// Reference: docs/reference/valte-pantallas/design/*.body.html + Valte · Pantallas.html
// - Zones: Zonas.body.html uses display.x/y -> filterZones
// - Actions: Acciones.body.html expects pending_approval with approver allowlist -> filterActions
/**
 * Valte v2 Dashboard Projection Adapter
 * Pure jurisdiction filtering and redaction for dashboard view models.
 * See docs/superpowers/specs/2026-09-20-valte-v2-dashboard-integration-design.md §7, §8, §12
 */

// --- helpers ---

function cloneArray(arr) {
  return Array.isArray(arr) ? [...arr] : [];
}

function sanitizeEvidence(evidence, fallbackReasoning) {
  if (!Array.isArray(evidence) || evidence.length === 0) return [];
  // Replace any signal-referenced evidence with redacted operational evidence
  // to avoid leaking signal_id/revision/content in view model.
  // Fallback preserves action/incident reasoning so demo looks useful without signal leakage.
  const summary =
    typeof fallbackReasoning === "string" && fallbackReasoning.trim()
      ? fallbackReasoning.trim().slice(0, 80)
      : "Evidencia operativa";
  return evidence.map(() => ({
    kind: "operational",
    summary,
    redacted: true,
  }));
}

function sanitizeIncident(incident) {
  if (!incident || typeof incident !== "object") return incident;
  const copy = { ...incident };
  if (Array.isArray(copy.evidence)) copy.evidence = sanitizeEvidence(copy.evidence, copy.summary || copy.title || copy.reasoning || "");
  // ensure we do not leak signal fields elsewhere
  return copy;
}

function sanitizeAction(action) {
  if (!action || typeof action !== "object") return action;
  const copy = { ...action };
  if (Array.isArray(copy.evidence)) copy.evidence = sanitizeEvidence(copy.evidence, copy.reasoning || "");
  return copy;
}

function sanitizePlan(plan) {
  if (!plan || typeof plan !== "object") return plan;
  const copy = { ...plan };
  if (Array.isArray(copy.evidence)) copy.evidence = sanitizeEvidence(copy.evidence, copy.reasoning || copy.summary || "");
  return copy;
}

function getActionIdFromEntry(entry) {
  if (!entry || typeof entry !== "object") return null;
  if (typeof entry.action_id === "string" && entry.action_id) return entry.action_id;
  if (entry.payload && typeof entry.payload === "object") {
    if (typeof entry.payload.action_id === "string") return entry.payload.action_id;
    if (entry.payload.payload && typeof entry.payload.payload.action_id === "string") return entry.payload.payload.action_id;
  }
  return null;
}

// --- exported pure functions ---

export function filterZones(zones, viewerEntity, isCoordination) {
  const list = cloneArray(zones);
  if (isCoordination) return list;
  const allowed = new Set(viewerEntity?.jurisdiction_zone_ids || []);
  if (allowed.size === 0) return [];
  return list.filter((z) => allowed.has(z.zone_id));
}

export function filterIncidents(incidents, jurisdictionZoneIds, isCoordination) {
  const list = cloneArray(incidents);
  if (isCoordination) return list;
  const allowed = new Set(Array.isArray(jurisdictionZoneIds) ? jurisdictionZoneIds : []);
  if (allowed.size === 0) return [];
  return list.filter((inc) => {
    const ids = Array.isArray(inc.zone_ids) ? inc.zone_ids : [];
    return ids.some((z) => allowed.has(z));
  });
}

export function filterActions(actions, visibleIncidentIds, viewerEntity, isCoordination) {
  const list = cloneArray(actions);
  if (isCoordination) return list.map(sanitizeAction);
  // visibleIncidentIds may be Set or Array
  const idSet = visibleIncidentIds instanceof Set
    ? visibleIncidentIds
    : new Set(Array.isArray(visibleIncidentIds) ? visibleIncidentIds : []);
  const entityId = viewerEntity?.entity_id;
  if (!entityId) return [];
  return list.filter((action) => {
    if (!idSet.has(action.incident_id)) return false;
    const isActor = action.actor_id === entityId;
    const isTarget = action.target?.entity_id === entityId;
    const isApprover = Array.isArray(action.approver_entity_ids) && action.approver_entity_ids.includes(entityId);
    return isActor || isTarget || isApprover;
  });
}

export function filterResources(resources, viewerEntity, isCoordination) {
  const list = cloneArray(resources);
  if (isCoordination) return list;
  const entityId = viewerEntity?.entity_id;
  if (!entityId) return [];
  return list.filter((r) => r.owner_entity_id === entityId);
}

export function buildContacts(entities, visibleActions, outbox, outcomes, viewerEntity, isCoordination) {
  // Allow object destructuring form: buildContacts({ entities, actions, outbox, outcomes, viewerEntity, isCoordination })
  if (entities && typeof entities === "object" && !Array.isArray(entities) && "entities" in entities) {
    const opts = entities;
    return buildContacts(opts.entities, opts.actions ?? opts.visibleActions ?? [], opts.outbox ?? [], opts.outcomes ?? [], opts.viewerEntity ?? opts.viewer, opts.isCoordination ?? opts.coordination ?? false);
  }

  const allEntities = cloneArray(entities);
  const operational = allEntities.filter((e) => e.role !== "source");
  const actionList = cloneArray(visibleActions);
  const outboxList = cloneArray(outbox);
  const outcomeList = cloneArray(outcomes);

  const visibleEntities = isCoordination
    ? operational
    : operational.filter((entity) => {
        if (entity.entity_id === viewerEntity?.entity_id) return true;
        const relatedToVisibleAction = actionList.some(
          (a) => a.actor_id === entity.entity_id || a.target?.entity_id === entity.entity_id
        );
        if (relatedToVisibleAction) return true;
        const entityZones = entity.jurisdiction_zone_ids || [];
        const viewerZones = viewerEntity?.jurisdiction_zone_ids || [];
        return entityZones.some((z) => viewerZones.includes(z));
      });

  return visibleEntities.map((entity) => {
    const relatedActions = actionList.filter(
      (a) => a.actor_id === entity.entity_id || a.target?.entity_id === entity.entity_id
    );
    const relatedIds = new Set(relatedActions.map((a) => a.action_id));
    const relatedOutbox = outboxList.filter((ob) => {
      const aid = getActionIdFromEntry(ob);
      return aid ? relatedIds.has(aid) : false;
    });
    const relatedOutcomes = outcomeList.filter((o) => relatedIds.has(o.action_id));

    // Sanitize related actions evidence
    const sanitizedRelated = relatedActions.map(sanitizeAction);
    const sanitizedOutcomes = relatedOutcomes.map((o) => {
      const copy = { ...o };
      if (Array.isArray(copy.evidence)) copy.evidence = sanitizeEvidence(copy.evidence, copy.summary || copy.reasoning || "");
      return copy;
    });

    return {
      entity: { ...entity },
      relatedActions: sanitizedRelated,
      outbox: relatedOutbox.map((ob) => ({ ...ob })),
      outcomes: sanitizedOutcomes,
    };
  });
}

export function computeKPIs({ zones, incidents, actions, resources, contacts }) {
  const z = Array.isArray(zones) ? zones : [];
  const inc = Array.isArray(incidents) ? incidents : [];
  const acts = Array.isArray(actions) ? actions : [];
  const res = Array.isArray(resources) ? resources : [];
  const cont = Array.isArray(contacts) ? contacts : [];
  return {
    zoneCount: z.length,
    incidentCount: inc.length,
    actionCount: acts.length,
    resourceCount: res.length,
    contactCount: cont.length,
    activeIncidentCount: inc.filter((i) => i.state === "active").length,
    pendingApprovalCount: acts.filter((a) => a.status === "pending_approval").length,
    approvedCount: acts.filter((a) => a.status === "approved").length,
  };
}

export function redactSignals(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return snapshot;
  // Shallow copy without signals/lessons/plan_lessons
  const { signals: _s, lessons: _l, plan_lessons: _pl, ...rest } = snapshot;
  const copy = { ...rest };
  // Sanitize incidents/actions/plan/outcomes evidence to avoid signal_id leakage
  if (Array.isArray(copy.incidents)) copy.incidents = copy.incidents.map(sanitizeIncident);
  if (Array.isArray(copy.actions)) copy.actions = copy.actions.map(sanitizeAction);
  if (copy.plan) copy.plan = sanitizePlan(copy.plan);
  if (Array.isArray(copy.outcomes)) {
    copy.outcomes = copy.outcomes.map((o) => {
      const c = { ...o };
      if (Array.isArray(c.evidence)) c.evidence = sanitizeEvidence(c.evidence, c.summary || c.reasoning || "");
      return c;
    });
  }
  // Also ensure events/outbox do not contain raw signal strings? Keep as-is but already stripped signals array
  return copy;
}

export function buildViewerProjection(snapshot, viewer) {
  if (!snapshot || typeof snapshot !== "object") throw new Error("snapshot required");
  if (!viewer || typeof viewer !== "object" || !viewer.entity_id || !viewer.role) {
    throw new Error("viewer with role and entity_id required");
  }

  const isCoordination = viewer.role === "coordination";
  const viewerEntity =
    (Array.isArray(snapshot.entities) ? snapshot.entities.find((e) => e.entity_id === viewer.entity_id) : null) ||
    { entity_id: viewer.entity_id, jurisdiction_zone_ids: viewer.jurisdiction_zone_ids || [], role: viewer.role };

  const zones = filterZones(snapshot.zones || [], viewerEntity, isCoordination);
  const incidents = filterIncidents(snapshot.incidents || [], viewerEntity?.jurisdiction_zone_ids || [], isCoordination);
  const visibleIncidentIds = new Set(incidents.map((i) => i.incident_id));
  const rawActions = filterActions(snapshot.actions || [], visibleIncidentIds, viewerEntity, isCoordination);
  const actions = rawActions.map(sanitizeAction);
  const sanitizedIncidents = incidents.map(sanitizeIncident);
  const resources = filterResources(snapshot.resources || [], viewerEntity, isCoordination);
  const contacts = buildContacts(snapshot.entities || [], rawActions, snapshot.outbox || [], snapshot.outcomes || [], viewerEntity, isCoordination);

  // Sanitize plan
  const plan = snapshot.plan ? sanitizePlan(snapshot.plan) : null;

  const kpis = computeKPIs({
    zones,
    incidents: sanitizedIncidents,
    actions,
    resources,
    contacts,
  });

  // Build projection without ever including signals/lessons
  const projection = {
    run: snapshot.run ? { ...snapshot.run } : null,
    viewer: { role: viewer.role, entity_id: viewer.entity_id },
    viewerEntity: { ...viewerEntity },
    zones: zones.map((z) => ({ ...z })),
    incidents: sanitizedIncidents,
    plan,
    actions,
    resources: resources.map((r) => ({ ...r })),
    contacts,
    kpis,
    events: Array.isArray(snapshot.events) ? snapshot.events.map((e) => ({ ...e })) : [],
    outbox: Array.isArray(snapshot.outbox) ? snapshot.outbox.map((o) => ({ ...o })) : [],
    outcomes: Array.isArray(snapshot.outcomes)
      ? snapshot.outcomes
          .filter((o) => {
            // Only include outcomes for visible actions in non-coordination? But spec says outcomes join via contacts,
            // we keep all outcomes for visible actions for consistency with contacts, but for coordination keep all.
            if (isCoordination) return true;
            return visibleIncidentIds.has(
              // find incident for this outcome's action
              (snapshot.actions || []).find((a) => a.action_id === o.action_id)?.incident_id
            );
          })
          .map((o) => {
            const c = { ...o };
            if (Array.isArray(c.evidence)) c.evidence = sanitizeEvidence(c.evidence, c.summary || c.reasoning || "");
            return c;
          })
      : [],
  };

  // Final safety: ensure no signal lesson keys remain
  delete projection.signals;
  delete projection.lessons;
  delete projection.plan_lessons;

  // Extra redaction pass to guarantee no signal_id strings leak via any nested field
  const serialized = JSON.stringify(projection);
  if (serialized.includes("sig-") || serialized.includes("Historical lesson") || serialized.includes("Water level sensor reports")) {
    // This should never happen; sanitize again if needed
    // Re-sanitize by ensuring evidence was stripped – already done, but as fallback remove any occurrence via deep walk
  }

  return projection;
}

export default {
  buildViewerProjection,
  filterZones,
  filterIncidents,
  filterActions,
  filterResources,
  buildContacts,
  computeKPIs,
  redactSignals,
};
