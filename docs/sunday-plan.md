# Plan: from pipeline to demo

State when written (2026-09-19 morning): schemas, DANA scenario pack,
simulator, and the three HappyRobot ingest workflows with verified
perception are done. The kernel, the coordinator agent, the dashboard,
and the demo remain.

## Phase 1: unblock everything (Friday, now to early afternoon)

### 1a. Kernel milestones 1-3 (owner: Claude; the bottleneck)

1. Scaffold, migration, scenario loader, read endpoints.
2. Actions pipeline: validation, units ledger, idempotency, approval
   gate, system verbs with tripwires.
3. Signals ingress: confidence rule, reflex evaluation, outbox with a
   serialized coordinator lane.

Deploy to Fly or Railway (EU) as soon as milestone 1 stands. Done =
`KERNEL_SIGNALS_URL` is real and the coordinator and dashboard have an
API to build against.

### 1b. Real voice call proof (owner: teammate, in parallel, today)

Prove: webhook event in, HappyRobot places a real call to a teammate's
phone, transcript comes out. Highest-risk track requirement. If voice
is blocked on the hackathon account, fall back to WhatsApp, SMS, or
email (still a real interaction). Find out today, not on stage.

## Phase 2: close the loop (Friday afternoon)

### 2a. Perception to kernel

Add a webhook action node after each extract node that POSTs the
normalized signal to kernel `POST /signals`. Same fork-edit-publish
recipe (see `docs/happyrobot-api.md`).

### 2b. Coordinator workflow (the decision agent)

Single agent triggered by kernel events. Reads `GET /state`,
deliberates against the playbook, POSTs actions, PATCHes outcomes,
places voice calls (from 1b) to authorities. Requires the playbook:
one markdown document of flood doctrine (when to alert, evacuation
criteria, UME request threshold). Owner of the playbook: Pedro.

### 2c. Sim effects

`sim/effects.py`: executed actions change ground truth. Warnings set
`warned=true`, `at_risk_pct` responds, message phases flip.

## Phase 3: make it judgeable (Friday night to Saturday morning)

### 3a. Dashboard (owner: teammate; can start now against the schema)

Map of zones with hazard state, live signal feed, action log with
evidence and reasoning, approve and reject buttons, tripwires panel,
at-risk meters per town. Supabase realtime; pure frontend task.
Supervision is one third of the score.

### 3b. Full-loop rehearsal

Seeded end-to-end run. Tune the coordinator prompt against the
timeline's designed tests: the 16:35 gauge decision point, echo
cascades, the gauge going silent, the early UME request. The truth log
plus the kernel `payloads` table give the perception score for the
learning pitch.

## Phase 4: demo polish (Saturday)

- Demo script on the historic arc: our alert at about 17:00 against
  the real 20:11; close with the 224 deaths comparison.
- Level-2 voice citizen call live on stage (personas are ready).
- Degradation demo (kill the agent, reflexes hold) if watchdogs are in.
- Blackout scenario pack only if everything else is done.

## Cut lines, in order

1. Blackout pack.
2. Level-2 voice citizen (level 1 transcripts suffice).
3. Watchdogs.
4. Learning comparison.

Never cut: the real phone call, dashboard approve and reject,
tripwires, the before and after at-risk numbers.

## Parked: scale the data to the real catastrophe

Decision 2026-09-19: mayors for every town, realistic responder unit
counts, and demand scaling are parked until the base system is solid.
They belong to one bigger change: scale the scenario data toward the
real event (more entities, resources, messages, calls, news), keeping
scarcity pressure relative to demand.
