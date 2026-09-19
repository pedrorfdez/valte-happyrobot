-- Valte v2 catalogues: zones and entities per run, exposed in snapshot
create table if not exists scenario_zones (
  run_id text not null references scenario_runs(run_id) on delete cascade,
  zone_id text not null,
  document jsonb not null,
  primary key (run_id, zone_id)
);

create table if not exists scenario_entities (
  run_id text not null references scenario_runs(run_id) on delete cascade,
  entity_id text not null,
  role text not null check (role in ('coordination','authority','responder','source')),
  document jsonb not null,
  primary key (run_id, entity_id)
);

alter table scenario_zones enable row level security;
alter table scenario_entities enable row level security;

revoke all on table scenario_zones, scenario_entities from public, anon, authenticated, service_role;

-- Direct grants for service_role anon; function is SECURITY DEFINER so snapshot still works even with RLS
grant select on table scenario_zones, scenario_entities to anon, service_role;
grant select, insert, delete on table scenario_zones, scenario_entities to service_role;

-- Allow anon select via RLS policy (needed because RLS is enabled)
drop policy if exists scenario_zones_anon_select on scenario_zones;
create policy scenario_zones_anon_select on scenario_zones for select to anon using (true);
drop policy if exists scenario_entities_anon_select on scenario_entities;
create policy scenario_entities_anon_select on scenario_entities for select to anon using (true);
drop policy if exists scenario_zones_service_select on scenario_zones;
create policy scenario_zones_service_select on scenario_zones for select to service_role using (true);
drop policy if exists scenario_entities_service_select on scenario_entities;
create policy scenario_entities_service_select on scenario_entities for select to service_role using (true);

-- Replace get_run_snapshot to include zones, entities, lessons, plan_lessons
create or replace function get_run_snapshot(p_run_id text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select jsonb_build_object(
    'run', to_jsonb(r),
    'zones', coalesce((select jsonb_agg(document order by zone_id) from scenario_zones where run_id = r.run_id), '[]'::jsonb),
    'entities', coalesce((select jsonb_agg(document order by entity_id) from scenario_entities where run_id = r.run_id), '[]'::jsonb),
    'lessons', coalesce((select jsonb_agg(to_jsonb(l) order by l.created_at) from lessons l where l.pack_id = r.pack_id and l.source_run_id <> r.run_id), '[]'::jsonb),
    'signals', coalesce((select jsonb_agg(document order by signal_id, revision) from signals where run_id = r.run_id), '[]'::jsonb),
    'incidents', coalesce((select jsonb_agg(document order by incident_id) from incidents where run_id = r.run_id and state not in ('merged', 'split')), '[]'::jsonb),
    'plan', (select document from plans where run_id = r.run_id and status = 'active' limit 1),
    'actions', coalesce((select jsonb_agg(document order by action_id) from actions where run_id = r.run_id), '[]'::jsonb),
    'outcomes', coalesce((select jsonb_agg(document order by created_at) from outcomes where run_id = r.run_id), '[]'::jsonb),
    'resources', coalesce((select jsonb_agg(document order by resource_id) from resources where run_id = r.run_id), '[]'::jsonb),
    'plan_lessons', coalesce((select jsonb_agg(jsonb_build_object('plan_id', pl.plan_id, 'lesson_id', pl.lesson_id, 'run_id', pl.run_id) order by pl.plan_id) from plan_lessons pl where pl.run_id = r.run_id), '[]'::jsonb),
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

revoke all on function get_run_snapshot(text) from public, anon, authenticated, service_role;
grant execute on function get_run_snapshot(text) to service_role, anon;
