-- Valte v2 run summaries: lightweight list without snapshot/signals/lessons
create or replace function list_runs()
returns table (
  run_id text,
  pack_id text,
  name text,
  status text,
  scenario_now timestamptz,
  state_version bigint,
  zone_count bigint,
  active_incident_count bigint,
  pending_approval_count bigint
)
language sql
stable
security definer
set search_path = public
as $$
 select
   r.run_id,
   r.pack_id,
   r.pack_id as name,
   r.status,
   r.scenario_now,
   r.state_version,
   (select count(*) from scenario_zones where run_id = r.run_id),
   (select count(*) from incidents where run_id = r.run_id and state = 'active'),
   (select count(*) from actions a join plans p on p.plan_id = a.plan_id where a.run_id = r.run_id and p.status = 'active' and a.status = 'pending_approval')
 from scenario_runs r
 order by r.created_at;
$$;

revoke all on function list_runs() from public, anon, authenticated, service_role;
grant execute on function list_runs() to service_role, anon;
