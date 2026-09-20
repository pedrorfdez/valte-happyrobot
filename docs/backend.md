# Backend architecture

Written as the implementation plan; the system described here is built
and deployed (Railway service `kernel`). Deviations are recorded in
`docs/decisions.md`.

One Python process, two strictly separated components:

- **Crisis kernel**: the product. State store, validation, reflex
  layer, watchdogs, event routing. It exists identically whether it is
  fed by a simulator or by reality.
- **Simulator**: fake reality. Generates signals, evolves hazards,
  applies action effects. In a real deployment it disappears, replaced
  by real feeds and real telephony.

The boundary rule: **the simulator talks to the kernel only through
the same public interfaces reality would use.** It POSTs signals like
a real gauge would and reads executed actions like reality would. No
shared internals, no imports from `kernel/` beyond the HTTP client
(plus one narrow, explicitly-marked ground-truth write path for
hazards). Pitch line this buys: unplug the simulator, plug in real
feeds, nothing else changes.

## Perception layer

Between raw reality and the kernel sits perception: one HappyRobot
ingest workflow per unstructured channel (call, social, news). Each
receives its channel's native payload (see the channel payload
schemas), filters noise, extracts claims, resolves location, and POSTs
a normalized signal to the kernel. Structured sources (sensors,
official bulletins; `ingest.mode: direct` on the entity) skip
perception and POST normalized signals straight to `POST /signals`, so
the reflex path never waits for an LLM. The simulator's `--truth` log
stores the ground-truth signals behind each payload; comparing them
with what perception extracted scores the ingest workflows (learning
bonus). The call channel contract (`call_record.schema.json`) is the
same for simulated transcripts, voice-agent citizens, and live demo
calls.

## Design principles

1. The agent (LLM in HappyRobot) is 5-30 s per deliberation and cannot
   be made fast. Fast behavior comes from taking the agent off the
   critical path: a deterministic **reflex layer** in the kernel fires
   in milliseconds, and the agent's job is to *program it* (tripwires)
   and to deliberate on what rules cannot decide.
2. The kernel does not trust the agent. Validation rejects invalid
   actions; **watchdogs** guarantee a deterministic response when the
   agent is silent; idempotency absorbs duplicate calls. The agent is
   an advisor with authority; the kernel owns the guarantees.
3. Degradation mode: with the agent fully down, tripwires + watchdogs
   + the human dashboard still form a working (dumber) crisis system.

## Stack

- Python 3.11+, FastAPI, uvicorn.
- psycopg 3 with a connection pool. Plain SQL, no ORM.
- Validation: the JSON Schema files in `schemas/` validated with the
  `jsonschema` package at the API boundary. Pydantic only for config.
- Simulator: asyncio background task in the same process for the
  hackathon (one deploy, one clock), but behind the HTTP boundary.
- Env and deps: `uv` (fallback: venv + pip).

## Layout

```
backend/
  kernel/                # THE PRODUCT
    main.py              # FastAPI app, lifespan starts dispatcher + watchdogs
    config.py            # env vars (pydantic-settings)
    db.py                # psycopg pool
    validation.py        # loads ../schemas/*.json
    routers/
      state.py           # GET /state, GET /zones
      entities.py        # GET/POST /entities, GET /entities/{id}
      signals.py         # POST /signals (world-facing ingress), GET /signals
      actions.py         # POST /actions (idempotent), PATCH /actions/{id},
                         # POST /actions/{id}/approve|reject
      situation.py       # GET/PUT /situation
      tripwires.py       # GET /tripwires (dashboard: standing orders)
    services/
      world.py           # state reads/writes, invariant checks
      verbs.py           # SYSTEM_VERBS: register_entity, update_entity,
                         #   set_tripwire, clear_tripwire, schedule_check
      lifecycle.py       # action state machine, approval gate
      reflexes.py        # tripwire evaluation, synchronous on signal insert
      watchdogs.py       # deadlines on critical events, deterministic escalation
      outbox.py          # immediate post-commit dispatch + retry backstop loop
      clock.py           # scenario time (kernel-owned; sim advances it)
  sim/                   # FAKE REALITY (deleted in a real deployment)
    engine.py            # tick loop; talks to kernel via HTTP client only
    dynamics.py          # hazard evolution along the zone graph
    timeline.py          # scripted events + noise generator
    effects.py           # applies executed actions to ground truth
  migrations/
    001_init.sql
  scripts/
    load_scenario.py     # scenarios/<id>/ -> DB
    replay.py            # re-run a stored run for the learning demo
  tests/
```

## Database (Supabase Postgres)

Typed columns for what code filters on; JSONB documents so the JSON
Schemas stay the source of truth.

Kernel tables:

- `zones(id text pk, doc jsonb)`
- `entities(id text pk, kind text, status text, provenance text, doc jsonb)`
- `signals(id text pk, t timestamptz, source text, zone text, confidence text, doc jsonb)`
- `actions(id text pk, t timestamptz, actor text, verb text, status text,
  idempotency_key text unique, doc jsonb)`
- `situation(id int pk default 1, doc jsonb, updated_at timestamptz)`
- `tripwires(id text pk, set_by text, status text, doc jsonb)`
  (doc: condition, then-actions, evidence; dashboard renders them as
  standing orders)
- `events(id bigserial pk, type text, payload jsonb, webhook text,
  status text, attempts int, deadline timestamptz, created_at, sent_at)`
  (outbox and watchdog registry in one: `deadline` is the watchdog)

Simulator table (ground truth, agent has no endpoint for it):

- `hazards(id text pk, zone text, severity int, trend text, doc jsonb)`

Dashboard subscribes via Supabase realtime to `actions`, `signals`,
`entities`, `situation`, `tripwires`. It may also read `hazards` to
render ground truth next to the agent's belief.

## Kernel endpoints

World-facing ingress (simulator today, real feeds tomorrow):

- `POST /signals`: validate against `signal.schema.json`, compute
  confidence (corroboration rule), insert, then synchronously:
  1. evaluate tripwires (`reflexes.py`, milliseconds);
  2. enqueue + immediately dispatch the webhook event;
  3. if confidence high: register a watchdog deadline.

Agent-facing (HappyRobot HTTP tools, bearer `WORLD_API_TOKEN`):

- `GET /state`: zones + entities + situation + active tripwires in one
  prompt-sized response.
- `GET /entities`, `GET /entities/{id}`.
- `POST /actions` with `Idempotency-Key` header: schema validation,
  then invariants (world verb in actor capabilities, system verb in
  SYSTEM_VERBS with per-verb params validation, target_zones inside
  jurisdiction, evidence refs exist). Actor activation cost `high`
  forces `pending_approval`. System verbs execute inline.
- `PATCH /actions/{id}`: outcome (`in_progress|executed|failed`,
  `real_interaction`). `failed` emits `action_failed` event.
- `GET /signals?since&zone`, `GET /situation`, `PUT /situation`.

System verbs (closed set, kernel-implemented):

- `register_entity`, `update_entity`: as in the action schema.
- `set_tripwire`: install a standing rule (condition on incoming
  signals -> immediate kernel-executed actions). The agent's main
  self-programming mechanism; requires evidence like any action.
- `clear_tripwire`: retire a rule.
- `schedule_check`: timer event to the agent (reminders, reassessments).

Human-facing:

- `POST /actions/{id}/approve|reject`: the supervision gate. Approval
  cancels the timeout watchdog and emits `action_approved`.

Operator:

- `POST /sim/start|pause|reset`, `GET /sim/clock`: thin proxies that
  control the simulator task; kept under the kernel app for one deploy
  but logically simulator controls.

## Event flow and latency budget

1. Signal ingress -> tripwire evaluation: **~50 ms** (synchronous SQL
   + rule match; no LLM).
2. Signal ingress -> HappyRobot webhook: **<1 s**. Outbox row is
   dispatched immediately after commit; a 2 s poll loop is only the
   retry backstop (backoff, 5 attempts, then `dead`, visible on the
   dashboard).
3. Agent deliberation: 5-30 s, off the critical path by design.
4. Watchdog ceiling: a high-confidence event with no referencing
   action within `WATCHDOG_S` (default 60 s scenario-scaled) triggers
   deterministic escalation (default tripwire + human notification).
   Worst-case inaction is bounded regardless of agent health.

Webhook URLs from env: `HR_WEBHOOK_INGEST`, `HR_WEBHOOK_COORDINATOR`.
Point them at webhook.site until the workflows exist.

## Clock and simulator

The kernel owns the clock value (`clock.py`); the simulator advances
it: `scenario_t = start + (wall - t0) * compression`. Sim tick (2 s
wall): evolve hazards along `downstream_of` with `propagation_delay_min`
(dynamics.py), release due timeline events as `POST /signals`, apply
executed actions to ground truth (effects.py: close_road reduces
vehicle exposure, warnings reduce at_risk_pct), fire activation-delay
completions (`responder_operational`).

## Milestones (build in this order)

1. **Read-only kernel.** Scaffold, migration, `load_scenario.py`,
   `GET /state|/entities|/zones`. Deployable against the DANA pack.
2. **Actions.** `POST /actions` (validation, idempotency, approval
   gate, system verbs incl. set_tripwire/clear_tripwire),
   `PATCH /actions/{id}`.
3. **Ingress + outbox + reflexes.** `POST /signals` with confidence
   rule, tripwire evaluation, immediate webhook dispatch to
   webhook.site. **This completes the contract with the workflow team.**
4. **Simulator.** Clock, tick engine, dynamics, timeline player, noise
   generator, effects. Needs `timeline.json` (not written yet; can be
   authored in parallel with 1-3).
5. **Watchdogs and timers.** Deadlines, approval timeouts, activation
   delays, escalation events. Degradation demo becomes possible here.
6. **Deploy.** Railway or Fly (EU region), health endpoint, seed on
   boot. cloudflared tunnel only for local development.

Cut line if time runs short: watchdogs (5) degrade gracefully — the
demo works without them; tripwires (in 2-3) do not get cut, they are
the fast path and part of the pitch.

## Auth

One static bearer token (`WORLD_API_TOKEN`) on every non-GET kernel
route, checked by a FastAPI dependency. HappyRobot tools send it as a
header. The simulator uses the same token; approve/reject from the
dashboard too.

## Testing

- `pytest` + httpx: action validation matrix (bad verb, out of
  jurisdiction, missing evidence, high cost forces approval, duplicate
  idempotency key).
- Reflex test: insert signal matching a tripwire, assert kernel action
  exists within the same request.
- End-to-end script: load pack, start sim at high compression, assert
  signals hit the outbox and an executed action mutates ground truth.
