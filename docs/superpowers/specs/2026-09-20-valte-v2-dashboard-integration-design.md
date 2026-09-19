# Valte v2 operational dashboard integration

**Date:** 2026-09-20

**Status:** Design decisions approved; awaiting written-spec review

**Source branch:** `codex/crisis-demo-implementation`

**Planned implementation branch:** `codex/valte-v2-dashboard-integration`

## 1. Purpose

Replace the current demonstration dashboard with the visual language and screen templates from
`feat/valte-v2`, while preserving the existing Valte workflow architecture:

```text
HappyRobot workflows
        ↓
Supabase Gateway
        ↓
Supabase operational state
        ↓
Dashboard projection adapter
        ↓
Valte v2 visual templates
```

The integration must not introduce the FastAPI/SQLite kernel from `feat/valte-v2`. Supabase remains
the only operational source of truth and the Gateway remains the only writer.

## 2. Product outcome

The dashboard provides an operational view of existing crisis runs. A user selects a run, enters as
Coordination, and can switch to a particular Authority or Response entity. Each non-coordination
entity sees only the zones, incidents, actions, resources, contacts, and KPIs within its jurisdiction.

Signals and historical lessons remain available to the workflows but are not visible anywhere in the
dashboard.

The first release supports existing runs only. It does not create, clone, reset, edit, or delete runs or
Scenario Packs.

## 3. Scope

### 3.1 Included screens

- Existing scenario list.
- Coordination panel.
- Authority panel.
- Response panel.
- Zones.
- Incidents and active plan.
- Actions and approval decisions.
- Resources.
- Informational contacts.

### 3.2 Explicit exclusions

- Signals screen, signal counters, raw signal text, signal IDs, and signal revisions.
- Historical lesson panel, lesson counters, lesson administration, and applied-lesson indicators.
- Scenario creation wizard.
- Interactive contact creation.
- Live voice and email controls.
- Manual incident reporting.
- FastAPI, SQLite, v2 patrols, v2 tripwires, and the v2 external-world simulator.
- Production authentication or authorization. Entity selection is a demonstration projection, not an
  identity boundary.

Signals and lessons are excluded from presentation only. They continue to participate in workflow
reasoning and persisted state.

## 4. Architectural boundaries

### 4.1 Components retained from the current branch

- `crisis-intake`, `crisis-command`, and `crisis-response-coordination` workflows.
- Supabase tables, command application, events, and outbox.
- `GET /api/snapshot?run_id=...`.
- `POST /api/commands`.
- Optimistic concurrency through `expected_state_version`.
- Command idempotency.
- Supabase Realtime with polling fallback.
- Scenario Packs and their deterministic fixtures.
- Historical learning as a non-visual workflow capability.

### 4.2 Components reused from `feat/valte-v2`

- Visual tokens, fonts, components, and layout assets.
- Screen markup for the included screens.
- The frontend build pipeline.
- The fixed 1440×900 presentation and responsive scaling behavior.

The original v2 API client and screen logic are not copied unchanged because they depend on the
FastAPI crisis API and SSE. They are replaced or adapted to consume the current Gateway contract.

### 4.3 Transition strategy

The existing `app/` dashboard remains available during development as a diagnostic fallback. The new
frontend is built separately and becomes the default only after integration tests pass. Removing the
old dashboard is outside this release.

## 5. Domain catalogue

The Scenario Pack is the canonical source of zone and entity identity. Runtime objects must reference
IDs present in that catalogue.

### 5.1 Zones

Each run persists the zones from its pack. A zone document contains at least:

```json
{
  "zone_id": "paiporta-ground-floor",
  "name": "Paiporta — planta baja",
  "kind": "residential",
  "display": { "x": 18, "y": 62 }
}
```

Incident `zone_ids`, action targets, entity jurisdictions, and resource locations must use these exact
IDs. Values such as `paiporta` are invalid when the catalogue contains only
`paiporta-ground-floor`.

### 5.2 Entities

Existing source entities remain in the pack with role `source`. Operational entities are added
explicitly:

```json
{
  "entity_id": "rescue-team",
  "entity_type": "emergency_response",
  "name": "Equipo de rescate",
  "role": "responder",
  "jurisdiction_zone_ids": ["paiporta-ground-floor"],
  "fictional": true
}
```

Allowed roles are:

- `coordination`: global operational view.
- `authority`: jurisdiction-scoped authority view.
- `responder`: jurisdiction-scoped response view.
- `source`: workflow input source; never selectable as a dashboard role.

Each run has at least one coordination entity. Every `actor_id`, target `entity_id`, approval entity,
and resource owner must resolve to an operational entity in the same run.

### 5.3 Resources

Every resource declares its owner:

```json
{
  "resource_id": "water-rescue-team-1",
  "owner_entity_id": "rescue-team",
  "name": "Equipo de rescate acuático 1",
  "resource_mode": "reusable",
  "capacity": 1,
  "initial_zone_id": "catarroja-health-centre"
}
```

The owner and initial zone must exist in the run catalogue.

### 5.4 Persistence

The database gains run-scoped zone and entity catalogues. The intended logical model is:

```text
scenario_zones(run_id, zone_id, document)
scenario_entities(run_id, entity_id, role, document)
```

The exact migration may use equivalent names, but the records must be queryable by run and included in
the observable snapshot as `zones` and `entities`. Pack loading and reset scripts populate them
deterministically.

## 6. Scenario list

The Gateway adds:

```text
GET /api/runs
```

It returns lightweight summaries and never returns complete snapshots:

```json
{
  "runs": [
    {
      "run_id": "run-dana-demo",
      "pack_id": "dana-demo",
      "name": "DANA — Paiporta",
      "status": "running",
      "scenario_now": "2026-09-19T10:04:00Z",
      "state_version": 18,
      "zone_count": 3,
      "active_incident_count": 2,
      "pending_approval_count": 1
    }
  ]
}
```

The initial screen can list and open runs. It cannot mutate them. Selecting a run stores its `run_id`
and always enters the dashboard as Coordination, regardless of the role used in the previously opened
run.

## 7. Viewer model and jurisdiction

The frontend keeps a viewer context:

```json
{
  "role": "coordination",
  "entity_id": "cecopi-coordination"
}
```

The user starts as the run's coordination entity and may switch to a selectable Authority or Response
entity from the header.

### 7.1 Coordination projection

Coordination sees:

- All zones.
- All incidents.
- The active plan and all observable actions.
- All resources.
- All operational contact entities and their histories.
- Global KPIs.

Signals and historical lessons remain hidden.

### 7.2 Authority and Response projection

For a selected entity, visible zones are its `jurisdiction_zone_ids`. Visible incidents are active or
historical incidents whose `zone_ids` intersect that jurisdiction.

An action is visible when all of the following are true:

1. Its incident is visible to the entity.
2. The entity is the action actor, target, or eligible approver.

A resource is visible when its `owner_entity_id` equals the selected entity ID. A contact entity is
visible when it is the selected entity, is directly related to a visible action, or shares at least one
jurisdiction zone with the selected entity.

KPIs are computed from the filtered projection, never from global counts.

### 7.3 Presentation versus security

Jurisdiction filtering in this release is a dashboard projection for the shared demonstration. It does
not provide tenant isolation because the browser can enter Coordination. The Gateway still enforces
all command invariants, especially approval authority and state transitions.

## 8. Signals and evidence redaction

The snapshot may contain signals for workflow and adapter use, but the UI must not render:

- Signal lists or counts.
- Raw signal content.
- Reporter or source details originating only from a signal.
- Signal IDs or revision numbers.

Incident, plan, and action evidence is converted into an operational explanation. For example, the UI
may render `Riesgo confirmado en Paiporta` but not `sig-dana-call-001 revision 2`.

Navigation, empty states, accessibility labels, DOM attributes, and client logs must not expose signal
details.

## 9. Action approval model

### 9.1 Contract

Human-approved actions add an explicit allowlist:

```json
{
  "status": "pending_approval",
  "approval_policy": "human_required",
  "approver_entity_ids": [
    "mayor-paiporta",
    "cecopi-coordination"
  ],
  "approvals_required": 1
}
```

Contract rules:

- `approver_entity_ids` is non-empty and unique when `approval_policy` is `human_required`.
- Every approver exists in the run's operational entity catalogue.
- `approvals_required` is fixed to `1` in this release.
- Automatic actions omit the allowlist or use an empty list.

### 9.2 Decision commands

`approve_action` and `reject_action` include the deciding entity ID and an optional note. The Gateway
verifies that:

- The action is still `pending_approval`.
- The deciding entity is in `approver_entity_ids`.
- The action belongs to the active plan.
- Evidence remains valid.
- `expected_state_version` is current.

The first valid decision is final:

```text
pending_approval ── approve ──→ approved
pending_approval ── reject  ──→ rejected
```

A rejected action cannot later be approved by another eligible entity. The decision is persisted with
its type, deciding entity, wall-clock time, and optional note. Rejection emits an event that can cause
`crisis-command` to reconsider the plan. Simultaneous decisions are resolved by optimistic
concurrency: one commits and the other receives `409 version_conflict`.

The dashboard only renders decision controls for eligible entities, but Gateway validation is the
authoritative control.

## 10. Run controls

Only the Coordination view renders pause, resume, and abort controls. Authority and Response views do
not render them. Existing Gateway commands and state transition validation remain authoritative.

No run controls appear on the initial scenario list.

## 11. Informational contacts

Contacts are a read-only projection rather than a new communication subsystem. The projection joins:

```text
entity → related action → event/outbox dispatch → outcome
```

For each operational entity the screen shows:

- Name, role, and jurisdiction.
- Related actions.
- Approval and dispatch status.
- Outbox delivery state.
- Outcome status and summary.
- Existing sanitized simulated transcript when an outcome contains one.
- A chronological activity history.

The screen contains no send, call, email, answer, listen, takeover, or hang-up controls. Empty contact
history is a valid state and is presented as `Sin comunicaciones registradas`.

## 12. Dashboard adapter

The frontend adapter is the boundary between Gateway documents and the v2 visual components. It:

1. Fetches run summaries.
2. Fetches and validates the selected snapshot.
3. Builds the viewer-scoped projection.
4. Produces view models for each screen.
5. Translates dashboard decisions and run controls into Gateway command envelopes.
6. Refreshes on Supabase Realtime event notifications.
7. Falls back to polling when Realtime is unavailable.
8. Avoids identical renders through snapshot fingerprints.

The adapter must be implemented as focused projection functions rather than embedding domain filters
inside template rendering. The same projection functions are used by screen code and tests.

## 13. Navigation and screen behavior

The header contains:

- Scenario identity and simulated time.
- Gateway/Realtime health.
- Current viewer identity.
- Role/entity switcher.
- KPIs for visible zones, incidents, actions, resources, and contacts.

It does not contain a Signals KPI.

The Plan and Incidents presentation is part of the operational panels rather than a separate Signals
flow. The Zones screen supports the visual map using the pack's `display` coordinates. Geocoding is not
required.

All visible buttons must complete a real end-to-end operation. Unsupported v2 controls are removed,
not disabled or mocked.

## 14. Realtime and consistency

Supabase Realtime events are refresh hints, not the source of rendered state. On a relevant event the
adapter debounces and fetches a fresh snapshot. Polling remains active as a degraded fallback when
Realtime is unavailable.

The dashboard displays:

- `live` when Realtime is connected and snapshots are current.
- `degraded` when polling is maintaining current state.
- `stale` when no current snapshot has arrived within the configured threshold.
- `offline` when the Gateway cannot provide a valid snapshot.

After a successful command, the client refreshes from the Gateway rather than mutating local domain
state optimistically.

## 15. Error handling

- `409 version_conflict`: refresh the snapshot and explain that another operator decided first.
- `400` validation errors: show the stable Gateway message without applying a local state change.
- `404 run_not_found`: return to the scenario list and mark the selected run unavailable.
- Realtime failure: enter degraded polling mode without blocking the dashboard.
- Snapshot validation failure: retain the last valid view, mark it stale, and surface a diagnostic.
- Unknown entity, zone, resource owner, actor, target, or approver: reject during pack loading or
  command validation; do not silently hide the malformed record.
- Missing outcome or contact history: render a normal empty state.

## 16. Validation and tests

### 16.1 Contract and database tests

- Human-approved actions require valid, unique approver entity IDs.
- Automatic actions cannot carry an effective human approval requirement.
- Actor, target, approver, owner, and zone references resolve within the same run.
- One eligible entity can approve an action.
- One eligible entity can reject an action.
- An ineligible entity cannot decide.
- A second decision cannot change the first.
- Concurrent decisions produce one success and one version conflict.
- Rejection emits the expected replanning event.
- `GET /api/runs` returns summaries without snapshots, signals, or lessons.

### 16.2 Projection tests

- Coordination sees the global operational projection.
- Authority and Response see only their jurisdiction zones and incidents.
- Authority and Response see only owned resources.
- Actor, target, and approver relationships produce the expected visible actions.
- KPIs are calculated after filtering.
- Signal data and lesson data never enter any view model.
- Contact histories join actions, outbox entries, and outcomes correctly.

### 16.3 Browser tests

- The initial screen lists DANA and wildfire runs and opens the selected run.
- Every run opens as Coordination.
- Switching viewer updates every screen and KPI.
- No Signals navigation item, screen, KPI, DOM content, or raw evidence is present.
- Approval and rejection controls appear only for eligible entities.
- The first approval or rejection is reflected after refresh.
- Realtime refresh works and polling fallback reports degraded mode.
- All included screens render useful empty states.
- The legacy dashboard remains launchable during the transition.

## 17. Delivery sequence

Implementation planning should order the work as follows:

1. Extend and validate pack catalogues.
2. Persist zones and entities and expose them in snapshots.
3. Extend Action approval contracts and Gateway validation.
4. Add the run summary endpoint.
5. Import the v2 visual assets and build pipeline.
6. Implement pure dashboard projection functions.
7. Wire the included screens and role switcher.
8. Wire commands, Realtime, polling, and error states.
9. Add contract, projection, browser, and regression tests.
10. Make the new dashboard the default only after verification.

## 18. Acceptance criteria

The integration is complete when:

- Existing DANA and wildfire runs appear on the initial screen.
- A selected run opens as Coordination.
- Authority and Response projections obey explicit entity jurisdiction.
- Signals and historical lessons are absent from the complete rendered dashboard.
- Actions declare their eligible approvers and the Gateway enforces the first-decision-wins rule.
- Contacts accurately present existing operational history without offering communication controls.
- All displayed controls perform real Gateway operations.
- Realtime and polling keep the view current.
- Existing workflow, Gateway, contract, and E2E tests remain passing.
- The new integration tests pass for both DANA and wildfire.
