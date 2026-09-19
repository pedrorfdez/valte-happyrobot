# Crisis Demo Parallel Orchestration Implementation Plan

> **Desvío cierre 2026-09-19:** Gateway activo es Supabase Edge Function (`supabase/functions/gateway` → `https://<ref>.supabase.co/functions/v1/gateway`). Azure Static Web Apps / Functions ya no es ruta activa; `make up` solo sirve el dashboard local.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one complete DANA demo and immediately replay the same system with a wildfire pack, using six non-overlapping workstreams and the minimum custom code.

**Architecture:** The coordinator freezes the Gateway boundary, dispatches three Wave 1 workers, integrates the state/workflow core, then dispatches three Wave 2 workers for the operator experience and E2E proof. Supabase is the authority, HappyRobot reasons and communicates, the Supabase Edge Gateway serves the HTTP API and the local `app/` dashboard is served via `make up`, and Scenario Packs contain all crisis-specific data.

**Tech Stack:** Node.js 24 ESM, JSON Schema 2020-12, Supabase Postgres/Realtime, Azure Static Web Apps managed Functions, HappyRobot REST/platform configuration, plain HTML/CSS/JavaScript

---

## Execution constraints

- Do not use TDD and do not add Vitest, Jest, Playwright, Docker, Redis, Kafka, or another backend.
- Run the exact smoke checks in each workstream instead of creating a unit-test suite.
- Run at most three implementation workers concurrently, plus the coordinator.
- Workers edit only the files assigned to their workstream and do not commit.
- Only the coordinator edits shared interfaces, `.env.example`, `.gitignore`, `package.json`, or `package-lock.json`.
- Only the coordinator commits, after each integration gate is green.
- Do not change `schemas/v1/**`, `schemas/v2/**`, or `examples/contracts/**` in this delivery.
- Every visible or external communication must say `SIMULACIÓN`.
- External interaction is restricted to demo recipients; dry-run remains the default.

## Delivery map

```text
Coordinator — Wave 0
  freeze HTTP envelopes + environment names + clean baseline
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
Wave 1   Supabase     Scenario    HappyRobot
         + Gateway    Controller  workflows
             └───────────┼───────────┘
                         ▼
                 Integration Gate 1
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
Wave 2   SWA dashboard  Real       E2E +
                       interaction runbook
             └───────────┼───────────┘
                         ▼
                 Integration Gate 2
                         │
                         ▼
                 two-scenario demo
```

| Workstream | Plan | Exclusive ownership |
| --- | --- | --- |
| A | `2026-09-19-supabase-gateway.md` | `supabase/migrations/**`, `supabase/seed.sql`, `api/_shared/**`, `api/commands/**`, `api/event-router/**`, `api/snapshot/**` |
| B | `2026-09-19-scenario-controller.md` | `scenario-packs/dana-demo/**`, `scenario-packs/wildfire-demo/**`, `scripts/scenario-controller.mjs` |
| C | `2026-09-19-happyrobot-workflows.md` | `happyrobot/crisis-intake/**`, `happyrobot/crisis-command/**`, `happyrobot/crisis-response-coordination/**`, `happyrobot/README.md` |
| D | `2026-09-19-swa-dashboard.md` | `app/index.html`, `app/app.js`, `app/styles.css`, `staticwebapp.config.json` |
| E | `2026-09-19-real-interaction.md` | `happyrobot/integrations/**`, `examples/real-interaction/**`, `docs/demo-contacts.md` |
| F | `2026-09-19-crisis-e2e-demo.md` | `scripts/e2e-demo.mjs`, `docs/demo-runbook.md`, `artifacts/e2e/**` |

## Frozen command boundary

All workers use these routes and do not invent alternatives:

```text
POST /api/commands
GET  /api/snapshot?run_id=<run-id>
POST /api/event-router
```

The command request is:

```json
{
  "command_id": "cmd-unique",
  "run_id": "run-id",
  "pack_id": "pack-id",
  "pack_version": "1.0.0",
  "pack_digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "expected_state_version": 3,
  "actor": "scenario-controller|happyrobot|operator",
  "command_type": "receive_source_input|upsert_signal|replace_plan|approve_action|reject_action|record_outcome|advance_clock|pause_run|resume_run|abort_run",
  "payload": {},
  "causation_id": null
}
```

Success and replay use HTTP 200:

```json
{
  "ok": true,
  "command_id": "cmd-unique",
  "run_id": "run-id",
  "state_version": 4,
  "replayed": false,
  "result": {},
  "events": []
}
```

Repeating `command_id` returns the persisted response with `replayed: true` and creates no new state, event, or outbox row. Optimistic concurrency failure uses HTTP 409:

```json
{
  "ok": false,
  "error": "version_conflict",
  "run_id": "run-id",
  "expected_state_version": 3,
  "actual_state_version": 4
}
```

Validation/not-found errors use HTTP 400/404 and `{ "ok": false, "error": "stable_code", "message": "human-readable detail" }`.

The snapshot response uses this stable top-level shape:

```json
{
  "run": {},
  "signals": [],
  "incidents": [],
  "plan": null,
  "actions": [],
  "outcomes": [],
  "resources": [],
  "events": [],
  "outbox": []
}
```

It never contains `hidden_truth`, `scenario_truth`, HappyRobot credentials, or recipient contact details.

## Task 1: Wave 0 — freeze shared delivery inputs

**Files:**

- Create: `docs/contracts/gateway-api.md`
- Modify: `.env.example`
- Modify: `.gitignore`

- [ ] **Step 1: Confirm the existing contract baseline**

Run:

```bash
npm ci
npm run contracts:check
git diff --check
```

Expected output includes:

```text
PASS dana-demo: Signal → Incident → Plan → Action → Outcome
PASS wildfire-demo: Signal → Incident → Plan → Action → Outcome
```

- [ ] **Step 2: Document the frozen HTTP contract**

Create `docs/contracts/gateway-api.md` from the “Frozen command boundary” section above and add:

```text
Event allowlist:
source_input.received -> crisis-intake
signal.created         -> crisis-command
signal.revised         -> crisis-command
action.approved        -> crisis-response-coordination
outcome.recorded       -> crisis-command

POST /api/event-router request: {"limit": 10}
POST /api/event-router response:
{"claimed":0,"dispatched":0,"failed":0,"results":[]}
```

State explicitly that the Router calls HappyRobot, while all resulting domain writes return through `/api/commands`.

- [ ] **Step 3: Freeze all environment variable names**

Append to `.env.example`:

```dotenv
# Gateway / local Azure Functions
GATEWAY_URL=http://localhost:7071

# HappyRobot workflow IDs created from the versioned repository definitions
HAPPYROBOT_INTAKE_WORKFLOW_ID=your_intake_workflow_id_here
HAPPYROBOT_COMMAND_WORKFLOW_ID=your_command_workflow_id_here
HAPPYROBOT_COORDINATION_WORKFLOW_ID=your_coordination_workflow_id_here

# Seeded demo run IDs
DANA_RUN_ID=run-dana-demo
WILDFIRE_RUN_ID=run-wildfire-demo

# External effects default to no-contact mode
DEMO_INTERACTION_MODE=dry-run
DEMO_VOICE_TARGET=demo_recipient_alias
DEMO_EMAIL_TARGET=demo_recipient_alias
```

Do not add real phone numbers, email addresses, keys, or tokens.

- [ ] **Step 4: Ignore generated E2E evidence but retain its directory**

Append to `.gitignore`:

```gitignore
artifacts/e2e/*.json
!artifacts/e2e/.gitkeep
```

- [ ] **Step 5: Re-run the baseline**

Run:

```bash
npm run contracts:check
git diff --check
```

Expected: both contract chains pass and `git diff --check` prints nothing.

## Task 2: Dispatch Wave 1

- [ ] **Step 1: Start exactly three workers concurrently**

Give each worker the full text of its own plan plus these shared constraints:

```text
Do not edit outside your ownership list.
Do not change schemas/v2 or the frozen Gateway routes/envelopes.
Do not add a test framework or perform TDD.
Use only the smoke checks in your plan.
Do not commit; report changed files, commands, output, and blockers.
If an interface is insufficient, stop and report the exact missing field.
```

- [ ] **Step 2: Assign the plans**

```text
Worker A -> docs/superpowers/plans/2026-09-19-supabase-gateway.md
Worker B -> docs/superpowers/plans/2026-09-19-scenario-controller.md
Worker C -> docs/superpowers/plans/2026-09-19-happyrobot-workflows.md
```

- [ ] **Step 3: While they work, prepare only integration commands**

Do not implement missing worker code in parallel. Prepare a local `.env` from `.env.example`, verify `supabase --version` when available, and confirm the HappyRobot development workspace is accessible.

## Task 3: Integration Gate 1 — prove the core

- [ ] **Step 1: Review ownership and unintended edits**

Run:

```bash
git status --short
git diff --name-only
git diff --check
```

Expected: changed paths fit Wave 0 or A/B/C ownership; whitespace check is silent.

- [ ] **Step 2: Run local/static checks in this order**

```bash
npm run contracts:check
node scripts/scenario-controller.mjs \
  --pack scenario-packs/dana-demo \
  --run-id run-dana-demo \
  --state-version 0 \
  --operation-id gate-1-dana \
  --dry-run > /tmp/gate-1-dana.jsonl
node scripts/scenario-controller.mjs \
  --pack scenario-packs/wildfire-demo \
  --run-id run-wildfire-demo \
  --state-version 0 \
  --operation-id gate-1-wildfire \
  --dry-run > /tmp/gate-1-wildfire.jsonl
```

Expected: contract checks pass; each controller run prints deterministic JSON commands and exits zero.

- [ ] **Step 3: Apply the Supabase migration and seed**

Use the command specified by the Supabase/Gateway plan. Expected: clean schema creation, one seeded DANA run, and no SQL error.

- [ ] **Step 4: Prove idempotency before connecting workflows**

Send the same `command_id` twice to `/api/commands`. Expected: the second response has `replayed: true`, the same `state_version` and result, and row counts do not increase.

- [ ] **Step 5: Prove the full core chain**

Execute one source input through public routes only:

```text
Scenario Controller -> receive_source_input
Event Router         -> crisis-intake
crisis-intake        -> upsert_signal
Event Router         -> crisis-command
crisis-command       -> replace_plan
approve_action       -> crisis-response-coordination
coordination         -> record_outcome
outcome.recorded     -> crisis-command replan
```

Expected: each transition increments `state_version`, all domain objects retain the same run/pack identity, and exact evidence revisions remain traceable.

- [ ] **Step 6: Check for leaked private data**

Run:

```bash
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=$RUN_ID" > /tmp/valte-snapshot.json
if rg -n 'hidden_truth|scenario_truth|service_role|HAPPYROBOT_KEY' /tmp/valte-snapshot.json; then exit 1; fi
```

Expected: `rg` finds nothing.

- [ ] **Step 7: Commit Wave 1 as coordinator**

```bash
git add .env.example .gitignore docs/contracts supabase api scenario-packs scripts/scenario-controller.mjs happyrobot
git commit -m "feat: add crisis orchestration core"
```

Do not continue to Wave 2 if any Gate 1 check fails.

## Task 4: Dispatch Wave 2

- [ ] **Step 1: Start exactly three workers concurrently**

```text
Worker D -> docs/superpowers/plans/2026-09-19-swa-dashboard.md
Worker E -> docs/superpowers/plans/2026-09-19-real-interaction.md
Worker F -> docs/superpowers/plans/2026-09-19-crisis-e2e-demo.md
```

Repeat the same no-overlap, no-TDD, no-commit constraints from Wave 1. Provide the actual local `GATEWAY_URL`, seeded `run_id`, and HappyRobot workflow IDs as runtime values, never by editing tracked files.

- [ ] **Step 2: Keep external effects disabled during parallel implementation**

Use:

```bash
export DEMO_INTERACTION_MODE=dry-run
```

Enable a controlled recipient only during Gate 2 after reviewing `docs/demo-contacts.md`.

## Task 5: Integration Gate 2 — prove the product

- [ ] **Step 1: Review scope and static quality**

```bash
git status --short
git diff --name-only HEAD
git diff --check
npm run contracts:check
```

Expected: only D/E/F ownership paths changed, no whitespace error, both contract chains still pass.

- [ ] **Step 2: Run every workstream smoke check**

Execute the exact smoke commands from the dashboard, real-interaction, and E2E plans. Do not replace a failed check with visual inspection alone.

- [ ] **Step 3: Run the sequential DANA → wildfire E2E**

```bash
node scripts/e2e-demo.mjs \
  --gateway "$GATEWAY_URL" \
  --dana-run "$DANA_RUN_ID" \
  --wildfire-run "$WILDFIRE_RUN_ID" \
  --effects dry-run
```

Expected final summary:

```text
PASS DANA: Signal → Intake → Command → approval → Coordination → Outcome → replan
PASS DANA abort: operator abort_run → run.status=aborted
PASS wildfire: same contracts and workflows
PASS wildfire abort: operator abort_run → run.status=aborted
PASS isolation: no DANA IDs or terms in wildfire
```

The runner must wait for the Scenario Controller to finish each timeline before draining the Router, so workflow writes cannot race the controller's `expected_state_version`. The wildfire artifact must contain its own `run_id`, `pack_id`, and digest and contain no DANA-only IDs or vocabulary.

- [ ] **Step 4: Perform one controlled external effect**

Follow `docs/demo-contacts.md`, switch only the selected Action to the configured demo alias, and execute the real-interaction smoke command. Expected: one `dispatch_id` produces exactly one Outcome; a retry returns the existing Outcome rather than contacting the recipient again.

- [ ] **Step 5: Verify the dashboard**

Open the dashboard, confirm the `SIMULACIÓN` banner, inspect Signal/Incident/Plan/Action/Outcome traceability, approve or reject one pending Action, pause/resume the run, and verify `state_version` advances without a full page reload.

- [ ] **Step 6: Scan tracked changes for accidental secrets**

```bash
git diff --cached --check
if git diff -- . ':!package-lock.json' | rg -n '(service_role|Bearer [A-Za-z0-9_-]{20,}|@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\+[0-9][0-9 -]{7,})'; then exit 1; fi
```

Expected: no real key, bearer token, phone number, or email address is found. Review any intentional placeholder match manually.

- [ ] **Step 7: Commit Wave 2 as coordinator**

```bash
git add app staticwebapp.config.json happyrobot/integrations examples/real-interaction docs/demo-contacts.md scripts/e2e-demo.mjs docs/demo-runbook.md artifacts/e2e/.gitkeep
git commit -m "feat: complete generalist crisis demo"
```

## Task 6: Final handoff

- [ ] **Step 1: Run final reproducibility checks**

```bash
npm ci
npm run contracts:check
node scripts/scenario-controller.mjs --pack scenario-packs/dana-demo --run-id run-dana-demo --state-version 0 --operation-id final-dana --dry-run > /tmp/final-dana.jsonl
node scripts/scenario-controller.mjs --pack scenario-packs/wildfire-demo --run-id run-wildfire-demo --state-version 0 --operation-id final-wildfire --dry-run > /tmp/final-wildfire.jsonl
git diff --check
git status --short
```

Expected: all checks exit zero and `git status --short` is empty.

- [ ] **Step 2: Record the demo order**

The operator follows `docs/demo-runbook.md` in this order:

```text
1. Show clean DANA run and SIMULACIÓN banner.
2. Inject noisy source input.
3. Explain provisional Signal and evidence.
4. Show plan, scarce resource choice, and human approval.
5. Trigger controlled interaction and record Outcome.
6. Inject changed conditions and show replan.
7. Close DANA.
8. Start wildfire and show the same contracts/workflows unchanged.
```

- [ ] **Step 3: Report remaining deliberate gaps**

Document as follow-up, not as blockers: four additional packs, advanced reservations, full retract/merge/split operations, terminal fencing, priority-lane backpressure, and postmortem comparison with hidden truth.
