import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { resolve } from "node:path";

const actionsPath = resolve("app-v2/src/screens/actions.js");
const contactsPath = resolve("app-v2/src/screens/contacts.js");

describe("browser: actions screen parity with Acciones.body.html", () => {
  test("renderActions eligible viewer renders Aprobar/Rechazar with data-decide", async () => {
    const { renderActions } = await import(actionsPath);
    assert.equal(typeof renderActions, "function", "renderActions must be exported");
    const actions = [
      {
        action_id: "act-0031",
        id: "act-0031",
        status: "pending_approval",
        approval_policy: "human_required",
        approver_entity_ids: ["mayor-paiporta", "cecopi-coordination"],
        actor_id: "alcaldia-paiporta",
        verbLabel: "Ordenar evacuación",
        actorName: "Alcaldía de Paiporta",
        deadline: "04:12",
        time: "16:30",
        reasoning: "Caudal del Poyo en ascenso",
        evidence: [{ summary: "evidencia operativa" }],
        action: { id: "act-0031", verb: "order_evacuation", actor: "alcaldia-paiporta", target_zones: ["paiporta"], status: "pending_approval", evidence: ["sig-0102"], reasoning: "Caudal del Poyo", real_interaction: null },
        target_zones: ["paiporta"],
      },
    ];
    const htmlEligible = renderActions(actions, { entity_id: "mayor-paiporta", role: "authority" });
    // eligible viewer must see both buttons with data-decide attributes
    assert.ok(htmlEligible.includes("Aprobar"), "eligible should see Aprobar");
    assert.ok(htmlEligible.includes("Rechazar"), "eligible should see Rechazar");
    assert.ok(htmlEligible.includes('data-decide="approve"'), "must have data-decide approve");
    assert.ok(htmlEligible.includes('data-decide="reject"'), "must have data-decide reject");
    assert.ok(htmlEligible.includes('data-action-id="act-0031"'), "must have data-action-id");
  });

  test("renderActions non-eligible viewer does NOT render Aprobar/Rechazar", async () => {
    const { renderActions } = await import(actionsPath);
    const actions = [
      {
        action_id: "act-0031",
        status: "pending_approval",
        approver_entity_ids: ["mayor-paiporta"],
        verbLabel: "Ordenar evacuación",
        actorName: "Alcaldía de Paiporta",
        deadline: "04:12",
        time: "16:30",
        reasoning: "Caudal",
        evidence: [],
      },
    ];
    const htmlNonEligible = renderActions(actions, { entity_id: "rescue-team", role: "responder" });
    assert.equal(htmlNonEligible.includes('data-decide="approve"'), false, "non-eligible must NOT have approve button");
    assert.equal(htmlNonEligible.includes('data-decide="reject"'), false, "non-eligible must NOT have reject button");
  });

  test("renderActions uses Valte.ActionItem structure verbLabel actorName deadline", async () => {
    const { renderActions } = await import(actionsPath);
    const actions = [
      {
        action_id: "act-0031",
        id: "act-0031",
        status: "pending_approval",
        approver_entity_ids: ["mayor-paiporta"],
        verbLabel: "Ordenar evacuación",
        actorName: "Alcaldía de Paiporta",
        deadline: "04:12",
        time: "16:30",
        reasoning: "Caudal del Poyo en ascenso",
        evidence: [{ summary: "ok" }],
        action: { id: "act-0031", verb: "order_evacuation", actor: "alcaldia-paiporta", target_zones: ["paiporta"], status: "pending_approval", reasoning: "Caudal", evidence: ["sig-0102"] },
      },
    ];
    const html = renderActions(actions, { entity_id: "mayor-paiporta", role: "authority" });
    // must render verbLabel, actorName, deadline from Acciones.mock.js + ActionItem
    assert.ok(html.includes("Ordenar evacuación"), "must render verbLabel Ordenar evacuación");
    assert.ok(html.includes("Alcaldía de Paiporta"), "must render actorName");
    assert.ok(html.includes("04:12"), "must render deadline 04:12");
    // Valte.ActionItem parity: check for vt-log or Valte.ActionItem marker and col-head Por aprobar
    const hasActionItemMarker = html.includes("Valte.ActionItem") || html.includes("vt-log") || html.includes("vt-log__verb") || html.includes("vt-log__head");
    assert.ok(hasActionItemMarker, "must use Valte.ActionItem structure (vt-log / Valte.ActionItem)");
    // also check col-head from Acciones.body.html
    assert.ok(html.includes("Por aprobar") || html.includes("col-head"), "should include Por aprobar col-head from Acciones.body.html");
  });

  test("renderActions executed status never shows approve buttons", async () => {
    const { renderActions } = await import(actionsPath);
    const actions = [
      { action_id: "act-0033", status: "executed", approver_entity_ids: ["mayor-paiporta"], verbLabel: "Rescate", actorName: "Bomberos", deadline: "04:12", time: "16:31" },
    ];
    const html = renderActions(actions, { entity_id: "mayor-paiporta", role: "authority" });
    assert.equal(html.includes('data-decide="approve"'), false, "executed must not have approve");
  });

  test("renderContacts parity with Contactos.body.html no send/call Sin comunicaciones", async () => {
    const { renderContacts } = await import(contactsPath);
    assert.equal(typeof renderContacts, "function", "renderContacts must be exported");
    // empty relatedActions -> Sin comunicaciones registradas
    const emptyContacts = [
      { entity: { entity_id: "mayor-paiporta", name: "Alcaldía de Paiporta", role: "authority", jurisdiction_zone_ids: ["paiporta-ground-floor"] }, relatedActions: [], outbox: [], outcomes: [] },
    ];
    const htmlEmpty = renderContacts(emptyContacts);
    assert.ok(htmlEmpty.includes("Sin comunicaciones registradas"), "must show Sin comunicaciones registradas when relatedActions empty");
    // must NOT contain send/call/email controls
    const lower = htmlEmpty.toLowerCase();
    assert.equal(lower.includes("enviar") && lower.includes("send"), false, "must not have send controls");
    // check no call/email buttons (spec: no send/call)
    assert.equal(htmlEmpty.includes("Tomar la llamada") && htmlEmpty.includes("data-testid=\"send\""), true ? false : true, "contact must not expose send/call controls - check forbidden strings");
    // explicitly ensure forbidden strings absent
    assert.equal(htmlEmpty.includes("Enviar"), false, "must not contain Enviar");
    assert.equal(htmlEmpty.includes("Llamar"), false, "must not contain Llamar");
  });

  test("renderContacts renders simulated_transcript sanitized", async () => {
    const { renderContacts } = await import(contactsPath);
    const contacts = [
      {
        entity: { entity_id: "mayor-paiporta", name: "Alcaldía de Paiporta", role: "authority", jurisdiction_zone_ids: [] },
        relatedActions: [{ action_id: "act-0031" }],
        outbox: [],
        outcomes: [{ action_id: "act-0031", transcript: "Simulated transcript <script>alert(1)</script>", summary: "ok" }],
      },
    ];
    const html = renderContacts(contacts);
    assert.ok(html.includes("Simulated transcript"), "must render simulated_transcript");
    // must be sanitized: no raw <script>
    assert.equal(html.includes("<script>"), false, "transcript must be sanitized (no raw script tag)");
    assert.ok(html.includes("&lt;script&gt;"), "sanitized transcript should escape html");
    // must not contain raw sig ids leakage? just check transcript present
  });
});
