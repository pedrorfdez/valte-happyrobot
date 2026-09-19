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
delete from scenario_zones where run_id in ('run-dana-demo', 'run-wildfire-demo', 'run-dana-demo-2');
delete from scenario_entities where run_id in ('run-dana-demo', 'run-wildfire-demo', 'run-dana-demo-2');
delete from resources where run_id in ('run-dana-demo', 'run-wildfire-demo');

insert into resources (run_id, resource_id, resource_mode, capacity, available, document)
values
  (
    'run-dana-demo', 'water-rescue-team-1', 'reusable', 1, 1,
    '{"resource_id":"water-rescue-team-1","owner_entity_id":"rescue-team","name":"Equipo de rescate acuático 1","resource_mode":"reusable","capacity":1,"available":1,"capabilities":["water_rescue"],"initial_zone_id":"catarroja-health-centre"}'::jsonb
  ),
  (
    'run-wildfire-demo', 'wildfire-brigade-1', 'reusable', 1, 1,
    '{"resource_id":"wildfire-brigade-1","owner_entity_id":"wildfire-brigade-1","name":"Brigada forestal 1","resource_mode":"reusable","capacity":1,"available":1,"capabilities":["wildfire_response"],"initial_zone_id":"corredor-sur"}'::jsonb
  );

commit;
