-- Valte v2 decision: eligible approver and first-decision-wins
-- Enforces deciding_entity_id validation, eligibility check, pending_approval status,
-- active plan membership, evidence validity, and SELECT FOR UPDATE serialization.
-- First valid decision is final; concurrent decisions produce version_conflict via optimistic concurrency.

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
  v_lesson lessons%rowtype;
  v_source_run scenario_runs%rowtype;
  v_outcome outcomes%rowtype;
  v_action actions%rowtype;
  v_deciding_entity text;
  v_note text;
  v_decision jsonb;
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
    'advance_clock', 'pause_run', 'resume_run', 'abort_run', 'complete_run', 'create_lesson'
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

  if v_type <> 'create_lesson' and v_run.status in ('completed', 'aborted') then
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

      if v_payload ? 'applied_lesson_ids' then
        if jsonb_typeof(v_payload->'applied_lesson_ids') <> 'array' then
          return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'applied_lesson_ids must be array');
        end if;
        for v_record in select value from jsonb_array_elements(v_payload->'applied_lesson_ids') loop
          if jsonb_typeof(v_record) <> 'string' or coalesce(v_record #>> '{}','') = '' then
            return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'applied_lesson_ids must be non-empty strings');
          end if;
          select * into v_lesson from lessons where lesson_id = (v_record #>> '{}')::uuid;
          if not found then
            return jsonb_build_object('ok', false, 'error', 'lesson_not_found', 'message', v_record #>> '{}');
          end if;
          if v_lesson.pack_id <> v_run.pack_id then
            return jsonb_build_object('ok', false, 'error', 'lesson_pack_mismatch', 'message', v_record #>> '{}');
          end if;
          if v_lesson.source_run_id = v_run.run_id then
            return jsonb_build_object('ok', false, 'error', 'lesson_self_reference', 'message', v_record #>> '{}');
          end if;
        end loop;
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


      -- Valte v2 approver allowlist: human_required pending_approval must have valid approvers
      for v_record in select value from jsonb_array_elements(v_payload->'actions') loop
        if coalesce(v_record->>'status','') = 'pending_approval' and coalesce(v_record->>'approval_policy','') = 'human_required' then
          if jsonb_typeof(v_record->'approver_entity_ids') is distinct from 'array' then
            return jsonb_build_object('ok', false, 'error', 'invalid_approver', 'message', 'approver_entity_ids must be non-empty array for ' || coalesce(v_record->>'action_id',''));
          end if;
          if jsonb_array_length(v_record->'approver_entity_ids') = 0 then
            return jsonb_build_object('ok', false, 'error', 'invalid_approver', 'message', 'approver_entity_ids must be non-empty for ' || coalesce(v_record->>'action_id',''));
          end if;
          if (select count(*) from jsonb_array_elements(v_record->'approver_entity_ids')) <> (select count(distinct value #>> '{}') from jsonb_array_elements(v_record->'approver_entity_ids')) then
            return jsonb_build_object('ok', false, 'error', 'invalid_approver', 'message', 'approver_entity_ids must be unique for ' || coalesce(v_record->>'action_id',''));
          end if;
          if exists (select 1 from jsonb_array_elements(v_record->'approver_entity_ids') as e where jsonb_typeof(e.value) <> 'string' or coalesce(e.value #>> '{}','') = '') then
            return jsonb_build_object('ok', false, 'error', 'invalid_approver', 'message', 'approver_entity_ids must be non-empty strings');
          end if;
          if coalesce((v_record->>'approvals_required'),'') <> '1' then
            return jsonb_build_object('ok', false, 'error', 'invalid_approver', 'message', 'approvals_required must be 1 for ' || coalesce(v_record->>'action_id',''));
          end if;
          if exists (
            select 1 from jsonb_array_elements(v_record->'approver_entity_ids') as e
            where not exists (select 1 from scenario_entities se where se.run_id = v_run.run_id and se.entity_id = e.value #>> '{}')
          ) then
            return jsonb_build_object('ok', false, 'error', 'invalid_approver', 'message', 'approver_entity_id not found in scenario_entities for ' || coalesce(v_record->>'action_id',''));
          end if;
        end if;
      end loop;

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

      if v_payload ? 'applied_lesson_ids' then
        for v_record in select value from jsonb_array_elements(v_payload->'applied_lesson_ids') loop
          insert into plan_lessons (plan_id, lesson_id, run_id)
          values (v_plan->>'plan_id', (v_record #>> '{}')::uuid, v_run.run_id)
          on conflict do nothing;
        end loop;
      end if;

      v_event := append_crisis_event(
        v_run.run_id, v_next_version, 'plan.replaced',
        p_command->>'causation_id',
        jsonb_build_object('plan_id', (v_payload->'plan')->>'plan_id'),
        null
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('plan_id', (v_payload->'plan')->>'plan_id');

    when 'approve_action' then
      v_deciding_entity := coalesce(v_payload->>'deciding_entity_id','');
      v_note := case when v_payload ? 'note' and jsonb_typeof(v_payload->'note') = 'string' then v_payload->>'note' else null end;
      if v_deciding_entity = '' then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'deciding_entity_id must be non-empty string');
      end if;
      if v_payload ? 'note' and jsonb_typeof(v_payload->'note') is distinct from 'string' and jsonb_typeof(v_payload->'note') is distinct from 'null' then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'note must be a string');
      end if;
      -- serialize on action row
      select a.document into v_record
      from actions a
      join plans p
        on p.run_id = a.run_id
       and p.plan_id = a.plan_id
       and p.status = 'active'
      where a.run_id = v_run.run_id
        and a.action_id = v_payload->>'action_id'
      for update;
      if not found then
        return jsonb_build_object(
          'ok', false,
          'error', 'action_not_in_active_plan',
          'message', coalesce(v_payload->>'action_id', '')
        );
      end if;
      if coalesce(v_record->>'status','') <> 'pending_approval' then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'action is not pending_approval');
      end if;
      if coalesce(v_record->>'approval_policy','') <> 'human_required' then
        return jsonb_build_object('ok', false, 'error', 'invalid_approver', 'message', 'action does not require human approval');
      end if;
      if coalesce(v_record->>'evidence_status','valid') <> 'valid' then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'evidence is not valid');
      end if;
      if jsonb_typeof(v_record->'approver_entity_ids') is distinct from 'array' or not (v_record->'approver_entity_ids' @> to_jsonb(v_deciding_entity)) then
        return jsonb_build_object('ok', false, 'error', 'not_eligible_approver', 'message', 'deciding_entity_id ' || v_deciding_entity || ' not in approver_entity_ids');
      end if;

      v_decision := jsonb_build_object('deciding_entity_id', v_deciding_entity, 'decided_at', now()::text, 'type', 'approved');
      if v_note is not null then
        v_decision := v_decision || jsonb_build_object('note', v_note);
      end if;

      update actions a
      set status = 'approved',
          document = jsonb_set(jsonb_set(document, '{status}', '"approved"'), '{decision}', v_decision)
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
          'causation_id', p_command->>'causation_id',
          'deciding_entity_id', v_deciding_entity,
          'note', v_note
        ),
        'crisis-response-coordination'
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('action_id', v_payload->>'action_id', 'status', 'approved', 'deciding_entity_id', v_deciding_entity);

    when 'reject_action' then
      v_deciding_entity := coalesce(v_payload->>'deciding_entity_id','');
      v_note := case when v_payload ? 'note' and jsonb_typeof(v_payload->'note') = 'string' then v_payload->>'note' else null end;
      if v_deciding_entity = '' then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'deciding_entity_id must be non-empty string');
      end if;
      if v_payload ? 'note' and jsonb_typeof(v_payload->'note') is distinct from 'string' and jsonb_typeof(v_payload->'note') is distinct from 'null' then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'note must be a string');
      end if;
      select a.document into v_record
      from actions a
      join plans p
        on p.run_id = a.run_id
       and p.plan_id = a.plan_id
       and p.status = 'active'
      where a.run_id = v_run.run_id
        and a.action_id = v_payload->>'action_id'
      for update;
      if not found then
        return jsonb_build_object(
          'ok', false,
          'error', 'action_not_in_active_plan',
          'message', coalesce(v_payload->>'action_id', '')
        );
      end if;
      if coalesce(v_record->>'status','') <> 'pending_approval' then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'action is not pending_approval');
      end if;
      if coalesce(v_record->>'approval_policy','') <> 'human_required' then
        return jsonb_build_object('ok', false, 'error', 'invalid_approver', 'message', 'action does not require human approval');
      end if;
      if coalesce(v_record->>'evidence_status','valid') <> 'valid' then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'evidence is not valid');
      end if;
      if jsonb_typeof(v_record->'approver_entity_ids') is distinct from 'array' or not (v_record->'approver_entity_ids' @> to_jsonb(v_deciding_entity)) then
        return jsonb_build_object('ok', false, 'error', 'not_eligible_approver', 'message', 'deciding_entity_id ' || v_deciding_entity || ' not in approver_entity_ids');
      end if;

      v_decision := jsonb_build_object('deciding_entity_id', v_deciding_entity, 'decided_at', now()::text, 'type', 'rejected');
      if v_note is not null then
        v_decision := v_decision || jsonb_build_object('note', v_note);
      end if;

      update actions a
      set status = 'rejected',
          document = jsonb_set(jsonb_set(document, '{status}', '"rejected"'), '{decision}', v_decision)
      where a.run_id = v_run.run_id
        and a.action_id = v_payload->>'action_id'
      returning document into v_record;

      v_event := append_crisis_event(
        v_run.run_id, v_next_version, 'action.rejected',
        p_command->>'causation_id',
        jsonb_build_object('action_id', v_payload->>'action_id', 'deciding_entity_id', v_deciding_entity, 'note', v_note),
        'crisis-command'
      );
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('action_id', v_payload->>'action_id', 'status', 'rejected', 'deciding_entity_id', v_deciding_entity);

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
      v_event := append_crisis_event(v_run.run_id, v_next_version, 'run.aborted', p_command->>'causation_id', v_payload, 'crisis-review');
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('status', 'aborted');

    when 'complete_run' then
      if v_run.status in ('completed', 'aborted') then
        return jsonb_build_object('ok', false, 'error', 'invalid_transition', 'message', 'run is already terminal');
      end if;
      update scenario_runs set status = 'completed' where run_id = v_run.run_id;
      v_event := append_crisis_event(v_run.run_id, v_next_version, 'run.completed', p_command->>'causation_id', v_payload, 'crisis-review');
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('status', 'completed');

    when 'create_lesson' then
      v_record := v_payload->'lesson';
      if v_record is null or jsonb_typeof(v_record) <> 'object'
        or coalesce(v_record->>'instruction','') = ''
        or char_length(v_record->>'instruction') < 10
        or coalesce(v_record->>'evidence_action_id','') = ''
        or coalesce(v_record->>'evidence_outcome_id','') = '' then
        return jsonb_build_object('ok', false, 'error', 'invalid_payload', 'message', 'lesson requires instruction, evidence_action_id, evidence_outcome_id');
      end if;
      select * into v_source_run from scenario_runs where run_id = coalesce(v_record->>'source_run_id', v_run.run_id);
      if not found then
        return jsonb_build_object('ok', false, 'error', 'run_not_found', 'message', coalesce(v_record->>'source_run_id', v_run.run_id));
      end if;
      if v_source_run.status not in ('completed','aborted') then
        return jsonb_build_object('ok', false, 'error', 'source_not_terminal', 'message', v_source_run.run_id);
      end if;
      if coalesce(v_record->>'pack_id', v_source_run.pack_id) <> v_source_run.pack_id then
        return jsonb_build_object('ok', false, 'error', 'lesson_pack_mismatch', 'message', coalesce(v_record->>'pack_id',''));
      end if;
      select * into v_action from actions where run_id = v_source_run.run_id and action_id = v_record->>'evidence_action_id';
      if not found then
        return jsonb_build_object('ok', false, 'error', 'evidence_action_not_found', 'message', v_record->>'evidence_action_id');
      end if;
      select * into v_outcome from outcomes where run_id = v_source_run.run_id and outcome_id = v_record->>'evidence_outcome_id';
      if not found then
        return jsonb_build_object('ok', false, 'error', 'evidence_outcome_not_found', 'message', v_record->>'evidence_outcome_id');
      end if;
      if v_outcome.action_id <> v_record->>'evidence_action_id' then
        return jsonb_build_object('ok', false, 'error', 'evidence_mismatch', 'message', 'outcome action_id differs');
      end if;
      if exists (select 1 from lessons where source_run_id = v_source_run.run_id) then
        return jsonb_build_object('ok', false, 'error', 'lesson_already_exists', 'message', v_source_run.run_id);
      end if;
      insert into lessons (pack_id, source_run_id, instruction, evidence_action_id, evidence_outcome_id)
      values (v_source_run.pack_id, v_source_run.run_id, v_record->>'instruction', v_record->>'evidence_action_id', v_record->>'evidence_outcome_id')
      returning * into v_lesson;
      v_event := append_crisis_event(v_run.run_id, v_next_version, 'lesson.created', p_command->>'causation_id', jsonb_build_object('lesson_id', v_lesson.lesson_id, 'source_run_id', v_source_run.run_id), null);
      v_events := v_events || jsonb_build_array(v_event);
      v_result := jsonb_build_object('lesson_id', v_lesson.lesson_id, 'source_run_id', v_source_run.run_id);
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

revoke all on function apply_command(jsonb) from public, anon, authenticated, service_role;
grant execute on function apply_command(jsonb) to service_role;
