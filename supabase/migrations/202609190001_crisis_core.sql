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
  outbox_id uuid primary key default pg_catalog.gen_random_uuid(),
  event_id bigint not null unique references events(event_id),
  run_id text not null references scenario_runs(run_id),
  destination text not null,
  dispatch_id uuid not null default pg_catalog.gen_random_uuid(),
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

alter table outbox
  alter column outbox_id set default pg_catalog.gen_random_uuid(),
  alter column dispatch_id set default pg_catalog.gen_random_uuid();

create index if not exists outbox_claimable
  on outbox (status, available_at, created_at);

alter table scenario_runs enable row level security;
alter table source_inputs enable row level security;
alter table signals enable row level security;
alter table incidents enable row level security;
alter table plans enable row level security;
alter table actions enable row level security;
alter table outcomes enable row level security;
alter table resources enable row level security;
alter table commands enable row level security;
alter table events enable row level security;
alter table outbox enable row level security;

revoke all on table
  scenario_runs, source_inputs, signals, incidents, plans, actions,
  outcomes, resources, commands, events, outbox
from public, anon, authenticated, service_role;
revoke all on sequence events_event_id_seq
from public, anon, authenticated, service_role;

drop policy if exists events_anon_select on events;
create policy events_anon_select on events
  for select to anon
  using (true);

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

create or replace function apply_command(p_command jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_run scenario_runs%rowtype;
  v_existing commands%rowtype;
  v_fingerprint text := pg_catalog.md5(p_command::text);
  v_type text := p_command->>'command_type';
  v_payload jsonb := coalesce(p_command->'payload', '{}'::jsonb);
  v_expected_state_version bigint;
  v_next_version bigint;
  v_events jsonb := '[]'::jsonb;
  v_event jsonb;
  v_result jsonb := '{}'::jsonb;
  v_response jsonb;
  v_record jsonb;
  v_plan jsonb;
  v_active_plan plans%rowtype;
  v_integer integer;
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

  if coalesce(p_command->>'expected_state_version', '') !~ '^[0-9]+$' then
    return jsonb_build_object('ok', false, 'error', 'invalid_command', 'message', 'expected_state_version must be a non-negative integer');
  end if;
  begin
    v_expected_state_version := (p_command->>'expected_state_version')::bigint;
  exception
    when numeric_value_out_of_range then
      return jsonb_build_object('ok', false, 'error', 'invalid_command', 'message', 'expected_state_version is out of range');
  end;

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
    if v_existing.request = p_command then
      return jsonb_set(v_existing.response, '{replayed}', 'true'::jsonb, true);
    end if;
    return jsonb_build_object('ok', false, 'error', 'idempotency_mismatch', 'message', 'command_id already used with different content');
  end if;

  if v_run.pack_id <> p_command->>'pack_id'
    or v_run.pack_version <> p_command->>'pack_version'
    or v_run.pack_digest <> p_command->>'pack_digest' then
    return jsonb_build_object('ok', false, 'error', 'pack_context_mismatch', 'message', 'command pack identity differs from run snapshot');
  end if;

  if v_run.status in ('completed', 'aborted') then
    return jsonb_build_object(
      'ok', false,
      'error', 'run_closed',
      'message', 'run is terminal',
      'run_id', v_run.run_id,
      'status', v_run.status
    );
  end if;

  if v_run.state_version <> v_expected_state_version then
    return jsonb_build_object(
      'ok', false,
      'error', 'version_conflict',
      'message', 'expected_state_version is stale',
      'run_id', v_run.run_id,
      'expected_state_version', v_expected_state_version,
      'actual_state_version', v_run.state_version,
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
        or coalesce((v_payload->'signal_identity')->>'signal_id', '') = ''
        or coalesce((v_payload->'signal_identity')->>'revision', '') !~ '^[1-9][0-9]*$'
        or jsonb_typeof(v_payload->'zone_catalog') <> 'array' then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'receive_source_input fields are incomplete');
      end if;
      begin
        v_integer := ((v_payload->'signal_identity')->>'revision')::integer;
      exception
        when numeric_value_out_of_range then
          return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'signal revision is out of range');
      end;
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
        'revision', v_integer
      );

    when 'upsert_signal' then
      v_record := v_payload->'signal';
      if v_record is null
        or jsonb_typeof(v_record) <> 'object'
        or coalesce(v_record->>'signal_id', '') = ''
        or coalesce(v_record->>'revision', '') !~ '^[1-9][0-9]*$'
        or coalesce(v_record->>'status', '') = '' then
        return jsonb_build_object(
          'ok', false,
          'error', 'invalid_payload',
          'message', 'signal requires signal_id, positive integer revision, and status'
        );
      end if;
      begin
        v_integer := (v_record->>'revision')::integer;
      exception
        when numeric_value_out_of_range then
          return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'signal revision is out of range');
      end;
      insert into signals (run_id, signal_id, revision, status, document)
      values (
        v_run.run_id,
        v_record->>'signal_id',
        v_integer,
        v_record->>'status',
        v_record
      );
      v_event := append_crisis_event(
        v_run.run_id, v_next_version,
        case when v_integer = 1 then 'signal.created' else 'signal.revised' end,
        p_command->>'causation_id',
        jsonb_build_object('signal_id', v_record->>'signal_id', 'revision', v_integer),
        'crisis-command'
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('signal_id', v_record->>'signal_id', 'revision', v_integer);

    when 'replace_plan' then
      v_plan := v_payload->'plan';
      if jsonb_typeof(v_payload->'incidents') is distinct from 'array'
        or jsonb_typeof(v_payload->'actions') is distinct from 'array'
        or jsonb_typeof(v_plan) is distinct from 'object' then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'replace_plan requires incidents, plan, and actions');
      end if;

      if coalesce(v_plan->>'plan_id', '') = ''
        or coalesce(v_plan->>'plan_version', '') !~ '^[1-9][0-9]*$'
        or coalesce(v_plan->>'status', '') <> 'active'
        or jsonb_typeof(v_plan->'incident_ids') is distinct from 'array'
        or jsonb_typeof(v_plan->'action_ids') is distinct from 'array' then
        return jsonb_build_object(
          'ok', false,
          'error', 'invalid_payload',
          'message', 'plan requires plan_id, positive integer plan_version, active status, incident_ids, and action_ids'
        );
      end if;
      begin
        v_integer := (v_plan->>'plan_version')::integer;
      exception
        when numeric_value_out_of_range then
          return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'plan_version is out of range');
      end;

      select * into v_active_plan
      from plans
      where run_id = v_run.run_id and status = 'active';

      if found then
        if v_integer::bigint <> v_active_plan.plan_version::bigint + 1
          or v_plan->>'plan_id' = v_active_plan.plan_id
          or coalesce(v_plan->>'supersedes_plan_id', '') <> v_active_plan.plan_id then
          return jsonb_build_object(
            'ok', false,
            'error', 'invalid_payload',
            'message', 'replan must increment the active version, use a new plan_id, and exactly supersede the active plan'
          );
        end if;
      else
        if exists (select 1 from plans where run_id = v_run.run_id)
          or v_integer <> 1
          or not (v_plan ? 'supersedes_plan_id')
          or jsonb_typeof(v_plan->'supersedes_plan_id') is distinct from 'null' then
          return jsonb_build_object(
            'ok', false,
            'error', 'invalid_payload',
            'message', 'first plan must be version 1 with null supersedes_plan_id'
          );
        end if;
      end if;

      if exists (
        select 1
        from plans
        where run_id = v_run.run_id
          and (plan_id = v_plan->>'plan_id' or plan_version = v_integer)
      ) then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'plan_id and plan_version must be new');
      end if;

      if jsonb_array_length(v_payload->'incidents') = 0
        or exists (
          select 1
          from jsonb_array_elements(v_payload->'incidents') as item(value)
          where jsonb_typeof(item.value) <> 'object'
            or coalesce(item.value->>'incident_id', '') = ''
            or coalesce(item.value->>'state', '') = ''
        ) then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'every incident requires incident_id and state');
      end if;

      if exists (
        select 1
        from jsonb_array_elements(v_payload->'actions') as item(value)
        where jsonb_typeof(item.value) <> 'object'
          or coalesce(item.value->>'action_id', '') = ''
          or coalesce(item.value->>'plan_id', '') = ''
          or coalesce(item.value->>'incident_id', '') = ''
          or coalesce(item.value->>'status', '') = ''
      ) then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'every action requires action_id, plan_id, incident_id, and status');
      end if;

      if exists (
        select 1
        from jsonb_array_elements(v_plan->'incident_ids') as item(value)
        where jsonb_typeof(item.value) <> 'string'
          or coalesce(item.value #>> '{}', '') = ''
      ) or exists (
        select 1
        from jsonb_array_elements(v_plan->'action_ids') as item(value)
        where jsonb_typeof(item.value) <> 'string'
          or coalesce(item.value #>> '{}', '') = ''
      ) then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'plan references must be non-empty string IDs');
      end if;

      if (select count(*) from jsonb_array_elements(v_payload->'incidents'))
          <> (select count(distinct value->>'incident_id') from jsonb_array_elements(v_payload->'incidents'))
        or (select count(*) from jsonb_array_elements(v_payload->'actions'))
          <> (select count(distinct value->>'action_id') from jsonb_array_elements(v_payload->'actions'))
        or (select count(*) from jsonb_array_elements(v_plan->'incident_ids'))
          <> (select count(distinct value #>> '{}') from jsonb_array_elements(v_plan->'incident_ids'))
        or (select count(*) from jsonb_array_elements(v_plan->'action_ids'))
          <> (select count(distinct value #>> '{}') from jsonb_array_elements(v_plan->'action_ids')) then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'plan and payload IDs must be unique');
      end if;

      if exists (
        select 1
        from actions existing
        join jsonb_array_elements(v_payload->'actions') as item(value)
          on existing.action_id = item.value->>'action_id'
        where existing.run_id = v_run.run_id
      ) then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'action_id already exists in this run');
      end if;

      if jsonb_array_length(v_plan->'incident_ids') <> jsonb_array_length(v_payload->'incidents')
        or jsonb_array_length(v_plan->'action_ids') <> jsonb_array_length(v_payload->'actions')
        or exists (
          select 1
          from jsonb_array_elements(v_payload->'incidents') as item(value)
          where not (v_plan->'incident_ids' @> jsonb_build_array(item.value->>'incident_id'))
        )
        or exists (
          select 1
          from jsonb_array_elements(v_payload->'actions') as item(value)
          where item.value->>'plan_id' <> v_plan->>'plan_id'
            or not (v_plan->'incident_ids' @> jsonb_build_array(item.value->>'incident_id'))
            or not (v_plan->'action_ids' @> jsonb_build_array(item.value->>'action_id'))
        ) then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'plan, incident, and action references are inconsistent');
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

      insert into plans (run_id, plan_id, plan_version, status, document)
      values (
        v_run.run_id,
        v_plan->>'plan_id',
        v_integer,
        v_plan->>'status',
        v_plan
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
      select a.document into v_record
      from actions a
      join plans p
        on p.run_id = a.run_id
       and p.plan_id = a.plan_id
       and p.status = 'active'
      where a.run_id = v_run.run_id
        and a.action_id = v_payload->>'action_id';
      if not found then
        return jsonb_build_object(
          'ok', false,
          'error', 'action_not_in_active_pack',
          'message', coalesce(v_payload->>'action_id', '')
        );
      end if;
      if v_record->>'status' not in ('proposed', 'pending_approval') then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'action cannot be approved');
      end if;

      update actions a
      set status = 'approved', document = jsonb_set(document, '{status}', '"approved"')
      where a.run_id = v_run.run_id
        and a.action_id = v_payload->>'action_id'
      returning document into v_record;
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
      if v_record is null
        or jsonb_typeof(v_record) <> 'object'
        or coalesce(v_record->>'outcome_id', '') = ''
        or coalesce(v_record->>'action_id', '') = ''
        or coalesce(v_record->>'status', '') = '' then
        return jsonb_build_object(
          'ok', false,
          'error', 'invalid_payload',
          'message', 'outcome requires outcome_id, action_id, and status'
        );
      end if;
      if not exists (
        select 1
        from actions a
        join plans p
          on p.run_id = a.run_id
         and p.plan_id = a.plan_id
         and p.status = 'active'
        where a.run_id = v_run.run_id
          and a.action_id = v_record->>'action_id'
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

drop function if exists claim_outbox(integer);

create or replace function claim_outbox(
  p_limit integer default 10,
  p_run_id text default null
)
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
      and (p_run_id is null or o.run_id = p_run_id)
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
      lease_until = now() + interval '2 minutes',
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
    and lease_until > now()
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

revoke all on function append_crisis_event(text, bigint, text, text, jsonb, text)
  from public, anon, authenticated, service_role;
revoke all on function apply_command(jsonb)
  from public, anon, authenticated, service_role;
revoke all on function get_run_snapshot(text)
  from public, anon, authenticated, service_role;
revoke all on function claim_outbox(integer, text)
  from public, anon, authenticated, service_role;
revoke all on function finish_outbox(uuid, uuid, boolean, text)
  from public, anon, authenticated, service_role;
grant execute on function apply_command(jsonb) to service_role;
grant execute on function get_run_snapshot(text) to service_role;
grant execute on function claim_outbox(integer, text) to service_role;
grant execute on function finish_outbox(uuid, uuid, boolean, text) to service_role;
