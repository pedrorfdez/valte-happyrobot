import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { resolve } from "node:path";

const projectionPath = resolve("app-v2/src/adapter/projection.js");

// Snapshot fixture mirroring real get_run_snapshot shape,
// using zones/entities from scenario-packs/dana-demo with added overlaps
function makeSnapshot() {
  return {
    run: { run_id: "run-dana-demo", pack_id: "dana-demo", state_version: 5 },
    zones: [
      { zone_id: "paiporta-ground-floor", name: "Paiporta — planta baja", kind: "residential", display: { x: 18, y: 62 } },
      { zone_id: "catarroja-health-centre", name: "Catarroja — centro de salud", kind: "infrastructure", display: { x: 45, y: 40 } },
      { zone_id: "south-bridge", name: "Puente Sur", kind: "infrastructure", display: { x: 72, y: 55 } },
    ],
    entities: [
      { entity_id: "cecopi-coordination", entity_type: "coordination", name: "CECOPI Coordinación", role: "coordination", jurisdiction_zone_ids: ["paiporta-ground-floor", "catarroja-health-centre", "south-bridge"], fictional: true },
      { entity_id: "mayor-paiporta", entity_type: "authority", name: "Alcaldía Paiporta", role: "authority", jurisdiction_zone_ids: ["paiporta-ground-floor"], fictional: true },
      { entity_id: "rescue-team", entity_type: "emergency_response", name: "Equipo de rescate", role: "responder", jurisdiction_zone_ids: ["paiporta-ground-floor"], fictional: true },
      { entity_id: "south-authority", entity_type: "authority", name: "Autoridad Puente Sur", role: "authority", jurisdiction_zone_ids: ["south-bridge"], fictional: true },
      // source entities should never appear as contacts
      { entity_id: "caller-paiporta-01", entity_type: "resident", name: "Llamante", role: "source", jurisdiction_zone_ids: [], fictional: true },
    ],
    incidents: [
      { incident_id: "inc-1", state: "active", zone_ids: ["paiporta-ground-floor"], priority: "P0", evidence: [{ kind: "signal", signal_id: "sig-dana-001", revision: 1 }] },
      { incident_id: "inc-2", state: "active", zone_ids: ["catarroja-health-centre"], priority: "P1", evidence: [{ kind: "signal", signal_id: "sig-dana-002", revision: 1 }] },
      { incident_id: "inc-3", state: "active", zone_ids: ["south-bridge"], priority: "P2", evidence: [{ kind: "signal", signal_id: "sig-dana-003", revision: 1 }] },
      { incident_id: "inc-4", state: "closed", zone_ids: ["paiporta-ground-floor"], priority: "P1", evidence: [{ kind: "signal", signal_id: "sig-dana-004", revision: 1 }] },
    ],
    plan: { plan_id: "plan-dana-001", status: "active", action_ids: ["act-1", "act-2", "act-3", "act-4"] },
    actions: [
      // visible to mayor-paiporta via approver, incident paiporta
      { action_id: "act-1", plan_id: "plan-dana-001", incident_id: "inc-1", status: "pending_approval", approval_policy: "human_required", approver_entity_ids: ["mayor-paiporta", "cecopi-coordination"], actor_id: "rescue-team", target: { zone_id: "paiporta-ground-floor" }, evidence: [{ kind: "signal", signal_id: "sig-dana-001", revision: 1 }], reasoning: "Need rescue" },
      // catarroja incident, actor cecopi, should NOT be visible to mayor-paiporta
      { action_id: "act-2", plan_id: "plan-dana-001", incident_id: "inc-2", status: "approved", approval_policy: "automatic", actor_id: "cecopi-coordination", target: { zone_id: "catarroja-health-centre" }, evidence: [{ kind: "signal", signal_id: "sig-dana-002", revision: 1 }], reasoning: "Medical" },
      // incident paiporta, actor mayor-paiporta => visible via actor
      { action_id: "act-3", plan_id: "plan-dana-001", incident_id: "inc-1", status: "approved", approval_policy: "automatic", actor_id: "mayor-paiporta", target: { entity_id: "rescue-team" }, evidence: [{ kind: "signal", signal_id: "sig-dana-001", revision: 1 }], reasoning: "Coordinate" },
      // south-bridge incident, actor rescue-team, target rescue? not visible to mayor because incident not in jurisdiction
      { action_id: "act-4", plan_id: "plan-dana-001", incident_id: "inc-3", status: "pending_approval", approval_policy: "human_required", approver_entity_ids: ["south-authority"], actor_id: "rescue-team", target: { zone_id: "south-bridge" }, evidence: [{ kind: "signal", signal_id: "sig-dana-003", revision: 1 }], reasoning: "South bridge" },
      // additional action for target test: target is entity rescue-team, incident paiporta, actor cecopi
      { action_id: "act-5", plan_id: "plan-dana-001", incident_id: "inc-4", status: "approved", approval_policy: "automatic", actor_id: "cecopi-coordination", target: { entity_id: "rescue-team" }, evidence: [{ kind: "signal", signal_id: "sig-dana-004", revision: 1 }], reasoning: "Target entity" },
    ],
    resources: [
      { resource_id: "water-rescue-team-1", owner_entity_id: "rescue-team", name: "Equipo de rescate acuático 1", resource_mode: "reusable", capacity: 1, initial_zone_id: "catarroja-health-centre" },
      { resource_id: "med-kit-1", owner_entity_id: "mayor-paiporta", name: "Botiquín", resource_mode: "consumable", capacity: 10, initial_zone_id: "paiporta-ground-floor" },
      { resource_id: "coord-truck", owner_entity_id: "cecopi-coordination", name: "Camión CECOPI", resource_mode: "reusable", capacity: 1, initial_zone_id: "south-bridge" },
      { resource_id: "south-resource", owner_entity_id: "south-authority", name: "Recurso Sur", resource_mode: "reusable", capacity: 1, initial_zone_id: "south-bridge" },
    ],
    signals: [
      { signal_id: "sig-dana-001", revision: 1, content: "Water level sensor reports flooding in Paiporta.", status: "active" },
      { signal_id: "sig-dana-002", revision: 1, content: "Clinic reports overflow", status: "active" },
    ],
    lessons: [
      { lesson_id: "lesson-1", content: "Historical lesson should never be visible", pack_id: "dana-demo" },
    ],
    plan_lessons: [{ plan_id: "plan-dana-001", lesson_id: "lesson-1", run_id: "run-dana-demo" }],
    events: [
      { event_id: 1, run_id: "run-dana-demo", state_version: 1, event_type: "action.approved", payload: { action_id: "act-1" } },
    ],
    outbox: [
      { outbox_id: "ob-1", event_id: 1, destination: "crisis-response", dispatch_id: "disp-1", status: "dispatched", attempts: 1, action_id: "act-1", payload: { action_id: "act-1" } },
      { outbox_id: "ob-2", event_id: 2, destination: "crisis-response", dispatch_id: "disp-2", status: "pending", attempts: 0, action_id: "act-3", payload: { action_id: "act-3" } },
      { outbox_id: "ob-3", event_id: 3, destination: "crisis-response", dispatch_id: "disp-3", status: "dispatched", attempts: 1, action_id: "act-2", payload: { action_id: "act-2" } },
    ],
    outcomes: [
      { outcome_id: "out-1", action_id: "act-1", status: "success", summary: "The rescue team reached Paiporta.", transcript: "Simulated transcript for act-1", created_at: "2026-09-19T10:05:00Z" },
      { outcome_id: "out-2", action_id: "act-3", status: "pending", summary: "Awaiting confirmation", created_at: "2026-09-19T10:06:00Z" },
      { outcome_id: "out-3", action_id: "act-2", status: "success", summary: "Warning delivered", created_at: "2026-09-19T10:07:00Z" },
    ],
  };
}

describe("projection: jurisdiction and redaction", () => {
  test("buildViewerProjection exists and is pure", async () => {
    const mod = await import(projectionPath);
    assert.equal(typeof mod.buildViewerProjection, "function");
    assert.equal(typeof mod.filterZones, "function");
    assert.equal(typeof mod.filterIncidents, "function");
    assert.equal(typeof mod.filterActions, "function");
    assert.equal(typeof mod.filterResources, "function");
    assert.equal(typeof mod.buildContacts, "function");
    assert.equal(typeof mod.computeKPIs, "function");
    assert.equal(typeof mod.redactSignals, "function");
  });

  test("coordination sees global projection", async () => {
    const { buildViewerProjection } = await import(projectionPath);
    const snap = makeSnapshot();
    const proj = buildViewerProjection(snap, { role: "coordination", entity_id: "cecopi-coordination" });
    // zones
    assert.equal(proj.zones.length, 3, "coordination sees all zones");
    // incidents
    assert.equal(proj.incidents.length, 4, "coordination sees all incidents");
    // actions
    assert.equal(proj.actions.length, 5, "coordination sees all actions");
    // resources
    assert.equal(proj.resources.length, 4, "coordination sees all resources");
    // contacts: operational entities only (4), source excluded
    const contactIds = proj.contacts.map((c) => c.entity.entity_id).sort();
    assert.deepEqual(contactIds, ["cecopi-coordination", "mayor-paiporta", "rescue-team", "south-authority"].sort());
  });

  test("authority jurisdiction filtering zones and incidents", async () => {
    const { buildViewerProjection } = await import(projectionPath);
    const snap = makeSnapshot();
    const proj = buildViewerProjection(snap, { role: "authority", entity_id: "mayor-paiporta" });
    // mayor jurisdiction = paiporta-ground-floor only
    assert.equal(proj.zones.length, 1);
    assert.equal(proj.zones[0].zone_id, "paiporta-ground-floor");
    // incidents visible = inc-1 and inc-4 (both paiporta)
    const incIds = proj.incidents.map((i) => i.incident_id).sort();
    assert.deepEqual(incIds, ["inc-1", "inc-4"]);
    // not visible: inc-2, inc-3
    assert.equal(proj.incidents.some((i) => i.incident_id === "inc-2"), false);
    assert.equal(proj.incidents.some((i) => i.incident_id === "inc-3"), false);
  });

  test("authority sees only owned resources", async () => {
    const { buildViewerProjection } = await import(projectionPath);
    const snap = makeSnapshot();
    const projMayor = buildViewerProjection(snap, { role: "authority", entity_id: "mayor-paiporta" });
    assert.equal(projMayor.resources.length, 1);
    assert.equal(projMayor.resources[0].resource_id, "med-kit-1");
    assert.equal(projMayor.resources[0].owner_entity_id, "mayor-paiporta");

    const projRescue = buildViewerProjection(snap, { role: "responder", entity_id: "rescue-team" });
    assert.equal(projRescue.resources.length, 1);
    assert.equal(projRescue.resources[0].resource_id, "water-rescue-team-1");

    const projCoord = buildViewerProjection(snap, { role: "coordination", entity_id: "cecopi-coordination" });
    assert.equal(projCoord.resources.length, 4);
  });

  test("action visibility via actor / target / approver", async () => {
    const { buildViewerProjection } = await import(projectionPath);
    const snap = makeSnapshot();
    // mayor-paiporta: should see act-1 via approver, act-3 via actor, act-5 via target? act-5 incident inc-4 visible and target is rescue-team not mayor so not unless mayor is actor? Actually act-5 actor cecopi, target rescue-team, not mayor => should NOT be visible to mayor
    const projMayor = buildViewerProjection(snap, { role: "authority", entity_id: "mayor-paiporta" });
    const mayorActIds = projMayor.actions.map((a) => a.action_id).sort();
    assert.deepEqual(mayorActIds, ["act-1", "act-3"], `mayor actions ${mayorActIds}`);

    // rescue-team: act-1 via actor, act-3 via target, act-5 via target (rescue-team) and incident inc-4 visible
    const projRescue = buildViewerProjection(snap, { role: "responder", entity_id: "rescue-team" });
    const rescueActIds = projRescue.actions.map((a) => a.action_id).sort();
    assert.deepEqual(rescueActIds, ["act-1", "act-3", "act-5"]);

    // south-authority: jurisdiction south-bridge, visible incidents inc-3, actions where incident visible and actor/target/approver matches => act-4 only
    const projSouth = buildViewerProjection(snap, { role: "authority", entity_id: "south-authority" });
    const southActIds = projSouth.actions.map((a) => a.action_id).sort();
    assert.deepEqual(southActIds, ["act-4"]);
  });

  test("KPIs are computed after filtering", async () => {
    const { buildViewerProjection } = await import(projectionPath);
    const snap = makeSnapshot();
    const projCoord = buildViewerProjection(snap, { role: "coordination", entity_id: "cecopi-coordination" });
    const projMayor = buildViewerProjection(snap, { role: "authority", entity_id: "mayor-paiporta" });
    // coordination KPIs reflect global counts
    assert.equal(projCoord.kpis.zoneCount, 3);
    assert.equal(projCoord.kpis.incidentCount, 4);
    assert.equal(projCoord.kpis.actionCount, 5);
    assert.equal(projCoord.kpis.resourceCount, 4);
    // mayor KPIs reflect filtered counts
    assert.equal(projMayor.kpis.zoneCount, 1);
    assert.equal(projMayor.kpis.incidentCount, 2);
    assert.equal(projMayor.kpis.actionCount, 2);
    assert.equal(projMayor.kpis.resourceCount, 1);
    // pending approvals after filtering: mayor sees act-1 pending
    assert.equal(projMayor.kpis.pendingApprovalCount, 1);
    assert.equal(projCoord.kpis.pendingApprovalCount, 2); // act-1 and act-4
    // active incidents after filtering
    assert.equal(projMayor.kpis.activeIncidentCount, 1); // inc-1 active, inc-4 closed
  });

  test("signals and lessons never enter view model", async () => {
    const { buildViewerProjection, redactSignals } = await import(projectionPath);
    const snap = makeSnapshot();
    const proj = buildViewerProjection(snap, { role: "coordination", entity_id: "cecopi-coordination" });
    const dumped = JSON.stringify(proj);
    // no signals key
    assert.equal("signals" in proj, false, "projection must not have signals");
    assert.equal("lessons" in proj, false);
    assert.equal("plan_lessons" in proj, false);
    // no raw signal content leaked
    assert.equal(dumped.includes("sig-dana-001"), false, "signal ids must be redacted");
    assert.equal(dumped.includes("Historical lesson"), false);
    assert.equal(dumped.includes("Water level sensor reports"), false);
    // redactSignals pure utility also strips
    const redacted = redactSignals(snap);
    assert.equal("signals" in redacted, false);
    assert.equal("lessons" in redacted, false);
    assert.equal(JSON.stringify(redacted).includes("sig-dana-001"), false);
  });

  test("contacts join actions/outbox/outcomes and jurisdiction sharing", async () => {
    const { buildViewerProjection } = await import(projectionPath);
    const snap = makeSnapshot();
    const projCoord = buildViewerProjection(snap, { role: "coordination", entity_id: "cecopi-coordination" });
    // coordination sees all contacts
    assert.equal(projCoord.contacts.length, 4);
    const rescueContact = projCoord.contacts.find((c) => c.entity.entity_id === "rescue-team");
    assert.ok(rescueContact, "rescue-team contact exists");
    // rescue-team related actions: act-1 (actor), act-3 (target), act-4 (actor but filtered? coordination sees all), act-5 (target)
    const relatedIds = rescueContact.relatedActions.map((a) => a.action_id).sort();
    assert.ok(relatedIds.includes("act-1"));
    assert.ok(relatedIds.includes("act-3"));
    // outbox linked to related actions
    const outboxIds = rescueContact.outbox.map((o) => o.outbox_id).sort();
    // act-1 and act-3 have outbox entries
    assert.ok(outboxIds.includes("ob-1"));
    assert.ok(outboxIds.includes("ob-2"));
    // outcomes linked
    const outcomeIds = rescueContact.outcomes.map((o) => o.outcome_id).sort();
    assert.ok(outcomeIds.includes("out-1"));
    assert.ok(outcomeIds.includes("out-2"));
    // jurisdiction sharing: mayor shares paiporta with rescue-team, so rescue contact visible to mayor
    const projMayor = buildViewerProjection(snap, { role: "authority", entity_id: "mayor-paiporta" });
    const mayorContactIds = projMayor.contacts.map((c) => c.entity.entity_id).sort();
    // mayor should see itself, rescue-team (shares zone), cecopi (shares zone), but NOT south-authority (no shared zone and no related visible action)
    assert.ok(mayorContactIds.includes("mayor-paiporta"), "mayor sees self");
    assert.ok(mayorContactIds.includes("rescue-team"), "mayor sees rescue via shared jurisdiction");
    assert.ok(mayorContactIds.includes("cecopi-coordination"), "mayor sees cecopi via shared jurisdiction");
    assert.equal(mayorContactIds.includes("south-authority"), false, "mayor should not see south-authority");
    // south-authority isolation: only sees itself and maybe cecopi if shares? cecopi shares south-bridge, so yes
    const projSouth = buildViewerProjection(snap, { role: "authority", entity_id: "south-authority" });
    const southIds = projSouth.contacts.map((c) => c.entity.entity_id).sort();
    assert.ok(southIds.includes("south-authority"));
    assert.ok(southIds.includes("cecopi-coordination"));
    assert.equal(southIds.includes("mayor-paiporta"), false);
  });

  test("filter functions are pure and handle edge cases", async () => {
    const mod = await import(projectionPath);
    const snap = makeSnapshot();
    const zones = snap.zones;
    const incidents = snap.incidents;
    const actions = snap.actions;
    const resources = snap.resources;
    // filterZones pure: coordination returns copy
    const allZones = mod.filterZones(zones, { entity_id: "cecopi-coordination", jurisdiction_zone_ids: ["paiporta-ground-floor", "catarroja-health-centre", "south-bridge"] }, true);
    assert.equal(allZones.length, 3);
    const mayorEntity = snap.entities.find((e) => e.entity_id === "mayor-paiporta");
    const mayorZones = mod.filterZones(zones, mayorEntity, false);
    assert.deepEqual(mayorZones.map((z) => z.zone_id), ["paiporta-ground-floor"]);
    // filterIncidents
    const mayorInc = mod.filterIncidents(incidents, mayorEntity.jurisdiction_zone_ids, false);
    assert.equal(mayorInc.length, 2);
    // filterResources
    const mayorRes = mod.filterResources(resources, mayorEntity, false);
    assert.equal(mayorRes.length, 1);
    // filterActions requires visible incident ids
    const visibleIncIds = new Set(mayorInc.map((i) => i.incident_id));
    const mayorActs = mod.filterActions(actions, visibleIncIds, mayorEntity, false);
    assert.equal(mayorActs.length, 2);
  });
});
