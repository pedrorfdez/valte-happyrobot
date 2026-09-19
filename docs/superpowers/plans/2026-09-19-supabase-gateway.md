# Supabase State Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the smallest Supabase-backed authority for run state, idempotent commands, observable snapshots, and allowlisted HappyRobot dispatches required by the DANA demo.

**Architecture:** Supabase owns all persistent state. A single `apply_command(jsonb)` RPC locks one run, verifies immutable pack identity and `expected_state_version`, applies one supported mutation, appends its events/outbox entries, stores the command result, and advances `state_version` once. Three thin, dependency-free Azure Functions expose the frozen HTTP interface; they use Supabase REST/RPC with the service-role key and never duplicate domain state in memory.

**Tech Stack:** PostgreSQL/Supabase SQL, Supabase PostgREST RPC, Azure Static Web Apps managed Functions v3 file-based model, Node.js ESM `.mjs`, built-in `fetch`

---

## Delivery constraints

- This is a demo increment: no TDD, test framework, ORM, generated client, Redis, Kafka, Docker, background daemon, or additional backend.
- Verification is by the smoke commands in the final task only.
- Do not commit. The coordinator owns integration and commits.
- Do not modify `package.json`, `package-lock.json`, `.env.example`, `schemas/v2/**`, `scripts/**`, scenario packs, HappyRobot artifacts, dashboard files, or documentation outside this plan.
- Use only the frozen endpoints: `POST /api/commands`, `GET /api/snapshot?run_id=<id>`, and `POST /api/event-router`.
- Use the flat command envelope frozen by the parallel-delivery design. Do not substitute the older nested `pack` or object-valued `actor` shape from the broader design document.
- `schemas/v2/**` remains authoritative for Signal, Incident, Plan, Action, and Outcome. Do not create database-specific alternative domain types; persist the validated v2 documents as `jsonb` projections plus searchable identity columns.
- Managed SWA packages `api/` as the Function App root. Runtime code therefore must not import `../../schemas/v2/**`; validate the frozen command envelope and v2 identity at the Gateway, while HappyRobot output schemas and `npm run contracts:check` perform full contract validation.
- Advanced reservations, backpressure lanes, evidence retraction, merge/split execution, HumanDirective, terminal fence completion, late callbacks, and postmortem are explicitly outside this increment.
- Never expose `SUPABASE_SERVICE_ROLE_KEY` to browser code or persist secrets in SQL, seed data, logs, events, or outbox payloads.

## Frozen interfaces

Every command sent to `POST /api/commands` has exactly this transport shape:

```json
{
  "command_id": "cmd-unique",
  "run_id": "run-id",
  "pack_id": "pack-id",
  "pack_version": "1.0.0",
  "pack_digest": "64-lowercase-hex-characters",
  "expected_state_version": 3,
  "actor": "scenario-controller",
  "command_type": "receive_source_input",
  "payload": {},
  "causation_id": null
}
```

Allowed `actor` values are `scenario-controller`, `happyrobot`, and `operator`. Allowed `command_type` values are `receive_source_input`, `upsert_signal`, `replace_plan`, `approve_action`, `reject_action`, `record_outcome`, `advance_clock`, `pause_run`, `resume_run`, and `abort_run`.

An accepted response is:

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

Errors use `{ "ok": false, "error": "stable_code", "message": "human readable detail" }`. Map `version_conflict`, `idempotency_mismatch`, and `pack_context_mismatch` to HTTP 409; malformed input and invalid transitions to HTTP 400; unknown runs to HTTP 404. Replaying an identical `(run_id, command_id)` returns the persisted response with `replayed: true`, the same `run_id`, `state_version`, `result`, and `events`, and no new state, event, or outbox row.

## File map

| Path | Change | Responsibility |
| --- | --- | --- |
| `supabase/migrations/202609190001_crisis_core.sql` | Create | Minimal tables, invariants, `apply_command`, `get_run_snapshot`, `claim_outbox`, and `finish_outbox` RPCs |
| `supabase/seed.sql` | Create | Re-runnable DANA and wildfire demo runs plus their isolated resource ledgers |
| `api/host.json` | Create | Managed SWA Functions v3 host declaration; no Function-local package or dependency installation |
| `api/_shared/supabase.mjs` | Create | Server-only Supabase REST/RPC helper and JSON HTTP response helper |
| `api/commands/function.json` | Create | Azure route metadata for `POST /api/commands` |
| `api/commands/index.mjs` | Create | Transport validation, v2 identity validation, RPC delegation, and error/status mapping |
| `api/snapshot/function.json` | Create | Azure route metadata for `GET /api/snapshot` |
| `api/snapshot/index.mjs` | Create | Read-only snapshot RPC adapter |
| `api/event-router/function.json` | Create | Azure route metadata for `POST /api/event-router` |
| `api/event-router/index.mjs` | Create | Claim up to ten outbox rows, map allowlisted destinations to frozen workflow-ID settings, dispatch, and acknowledge each lease |

The coordinator provisions these Router-only server settings in addition to the shared variables; this front does not edit `.env.example`:

```text
HAPPYROBOT_INTAKE_WORKFLOW_ID
HAPPYROBOT_COMMAND_WORKFLOW_ID
HAPPYROBOT_COORDINATION_WORKFLOW_ID
```

### Task 1: Create the minimal persistent model

**Files:**

- Create: `supabase/migrations/202609190001_crisis_core.sql`

- [ ] **Step 1: Create the schema and tables**

Start the migration with `pgcrypto` and these exact tables. Keep the domain payload in `document jsonb`; the adjacent columns exist only for keys, filtering, and invariant checks.

```sql
create extension if not exists pgcrypto;

create table if not exists scenario_runs (
  run_id text primary key,
  pack_id text not null,
  pack_version text not null,
  pack_digest text not null check (pack_digest ~ '^[a-f0-9]{64}$'),
  status text not null default 'ready'
    check (status in ('ready', 'running', 'paused', 'completed', 'aborted')),
  scenario_now timestamptz not null,
  state_version bigint not null default 0 check (state_version >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (run_id, pack_id, pack_version, pack_digest)
);

create table if not exists source_inputs (
  run_id text not null references scenario_runs(run_id),
  source_input_id text not null,
  scenario_at timestamptz not null,
  modality text not null,
  content text not null,
  payload jsonb not null,
  received_at timestamptz not null default now(),
  primary key (run_id, source_input_id)
);

create table if not exists signals (
  run_id text not null references scenario_runs(run_id),
  signal_id text not null,
  revision integer not null check (revision >= 1),
  status text not null,
  document jsonb not null,
  primary key (run_id, signal_id, revision)
);

create table if not exists incidents (
  run_id text not null references scenario_runs(run_id),
  incident_id text not null,
  state text not null,
  canonical_incident_id text,
  document jsonb not null,
  primary key (run_id, incident_id)
);

create table if not exists plans (
  run_id text not null references scenario_runs(run_id),
  plan_id text not null,
  plan_version integer not null check (plan_version >= 1),
  status text not null,
  document jsonb not null,
  primary key (run_id, plan_id),
  unique (run_id, plan_version)
);

create unique index if not exists one_active_plan_per_run
  on plans (run_id) where status = 'active';

create table if not exists actions (
  run_id text not null references scenario_runs(run_id),
  action_id text not null,
  plan_id text not null,
  incident_id text not null,
  status text not null,
  document jsonb not null,
  primary key (run_id, action_id)
);

create table if not exists outcomes (
  run_id text not null references scenario_runs(run_id),
  outcome_id text not null,
  action_id text not null,
  document jsonb not null,
  created_at timestamptz not null default now(),
  primary key (run_id, outcome_id)
);

create table if not exists resources (
  run_id text not null references scenario_runs(run_id),
  resource_id text not null,
  resource_mode text not null check (resource_mode in ('reusable', 'consumable')),
  capacity numeric not null check (capacity >= 0),
  available numeric not null check (available >= 0 and available <= capacity),
  document jsonb not null,
  primary key (run_id, resource_id)
);

create table if not exists commands (
  run_id text not null references scenario_runs(run_id),
  command_id text not null,
  fingerprint text not null,
  request jsonb not null,
  response jsonb not null,
  resulting_state_version bigint not null,
  created_at timestamptz not null default now(),
  primary key (run_id, command_id)
);

create table if not exists events (
  event_id bigint generated always as identity primary key,
  run_id text not null references scenario_runs(run_id),
  state_version bigint not null,
  event_type text not null,
  causation_id text,
  payload jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists outbox (
  outbox_id uuid primary key default gen_random_uuid(),
  event_id bigint not null unique references events(event_id),
  run_id text not null references scenario_runs(run_id),
  destination text not null,
  dispatch_id uuid not null default gen_random_uuid(),
  status text not null default 'pending'
    check (status in ('pending', 'claimed', 'dispatched', 'failed')),
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  lease_until timestamptz,
  payload jsonb not null,
  last_error text,
  dispatched_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists outbox_claimable
  on outbox (status, available_at, created_at);

grant select on table events to anon;

do $$
begin
  if exists (
    select 1 from pg_publication where pubname = 'supabase_realtime'
  ) and not exists (
    select 1
    from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'events'
  ) then
    alter publication supabase_realtime add table events;
  end if;
end;
$$;
```

`events` is the only table exposed to the demo browser. Supabase Realtime provides change notifications; the dashboard then refetches `GET /api/snapshot`. It never reads the remaining tables or receives `SUPABASE_SERVICE_ROLE_KEY`.

- [ ] **Step 2: Add one event helper with the frozen allowlist**

Add `append_crisis_event`. A `null` destination means the event remains observable but does not create outbox work.

```sql
create or replace function append_crisis_event(
  p_run_id text,
  p_state_version bigint,
  p_event_type text,
  p_causation_id text,
  p_payload jsonb,
  p_destination text default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_event_id bigint;
  v_event jsonb;
begin
  insert into events (run_id, state_version, event_type, causation_id, payload)
  values (p_run_id, p_state_version, p_event_type, p_causation_id, p_payload)
  returning event_id into v_event_id;

  v_event := jsonb_build_object(
    'event_id', v_event_id,
    'run_id', p_run_id,
    'state_version', p_state_version,
    'event_type', p_event_type,
    'causation_id', p_causation_id,
    'payload', p_payload
  );

  if p_destination is not null then
    insert into outbox (event_id, run_id, destination, payload)
    values (v_event_id, p_run_id, p_destination, v_event);
  end if;

  return v_event;
end;
$$;
```

Use only this routing table inside `apply_command`:

| Event | Destination |
| --- | --- |
| `source_input.received` | `crisis-intake` |
| `signal.created`, `signal.revised` | `crisis-command` |
| `action.approved` | `crisis-response-coordination` |
| `outcome.recorded` | `crisis-command` |

All other minimal events (`plan.replaced`, `action.rejected`, `clock.advanced`, `run.paused`, `run.resumed`, and `run.aborted`) use a null destination so the Router cannot create workflow loops.

The two direct execution handoffs are self-contained. `source_input.received.payload` carries `signal_identity`, the complete normalized transport input, run/pack identity, resulting `state_version`, timestamps, correlation/causation, and `zone_catalog`, so Intake never reads a table or invents IDs. `action.approved.payload` carries the complete updated Action v2 plus run/pack identity and resulting version, so Coordination does not need a race-prone follow-up read. Command is different by design: on `signal.created`, `signal.revised`, or `outcome.recorded`, it uses the event as a trigger and reads the authoritative observable state through `GET /api/snapshot?run_id=...`.

- [ ] **Step 3: Add the atomic `apply_command` RPC**

Implement one `security definer` PL/pgSQL function with this exact processing order:

```sql
create or replace function apply_command(p_command jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_run scenario_runs%rowtype;
  v_existing commands%rowtype;
  v_fingerprint text := encode(digest(p_command::text, 'sha256'), 'hex');
  v_type text := p_command->>'command_type';
  v_payload jsonb := coalesce(p_command->'payload', '{}'::jsonb);
  v_next_version bigint;
  v_events jsonb := '[]'::jsonb;
  v_event jsonb;
  v_result jsonb := '{}'::jsonb;
  v_response jsonb;
  v_record jsonb;
begin
  if not (p_command ?& array[
    'command_id', 'run_id', 'pack_id', 'pack_version', 'pack_digest',
    'expected_state_version', 'actor', 'command_type', 'payload', 'causation_id'
  ]) then
    return jsonb_build_object('ok', false, 'error', 'invalid_command', 'message', 'missing command envelope field');
  end if;

  if p_command->>'actor' not in ('scenario-controller', 'happyrobot', 'operator') then
    return jsonb_build_object('ok', false, 'error', 'invalid_actor', 'message', 'actor is not allowlisted');
  end if;

  if v_type not in (
    'receive_source_input', 'upsert_signal', 'replace_plan',
    'approve_action', 'reject_action', 'record_outcome',
    'advance_clock', 'pause_run', 'resume_run', 'abort_run'
  ) then
    return jsonb_build_object('ok', false, 'error', 'unsupported_command', 'message', v_type);
  end if;

  select * into v_run
  from scenario_runs
  where run_id = p_command->>'run_id'
  for update;

  if not found then
    return jsonb_build_object('ok', false, 'error', 'run_not_found', 'message', p_command->>'run_id');
  end if;

  select * into v_existing
  from commands
  where run_id = v_run.run_id and command_id = p_command->>'command_id';

  if found then
    if v_existing.fingerprint = v_fingerprint then
      return jsonb_set(v_existing.response, '{replayed}', 'true'::jsonb, true);
    end if;
    return jsonb_build_object('ok', false, 'error', 'idempotency_mismatch', 'message', 'command_id already used with different content');
  end if;

  if v_run.pack_id <> p_command->>'pack_id'
    or v_run.pack_version <> p_command->>'pack_version'
    or v_run.pack_digest <> p_command->>'pack_digest' then
    return jsonb_build_object('ok', false, 'error', 'pack_context_mismatch', 'message', 'command pack identity differs from run snapshot');
  end if;

  if v_run.state_version <> (p_command->>'expected_state_version')::bigint then
    return jsonb_build_object(
      'ok', false,
      'error', 'version_conflict',
      'message', 'expected_state_version is stale',
      'current_state_version', v_run.state_version
    );
  end if;

  v_next_version := v_run.state_version + 1;

  case v_type
    when 'receive_source_input' then
      if not (v_payload ?& array[
        'signal_identity', 'source_input', 'scenario_at', 'received_at',
        'correlation_id', 'zone_catalog'
      ]) or not ((v_payload->'source_input') ?& array[
        'source_input_id', 'modality', 'content', 'reporter_id',
        'origin_reference', 'declared_location'
      ]) or not ((v_payload->'signal_identity') ?& array['signal_id', 'revision'])
        or jsonb_typeof(v_payload->'zone_catalog') <> 'array' then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'receive_source_input fields are incomplete');
      end if;
      insert into source_inputs (
        run_id, source_input_id, scenario_at, modality, content, payload
      ) values (
        v_run.run_id,
        (v_payload->'source_input')->>'source_input_id',
        (v_payload->>'scenario_at')::timestamptz,
        (v_payload->'source_input')->>'modality',
        (v_payload->'source_input')->>'content',
        v_payload
      );
      v_event := append_crisis_event(
        v_run.run_id, v_next_version, 'source_input.received',
        p_command->>'causation_id',
        jsonb_build_object(
          'signal_identity', v_payload->'signal_identity',
          'source_input', v_payload->'source_input',
          'run_id', v_run.run_id,
          'pack_id', v_run.pack_id,
          'pack_version', v_run.pack_version,
          'pack_digest', v_run.pack_digest,
          'state_version', v_next_version,
          'scenario_at', v_payload->>'scenario_at',
          'received_at', v_payload->>'received_at',
          'correlation_id', v_payload->>'correlation_id',
          'causation_id', p_command->>'causation_id',
          'zone_catalog', v_payload->'zone_catalog'
        ),
        'crisis-intake'
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object(
        'source_input_id', (v_payload->'source_input')->>'source_input_id',
        'signal_id', (v_payload->'signal_identity')->>'signal_id',
        'revision', ((v_payload->'signal_identity')->>'revision')::integer
      );

    when 'upsert_signal' then
      v_record := v_payload->'signal';
      if v_record is null then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'payload.signal is required');
      end if;
      insert into signals (run_id, signal_id, revision, status, document)
      values (
        v_run.run_id,
        v_record->>'signal_id',
        (v_record->>'revision')::integer,
        v_record->>'status',
        v_record
      );
      v_event := append_crisis_event(
        v_run.run_id, v_next_version,
        case when (v_record->>'revision')::integer = 1 then 'signal.created' else 'signal.revised' end,
        p_command->>'causation_id',
        jsonb_build_object('signal_id', v_record->>'signal_id', 'revision', (v_record->>'revision')::integer),
        'crisis-command'
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('signal_id', v_record->>'signal_id', 'revision', (v_record->>'revision')::integer);

    when 'replace_plan' then
      if jsonb_typeof(v_payload->'incidents') <> 'array'
        or jsonb_typeof(v_payload->'actions') <> 'array'
        or v_payload->'plan' is null then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'replace_plan requires incidents, plan, and actions');
      end if;

      for v_record in select value from jsonb_array_elements(v_payload->'incidents') loop
        insert into incidents (run_id, incident_id, state, canonical_incident_id, document)
        values (
          v_run.run_id,
          v_record->>'incident_id',
          v_record->>'state',
          v_record->>'canonical_incident_id',
          v_record
        )
        on conflict (run_id, incident_id) do update set
          state = excluded.state,
          canonical_incident_id = excluded.canonical_incident_id,
          document = excluded.document;
      end loop;

      update plans
      set status = 'superseded', document = jsonb_set(document, '{status}', '"superseded"')
      where run_id = v_run.run_id and status = 'active';

      v_record := v_payload->'plan';
      insert into plans (run_id, plan_id, plan_version, status, document)
      values (
        v_run.run_id,
        v_record->>'plan_id',
        (v_record->>'plan_version')::integer,
        v_record->>'status',
        v_record
      );

      for v_record in select value from jsonb_array_elements(v_payload->'actions') loop
        insert into actions (run_id, action_id, plan_id, incident_id, status, document)
        values (
          v_run.run_id,
          v_record->>'action_id',
          v_record->>'plan_id',
          v_record->>'incident_id',
          v_record->>'status',
          v_record
        );
      end loop;

      v_event := append_crisis_event(
        v_run.run_id, v_next_version, 'plan.replaced',
        p_command->>'causation_id',
        jsonb_build_object('plan_id', (v_payload->'plan')->>'plan_id'),
        null
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('plan_id', (v_payload->'plan')->>'plan_id');

    when 'approve_action' then
      update actions
      set status = 'approved', document = jsonb_set(document, '{status}', '"approved"')
      where run_id = v_run.run_id
        and action_id = v_payload->>'action_id'
        and status in ('proposed', 'pending_approval')
      returning document into v_record;
      if not found then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'action cannot be approved');
      end if;
      v_event := append_crisis_event(
        v_run.run_id, v_next_version, 'action.approved',
        p_command->>'causation_id',
        jsonb_build_object(
          'action', v_record,
          'run_id', v_run.run_id,
          'pack_id', v_run.pack_id,
          'pack_version', v_run.pack_version,
          'pack_digest', v_run.pack_digest,
          'state_version', v_next_version,
          'correlation_id', v_record->>'correlation_id',
          'causation_id', p_command->>'causation_id'
        ),
        'crisis-response-coordination'
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('action_id', v_payload->>'action_id', 'status', 'approved');

    when 'reject_action' then
      update actions
      set status = 'rejected', document = jsonb_set(document, '{status}', '"rejected"')
      where run_id = v_run.run_id
        and action_id = v_payload->>'action_id'
        and status in ('proposed', 'pending_approval');
      if not found then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'action cannot be rejected');
      end if;
      v_event := append_crisis_event(
        v_run.run_id, v_next_version, 'action.rejected',
        p_command->>'causation_id',
        jsonb_build_object('action_id', v_payload->>'action_id'),
        null
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('action_id', v_payload->>'action_id', 'status', 'rejected');

    when 'record_outcome' then
      v_record := v_payload->'outcome';
      if v_record is null then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'payload.outcome is required');
      end if;
      if not exists (
        select 1 from actions
        where run_id = v_run.run_id and action_id = v_record->>'action_id'
      ) then
        return jsonb_build_object('ok', false, 'error', 'action_not_found', 'message', v_record->>'action_id');
      end if;
      insert into outcomes (run_id, outcome_id, action_id, document)
      values (v_run.run_id, v_record->>'outcome_id', v_record->>'action_id', v_record);
      v_event := append_crisis_event(
        v_run.run_id, v_next_version, 'outcome.recorded',
        p_command->>'causation_id',
        jsonb_build_object('outcome_id', v_record->>'outcome_id', 'action_id', v_record->>'action_id'),
        'crisis-command'
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('outcome_id', v_record->>'outcome_id');

    when 'advance_clock' then
      if (v_payload->>'scenario_at')::timestamptz < v_run.scenario_now then
        return jsonb_build_object('ok', false, 'error', 'clock_cannot_move_backwards', 'message', v_payload->>'scenario_at');
      end if;
      update scenario_runs
      set scenario_now = (v_payload->>'scenario_at')::timestamptz
      where run_id = v_run.run_id;
      v_event := append_crisis_event(
        v_run.run_id, v_next_version, 'clock.advanced',
        p_command->>'causation_id',
        jsonb_build_object('scenario_at', v_payload->>'scenario_at'), null
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('scenario_at', v_payload->>'scenario_at');

    when 'pause_run' then
      if v_run.status <> 'running' then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'only a running run can pause');
      end if;
      update scenario_runs set status = 'paused' where run_id = v_run.run_id;
      v_event := append_crisis_event(v_run.run_id, v_next_version, 'run.paused', p_command->>'causation_id', '{}'::jsonb, null);
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('status', 'paused');

    when 'resume_run' then
      if v_run.status not in ('ready', 'paused') then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'only a ready or paused run can resume');
      end if;
      update scenario_runs set status = 'running' where run_id = v_run.run_id;
      v_event := append_crisis_event(v_run.run_id, v_next_version, 'run.resumed', p_command->>'causation_id', '{}'::jsonb, null);
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('status', 'running');

    when 'abort_run' then
      if v_run.status in ('completed', 'aborted') then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'run is already terminal');
      end if;
      update scenario_runs set status = 'aborted' where run_id = v_run.run_id;
      v_event := append_crisis_event(v_run.run_id, v_next_version, 'run.aborted', p_command->>'causation_id', v_payload, null);
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('status', 'aborted');
  end case;

  update scenario_runs
  set state_version = v_next_version, updated_at = now()
  where run_id = v_run.run_id;

  v_response := jsonb_build_object(
    'ok', true,
    'command_id', p_command->>'command_id',
    'run_id', v_run.run_id,
    'state_version', v_next_version,
    'replayed', false,
    'result', v_result,
    'events', v_events
  );

  insert into commands (
    run_id, command_id, fingerprint, request, response, resulting_state_version
  ) values (
    v_run.run_id, p_command->>'command_id', v_fingerprint,
    p_command, v_response, v_next_version
  );

  return v_response;
exception
  when unique_violation then
    raise exception using errcode = '23505', message = 'domain identity already exists';
end;
$$;
```

Do not catch and turn database exceptions into accepted responses inside the RPC. An exception must roll back domain rows, events, outbox work, command receipt, and `state_version` together.

- [ ] **Step 4: Add snapshot and outbox lease RPCs**

Append these functions to the same migration:

```sql
create or replace function get_run_snapshot(p_run_id text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select jsonb_build_object(
    'run', to_jsonb(r),
    'signals', coalesce((select jsonb_agg(document order by signal_id, revision) from signals where run_id = r.run_id), '[]'::jsonb),
    'incidents', coalesce((select jsonb_agg(document order by incident_id) from incidents where run_id = r.run_id and state not in ('merged', 'split')), '[]'::jsonb),
    'plan', (select document from plans where run_id = r.run_id and status = 'active' limit 1),
    'actions', coalesce((select jsonb_agg(document order by action_id) from actions where run_id = r.run_id), '[]'::jsonb),
    'outcomes', coalesce((select jsonb_agg(document order by created_at) from outcomes where run_id = r.run_id), '[]'::jsonb),
    'resources', coalesce((select jsonb_agg(document order by resource_id) from resources where run_id = r.run_id), '[]'::jsonb),
    'events', coalesce((select jsonb_agg(to_jsonb(e) order by event_id) from events e where run_id = r.run_id), '[]'::jsonb),
    'outbox', coalesce((
      select jsonb_agg(jsonb_build_object(
        'outbox_id', outbox_id,
        'event_id', event_id,
        'destination', destination,
        'dispatch_id', dispatch_id,
        'status', status,
        'attempts', attempts,
        'available_at', available_at,
        'last_error', last_error
      ) order by created_at)
      from outbox where run_id = r.run_id
    ), '[]'::jsonb)
  )
  from scenario_runs r
  where r.run_id = p_run_id;
$$;

create or replace function claim_outbox(p_limit integer default 10)
returns setof outbox
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  with candidates as (
    select o.outbox_id
    from outbox o
    where o.available_at <= now()
      and (
        o.status = 'pending'
        or (o.status = 'claimed' and o.lease_until < now())
      )
    order by o.created_at, o.outbox_id
    for update skip locked
    limit greatest(1, least(coalesce(p_limit, 10), 10))
  )
  update outbox o
  set status = 'claimed',
      attempts = o.attempts + 1,
      lease_until = now() + interval '30 seconds',
      last_error = null
  from candidates c
  where o.outbox_id = c.outbox_id
  returning o.*;
end;
$$;

create or replace function finish_outbox(
  p_outbox_id uuid,
  p_dispatch_id uuid,
  p_succeeded boolean,
  p_error text default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row outbox%rowtype;
begin
  update outbox
  set status = case
        when p_succeeded then 'dispatched'
        when attempts >= 3 then 'failed'
        else 'pending'
      end,
      available_at = case when p_succeeded then available_at else now() + interval '5 seconds' end,
      lease_until = null,
      dispatched_at = case when p_succeeded then now() else null end,
      last_error = case when p_succeeded then null else left(coalesce(p_error, 'dispatch failed'), 1000) end
  where outbox_id = p_outbox_id
    and dispatch_id = p_dispatch_id
    and status = 'claimed'
  returning * into v_row;

  if not found then
    return jsonb_build_object('error', 'outbox_lease_not_found');
  end if;

  return jsonb_build_object(
    'outbox_id', v_row.outbox_id,
    'status', v_row.status,
    'attempts', v_row.attempts
  );
end;
$$;

revoke all on function apply_command(jsonb) from public;
revoke all on function get_run_snapshot(text) from public;
revoke all on function claim_outbox(integer) from public;
revoke all on function finish_outbox(uuid, uuid, boolean, text) from public;
grant execute on function apply_command(jsonb) to service_role;
grant execute on function get_run_snapshot(text) to service_role;
grant execute on function claim_outbox(integer) to service_role;
grant execute on function finish_outbox(uuid, uuid, boolean, text) to service_role;
```

- [ ] **Step 5: Check the migration without applying it**

Run:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction --file supabase/migrations/202609190001_crisis_core.sql
```

Expected: `CREATE TABLE`, `CREATE FUNCTION`, `REVOKE`, and `GRANT` messages with no `ERROR`. This command does apply the idempotent migration; `--single-transaction` guarantees all-or-nothing behavior.

### Task 2: Seed two isolated demo runs

**Files:**

- Create: `supabase/seed.sql`

- [ ] **Step 1: Add deterministic, re-runnable seed data**

Create both runs because the later integration gate executes DANA and then wildfire without direct table writes. The digests deliberately match the Scenario Controller plan.

```sql
begin;

insert into scenario_runs (
  run_id, pack_id, pack_version, pack_digest, status, scenario_now, state_version
) values
  (
    'run-dana-demo', 'dana-demo', '1.0.0',
    repeat('c', 64), 'ready', '2026-09-19T10:00:00Z', 0
  ),
  (
    'run-wildfire-demo', 'wildfire-demo', '1.0.0',
    repeat('d', 64), 'ready', '2026-09-19T12:00:00Z', 0
  )
on conflict (run_id) do update set
  pack_id = excluded.pack_id,
  pack_version = excluded.pack_version,
  pack_digest = excluded.pack_digest,
  status = 'ready',
  scenario_now = excluded.scenario_now,
  state_version = 0,
  updated_at = now();

delete from outbox where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from events where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from commands where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from outcomes where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from actions where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from plans where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from incidents where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from signals where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from source_inputs where run_id in ('run-dana-demo', 'run-wildfire-demo');
delete from resources where run_id in ('run-dana-demo', 'run-wildfire-demo');

insert into resources (run_id, resource_id, resource_mode, capacity, available, document)
values
  (
    'run-dana-demo', 'water-rescue-team-1', 'reusable', 1, 1,
    '{"resource_id":"water-rescue-team-1","resource_mode":"reusable","capacity":1,"available":1,"capabilities":["water_rescue"],"zone_id":"catarroja-health-centre"}'::jsonb
  ),
  (
    'run-wildfire-demo', 'wildfire-brigade-1', 'reusable', 1, 1,
    '{"resource_id":"wildfire-brigade-1","resource_mode":"reusable","capacity":1,"available":1,"capabilities":["wildfire_response"],"zone_id":"corredor-sur"}'::jsonb
  );

commit;
```

The seed is intentionally destructive only for the two named demo runs. Never broaden the `where run_id in (...)` target.

- [ ] **Step 2: Apply and inspect the seed**

Run:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --file supabase/seed.sql
psql "$DATABASE_URL" -Atc "select run_id || '|' || pack_id || '|' || state_version from scenario_runs where run_id in ('run-dana-demo','run-wildfire-demo') order by run_id"
```

Expected:

```text
run-dana-demo|dana-demo|0
run-wildfire-demo|wildfire-demo|0
```

### Task 3: Configure managed Functions and add the server-only Supabase adapter

**Files:**

- Create: `api/host.json`
- Create: `api/_shared/supabase.mjs`

- [ ] **Step 1: Declare the dependency-free Functions v3 host**

```json
{
  "version": "2.0",
  "logging": {
    "applicationInsights": {
      "samplingSettings": {
        "isEnabled": true,
        "excludedTypes": "Request"
      }
    }
  }
}
```

Do not add `api/package.json` or `@azure/functions`. Each route uses `function.json` plus an ESM `.mjs` entry point and only Node built-ins.

- [ ] **Step 2: Implement the shared REST/RPC helper**

```javascript
const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};

export const jsonResponse = (status, body) => ({
  status,
  headers: { "content-type": "application/json; charset=utf-8" },
  body: JSON.stringify(body)
});

export async function supabaseRequest(path, { method = "GET", body } = {}) {
  const baseUrl = required("SUPABASE_URL").replace(/\/$/, "");
  const serviceKey = required("SUPABASE_SERVICE_ROLE_KEY");
  const response = await fetch(`${baseUrl}/rest/v1/${path}`, {
    method,
    headers: {
      apikey: serviceKey,
      authorization: `Bearer ${serviceKey}`,
      "content-type": "application/json",
      accept: "application/json"
    },
    body: body === undefined ? undefined : JSON.stringify(body)
  });

  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text };
    }
  }

  if (!response.ok) {
    const error = new Error(data?.message ?? `Supabase request failed with ${response.status}`);
    error.status = response.status;
    error.details = data;
    throw error;
  }

  return data;
}

export const callRpc = (name, args) =>
  supabaseRequest(`rpc/${name}`, { method: "POST", body: args });
```

- [ ] **Step 3: Run the syntax and host checks**

Run:

```bash
node --check api/_shared/supabase.mjs
jq -e '.version == "2.0"' api/host.json
```

Expected: both commands exit 0; the syntax check prints nothing and `jq` prints `true`.

### Task 4: Expose `POST /api/commands`

**Files:**

- Create: `api/commands/function.json`
- Create: `api/commands/index.mjs`

- [ ] **Step 1: Add the Azure Function route**

```json
{
  "scriptFile": "index.mjs",
  "bindings": [
    {
      "authLevel": "anonymous",
      "type": "httpTrigger",
      "direction": "in",
      "name": "req",
      "methods": ["post"],
      "route": "commands"
    },
    {
      "type": "http",
      "direction": "out",
      "name": "res"
    }
  ]
}
```

- [ ] **Step 2: Implement transport and v2 identity validation**

Keep runtime validation deliberately narrow: validate the frozen command envelope, require v2 records where relevant, and reject any record whose run/pack identity differs from the command. Do not copy schemas into `api/` and do not import files outside the managed Function App root.

```javascript
import { callRpc, jsonResponse } from "../_shared/supabase.mjs";

const actors = new Set(["scenario-controller", "happyrobot", "operator"]);
const commandTypes = new Set([
  "receive_source_input", "upsert_signal", "replace_plan",
  "approve_action", "reject_action", "record_outcome",
  "advance_clock", "pause_run", "resume_run", "abort_run"
]);
const requiredFields = [
  "command_id", "run_id", "pack_id", "pack_version", "pack_digest",
  "expected_state_version", "actor", "command_type", "payload", "causation_id"
];

const parseBody = (body) => typeof body === "string" ? JSON.parse(body) : body;

function invalid(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return "body must be an object";
  const missing = requiredFields.filter((field) => !(field in body));
  if (missing.length) return `missing fields: ${missing.join(", ")}`;
  if (!actors.has(body.actor)) return "actor is not allowlisted";
  if (!commandTypes.has(body.command_type)) return "command_type is not allowlisted";
  if (!Number.isInteger(body.expected_state_version) || body.expected_state_version < 0) return "expected_state_version must be a non-negative integer";
  if (!/^[a-f0-9]{64}$/.test(body.pack_digest)) return "pack_digest must be 64 lowercase hexadecimal characters";
  if (!body.payload || typeof body.payload !== "object" || Array.isArray(body.payload)) return "payload must be an object";
  return null;
}

const isObject = (value) => value && typeof value === "object" && !Array.isArray(value);

function recordsFor(command) {
  if (command.command_type === "upsert_signal") return [["signal", command.payload.signal]];
  if (command.command_type === "record_outcome") return [["outcome", command.payload.outcome]];
  if (command.command_type !== "replace_plan") return [];
  if (!Array.isArray(command.payload.incidents) || !Array.isArray(command.payload.actions)) {
    return { error: "replace_plan requires incident and action arrays" };
  }
  return [
    ...command.payload.incidents.map((record) => ["incident", record]),
    ["plan", command.payload.plan],
    ...command.payload.actions.map((record) => ["action", record])
  ];
}

function validateDomainIdentity(command) {
  const records = recordsFor(command);
  if (records.error) return records.error;
  for (const [kind, record] of records) {
    if (!isObject(record)) return `${kind} must be an object`;
    if (record.contract_version !== "2.0.0") return `${kind}.contract_version must be 2.0.0`;
    for (const field of ["run_id", "pack_id", "pack_version", "pack_digest"]) {
      if (record[field] !== command[field]) return `${kind}.${field} differs from command`;
    }
  }
  return null;
}

const errorStatus = (code) => {
  if (code === "run_not_found") return 404;
  if (["version_conflict", "idempotency_mismatch", "pack_context_mismatch"].includes(code)) return 409;
  return 400;
};

export default async function commands(context, req) {
  try {
    let command;
    try {
      command = parseBody(req.body);
    } catch {
      context.res = jsonResponse(400, { ok: false, error: "invalid_command", message: "body must be valid JSON" });
      return;
    }
    const transportError = invalid(command);
    if (transportError) {
      context.res = jsonResponse(400, { ok: false, error: "invalid_command", message: transportError });
      return;
    }

    const domainError = validateDomainIdentity(command);
    if (domainError) {
      context.res = jsonResponse(400, { ok: false, error: "invalid_contract_identity", message: domainError });
      return;
    }

    const result = await callRpc("apply_command", { p_command: command });
    context.res = jsonResponse(result.error ? errorStatus(result.error) : 200, result);
  } catch (error) {
    context.log.error(error);
    context.res = jsonResponse(500, {
      ok: false,
      error: "gateway_failure",
      message: error.message
    });
  }
}
```

- [ ] **Step 3: Run syntax and frozen-interface checks**

Run:

```bash
node --check api/commands/index.mjs
rg -n 'POST /api/commands|pack_id|expected_state_version' docs/superpowers/specs/2026-09-19-six-workstream-parallel-delivery-design.md
```

Expected: syntax check exits 0; the search shows the frozen flat envelope and no implementation file introduces a nested `pack` or object-valued `actor`.

### Task 5: Expose the observable snapshot

**Files:**

- Create: `api/snapshot/function.json`
- Create: `api/snapshot/index.mjs`

- [ ] **Step 1: Add the GET route**

```json
{
  "scriptFile": "index.mjs",
  "bindings": [
    {
      "authLevel": "anonymous",
      "type": "httpTrigger",
      "direction": "in",
      "name": "req",
      "methods": ["get"],
      "route": "snapshot"
    },
    {
      "type": "http",
      "direction": "out",
      "name": "res"
    }
  ]
}
```

- [ ] **Step 2: Implement the read-only adapter**

```javascript
import { callRpc, jsonResponse } from "../_shared/supabase.mjs";

export default async function snapshot(context, req) {
  const runId = req.query?.run_id;
  if (!runId) {
    context.res = jsonResponse(400, { error: "run_id_required" });
    return;
  }

  try {
    const result = await callRpc("get_run_snapshot", { p_run_id: runId });
    if (!result) {
      context.res = jsonResponse(404, { error: "run_not_found", message: runId });
      return;
    }
    context.res = jsonResponse(200, result);
  } catch (error) {
    context.log.error(error);
    context.res = jsonResponse(500, { error: "snapshot_failure", message: error.message });
  }
}
```

- [ ] **Step 3: Prove the private truth is absent by construction**

Run:

```bash
node --check api/snapshot/index.mjs
! rg -n 'hidden_truth|scenario_truth|truth_canary' api supabase/migrations/202609190001_crisis_core.sql
```

Expected: both commands exit 0. Snapshot assembles only run identity/clock, active v2 state, resources, events, and visible outbox metadata.

### Task 6: Expose the allowlisted Event Router

**Files:**

- Create: `api/event-router/function.json`
- Create: `api/event-router/index.mjs`

- [ ] **Step 1: Add the POST route**

```json
{
  "scriptFile": "index.mjs",
  "bindings": [
    {
      "authLevel": "anonymous",
      "type": "httpTrigger",
      "direction": "in",
      "name": "req",
      "methods": ["post"],
      "route": "event-router"
    },
    {
      "type": "http",
      "direction": "out",
      "name": "res"
    }
  ]
}
```

- [ ] **Step 2: Implement bounded claim, dispatch, and acknowledgement**

Use the coordinator-frozen destination-to-setting map below. Do not list workflows or resolve mutable slugs at runtime. One invocation handles at most ten rows and never waits for a workflow to finish.

```javascript
import { callRpc, jsonResponse } from "../_shared/supabase.mjs";

const required = (name) => {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};

const workflowSettingByDestination = {
  "crisis-intake": "HAPPYROBOT_INTAKE_WORKFLOW_ID",
  "crisis-command": "HAPPYROBOT_COMMAND_WORKFLOW_ID",
  "crisis-response-coordination": "HAPPYROBOT_COORDINATION_WORKFLOW_ID"
};

async function happyRobot(path, options = {}) {
  const baseUrl = required("HAPPYROBOT_BASE_URL").replace(/\/$/, "");
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      authorization: `Bearer ${required("HAPPYROBOT_KEY")}`,
      "content-type": "application/json",
      accept: "application/json",
      ...options.headers
    }
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) throw new Error(`HappyRobot ${response.status}: ${text}`);
  return data;
}

export default async function eventRouter(context, req) {
  const requested = Number(req.body?.limit ?? 10);
  const limit = Number.isInteger(requested) ? Math.max(1, Math.min(requested, 10)) : 10;

  try {
    const jobs = await callRpc("claim_outbox", { p_limit: limit });
    if (!jobs.length) {
      context.res = jsonResponse(200, { claimed: 0, dispatched: 0, failed: 0, results: [] });
      return;
    }

    const results = [];

    for (const job of jobs) {
      let succeeded = false;
      let errorMessage = null;
      let workflowRunId = null;
      try {
        const settingName = workflowSettingByDestination[job.destination];
        if (!settingName) throw new Error(`destination is not allowlisted: ${job.destination}`);
        const workflowId = required(settingName);
        const launched = await happyRobot(`/workflows/${workflowId}/runs`, {
          method: "POST",
          body: JSON.stringify({
            environment: required("HAPPYROBOT_ENV"),
            payload: {
              dispatch_id: job.dispatch_id,
              run_id: job.run_id,
              event: job.payload
            }
          })
        });
        workflowRunId = launched.id ?? launched.data?.id ?? null;
        succeeded = true;
      } catch (error) {
        errorMessage = error.message;
      }

      const receipt = await callRpc("finish_outbox", {
        p_outbox_id: job.outbox_id,
        p_dispatch_id: job.dispatch_id,
        p_succeeded: succeeded,
        p_error: errorMessage
      });
      results.push({
        outbox_id: job.outbox_id,
        destination: job.destination,
        dispatch_id: job.dispatch_id,
        workflow_run_id: workflowRunId,
        succeeded,
        receipt
      });
    }

    context.res = jsonResponse(200, {
      claimed: jobs.length,
      dispatched: results.filter((item) => item.succeeded).length,
      failed: results.filter((item) => !item.succeeded).length,
      results
    });
  } catch (error) {
    context.log.error(error);
    context.res = jsonResponse(500, { error: "event_router_failure", message: error.message });
  }
}
```

- [ ] **Step 3: Run the router syntax check**

Run:

```bash
node --check api/event-router/index.mjs
```

Expected: exit code 0 and no output.

### Task 7: Run the Supabase/Gateway smoke checks

**Files:**

- Verify only; do not create test files.

- [ ] **Step 1: Reapply schema and clean seed**

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction --file supabase/migrations/202609190001_crisis_core.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --file supabase/seed.sql
psql "$DATABASE_URL" -Atc "
  select
    has_table_privilege('anon', 'public.events', 'select')::text || '|' ||
    (exists (
      select 1 from pg_publication_tables
      where pubname='supabase_realtime' and schemaname='public' and tablename='events'
    ))::text;
"
npm run contracts:check
```

Expected privilege/publication line and command tail:

```text
t|t
PASS dana-demo: Signal → Incident → Plan → Action → Outcome
PASS wildfire-demo: Signal → Incident → Plan → Action → Outcome
```

- [ ] **Step 2: Point at the deployed or coordinator-started Functions host**

```bash
export GATEWAY_URL="${GATEWAY_URL:?Set GATEWAY_URL to the Functions origin, without /api}"
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=run-dana-demo" \
  | jq -e '.run.run_id == "run-dana-demo" and .run.state_version == 0 and (.signals | length) == 0'
curl -fsS -X POST "$GATEWAY_URL/api/event-router" \
  -H 'content-type: application/json' \
  -d '{"limit":10}' \
  | jq -e '.claimed == 0 and .dispatched == 0 and .failed == 0'
```

Expected: both `jq -e` commands exit 0; the empty Router call does not require HappyRobot credentials because it returns before workflow discovery.

- [ ] **Step 3: Send the same command twice**

```bash
REQUEST='{
  "command_id":"smoke-source-001",
  "run_id":"run-dana-demo",
  "pack_id":"dana-demo",
  "pack_version":"1.0.0",
  "pack_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "expected_state_version":0,
  "actor":"scenario-controller",
  "command_type":"receive_source_input",
  "payload":{
    "signal_identity":{"signal_id":"sig-smoke-001","revision":1},
    "source_input":{
      "source_input_id":"smoke-input-001",
      "modality":"webhook",
      "content":"SIMULACIÓN: smoke input",
      "reporter_id":"smoke-source",
      "origin_reference":"smoke-origin-001",
      "declared_location":"smoke-zone"
    },
    "scenario_at":"2026-09-19T10:00:00Z",
    "received_at":"2026-09-19T10:00:00Z",
    "correlation_id":"corr-smoke-001",
    "zone_catalog":[{"zone_id":"smoke-zone","label":"Smoke Zone"}]
  },
  "causation_id":null
}'
curl -fsS -X POST "$GATEWAY_URL/api/commands" -H 'content-type: application/json' -d "$REQUEST" > /tmp/gateway-first.json
curl -fsS -X POST "$GATEWAY_URL/api/commands" -H 'content-type: application/json' -d "$REQUEST" > /tmp/gateway-second.json
jq -e '.ok == true and .command_id == "smoke-source-001" and .run_id == "run-dana-demo" and .state_version == 1 and .replayed == false and (.events | length) == 1' /tmp/gateway-first.json
jq -e '.ok == true and .command_id == "smoke-source-001" and .run_id == "run-dana-demo" and .state_version == 1 and .replayed == true and (.events | length) == 1' /tmp/gateway-second.json
diff -u \
  <(jq 'del(.replayed)' /tmp/gateway-first.json) \
  <(jq 'del(.replayed)' /tmp/gateway-second.json)
```

Expected: both `jq -e` commands exit 0 and `diff` prints nothing. Only the `replayed` flag differs between the original and replay responses.

- [ ] **Step 4: Verify one mutation, one version increment, and one outbox row**

```bash
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=run-dana-demo" > /tmp/gateway-snapshot.json
jq -e '
  .run.state_version == 1
  and ([.events[] | select(.event_type == "source_input.received")] | length) == 1
  and ([.events[] | select(
    .event_type == "source_input.received"
    and .payload.signal_identity.signal_id == "sig-smoke-001"
    and .payload.source_input.source_input_id == "smoke-input-001"
    and .payload.run_id == "run-dana-demo"
    and .payload.pack_id == "dana-demo"
    and .payload.state_version == 1
    and .payload.correlation_id == "corr-smoke-001"
    and (.payload.zone_catalog | length) == 1
  )] | length) == 1
  and ([.outbox[] | select(.destination == "crisis-intake")] | length) == 1
' /tmp/gateway-snapshot.json
psql "$DATABASE_URL" -Atc "
  select
    (select count(*) from source_inputs where run_id='run-dana-demo' and source_input_id='smoke-input-001') || '|' ||
    (select count(*) from commands where run_id='run-dana-demo' and command_id='smoke-source-001') || '|' ||
    (select state_version from scenario_runs where run_id='run-dana-demo');
"
```

Expected:

```text
1|1|1
```

- [ ] **Step 5: Verify stale-version rejection has no side effect**

```bash
STALE_REQUEST="$(printf '%s' "$REQUEST" | jq '.command_id="smoke-stale-001" | .payload.source_input.source_input_id="smoke-input-stale" | .payload.signal_identity.signal_id="sig-smoke-stale"')"
curl -sS -o /tmp/gateway-stale.json -w '%{http_code}\n' \
  -X POST "$GATEWAY_URL/api/commands" -H 'content-type: application/json' -d "$STALE_REQUEST"
jq -e '.ok == false and .error == "version_conflict" and .current_state_version == 1' /tmp/gateway-stale.json
curl -fsS "$GATEWAY_URL/api/snapshot?run_id=run-dana-demo" \
  | jq -e '.run.state_version == 1 and ([.events[] | select(.event_type == "source_input.received")] | length) == 1'
```

Expected HTTP status: `409`. Both `jq -e` commands exit 0.

- [ ] **Step 6: Run final static hygiene checks and stop**

```bash
node --check api/_shared/supabase.mjs
node --check api/commands/index.mjs
node --check api/snapshot/index.mjs
node --check api/event-router/index.mjs
jq -e '.version == "2.0"' api/host.json
git diff --check
git status --short -- \
  supabase/migrations/202609190001_crisis_core.sql \
  supabase/seed.sql \
  api/host.json \
  api/_shared/supabase.mjs \
  api/commands api/snapshot api/event-router
```

Expected: syntax, host, and whitespace checks exit 0. The scoped `git status --short` lists the ten created files in this plan, regardless of unrelated parallel work elsewhere in the shared worktree. Report the paths and smoke results to the coordinator; do not commit.

## Handoff contract

The front is complete only when:

- migrations and seed apply from a clean demo state;
- identical command replay returns the original result with `replayed: true` and leaves exactly one mutation/event/outbox record;
- a stale version returns `version_conflict` without changing the run;
- snapshots contain no hidden truth and preserve v2 documents unchanged;
- snapshots expose both `events` and visible `outbox`, while only `events` is granted to `anon` and published to `supabase_realtime` for change notification/refetch;
- `source_input.received` contains the complete Intake context and `action.approved` contains the complete approved Action context;
- Router work exists only for the four allowlisted event families;
- Router resolves those destinations through the three frozen workflow-ID environment settings without listing workflows by slug;
- every Function uses server-side Supabase credentials and no browser-facing file contains the service-role key;
- `npm run contracts:check` and `git diff --check` pass;
- no file outside the ownership map changed and no commit was created.
