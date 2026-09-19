#!/usr/bin/env bash
set -euo pipefail
# Reseed clean demo runs — idempotente, evita contaminación cruzada DANA→wildfire.
# Uso: ./scripts/reseed-runs.sh  (requiere DATABASE_URL en .env)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then
  set -a; source "$ROOT/.env"; set +a
fi
: "${DATABASE_URL:?Define DATABASE_URL en .env (Supabase pooler, puerto 5432)}"
command -v psql >/dev/null 2>&1 || { echo "✗ psql no encontrado — instala PostgreSQL client" >&2; exit 1; }

echo "→ Estado actual de ambos runs (antes de reseed):"
psql "$DATABASE_URL" -Atc "select run_id || '|' || coalesce(pack_id,'-') || '|' || coalesce(status,'-') || '|' || coalesce(state_version::text,'-') from scenario_runs where run_id in ('run-dana-demo','run-wildfire-demo') order by run_id;" || echo "  (sin runs previos o error de lectura)"

if [[ "${1:-}" == "--yes" ]]; then
  echo "→ Confirmación automática --yes"
else
  printf '⚠  Esto eliminará todo el estado observable de run-dana-demo y run-wildfire-demo.\nEscribe SIMULACION para continuar: '
  read -r valte_confirm
  if [[ "$valte_confirm" != "SIMULACION" ]]; then
    echo "✗ Confirmación no válida — reseed cancelado. No se borró ningún dato." >&2
    exit 1
  fi
fi

echo "→ Aplicando migraciones (idempotente)..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file "$ROOT/supabase/migrations/202609190001_crisis_core.sql"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file "$ROOT/supabase/migrations/202609190002_non_retryable_live_dispatch.sql" || true
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file "$ROOT/supabase/migrations/202609190003_agent_simulation_lessons.sql" || true
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file "$ROOT/supabase/migrations/202609190004_valte_catalogues.sql" || true
echo "→ Reseed run-dana-demo + run-wildfire-demo (state_version=0, ready)..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --file "$ROOT/supabase/seed.sql"
# Limpia lecciones históricas para evitar contaminación cross-run (agent_simulation)
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
  delete from plan_lessons where run_id in ('run-dana-demo','run-wildfire-demo','run-dana-demo-2');
  delete from lessons where source_run_id in ('run-dana-demo','run-wildfire-demo','run-dana-demo-2');
" >/dev/null || true
# Crea run adicional para historical learning (pack dana) si no existe
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
  insert into scenario_runs (run_id, pack_id, pack_version, pack_digest, status, scenario_now, state_version)
  values ('run-dana-demo-2', 'dana-demo', '1.0.0', repeat('c',64), 'ready', '2026-09-19T10:00:00Z', 0)
  on conflict (run_id) do update set pack_id=excluded.pack_id, pack_version=excluded.pack_version, pack_digest=excluded.pack_digest, status='ready', scenario_now=excluded.scenario_now, state_version=0, updated_at=now();
  delete from plan_lessons where run_id='run-dana-demo-2';
  delete from scenario_zones where run_id='run-dana-demo-2';
  delete from scenario_entities where run_id='run-dana-demo-2';
  delete from outbox where run_id='run-dana-demo-2';
  delete from events where run_id='run-dana-demo-2';
  delete from commands where run_id='run-dana-demo-2';
  delete from outcomes where run_id='run-dana-demo-2';
  delete from actions where run_id='run-dana-demo-2';
  delete from plans where run_id='run-dana-demo-2';
  delete from incidents where run_id='run-dana-demo-2';
  delete from signals where run_id='run-dana-demo-2';
  delete from source_inputs where run_id='run-dana-demo-2';
  delete from resources where run_id='run-dana-demo-2';
   insert into resources (run_id, resource_id, resource_mode, capacity, available, document)
  values ('run-dana-demo-2', 'water-rescue-team-1', 'reusable', 1, 1, '{\"resource_id\":\"water-rescue-team-1\",\"owner_entity_id\":\"rescue-team\",\"name\":\"Equipo de rescate acuático 1\",\"resource_mode\":\"reusable\",\"capacity\":1,\"available\":1,\"capabilities\":[\"water_rescue\"],\"initial_zone_id\":\"catarroja-health-centre\"}'::jsonb)
  on conflict (run_id, resource_id) do update set capacity=excluded.capacity, available=excluded.available, document=excluded.document;
" >/dev/null || true
echo "→ Seeding zones/entities catalogues from scenario-packs..."
if ! command -v jq >/dev/null 2>&1; then
  echo "✗ jq requerido para seed de zones/entities" >&2; exit 1
fi
seed_catalogue() {
  local pack="$1"
  local run_id="$2"
  local zones_file="$ROOT/scenario-packs/$pack/zones.json"
  local entities_file="$ROOT/scenario-packs/$pack/entities.json"
  echo "  • $pack → $run_id (zones: $zones_file, entities: $entities_file)"
  # zones
  jq -c '.[]' "$zones_file" | while IFS= read -r doc; do
    zone_id=$(echo "$doc" | jq -r '.zone_id')
    # Escape single quotes for SQL string literal
    esc_doc=$(printf "%s" "$doc" | sed "s/'/''/g")
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "insert into scenario_zones (run_id, zone_id, document) values ('$run_id', '$zone_id', '$esc_doc'::jsonb) on conflict (run_id, zone_id) do update set document = excluded.document;" >/dev/null
  done
  # entities
  jq -c '.[]' "$entities_file" | while IFS= read -r doc; do
    entity_id=$(echo "$doc" | jq -r '.entity_id')
    role=$(echo "$doc" | jq -r '.role')
    esc_doc=$(printf "%s" "$doc" | sed "s/'/''/g")
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "insert into scenario_entities (run_id, entity_id, role, document) values ('$run_id', '$entity_id', '$role', '$esc_doc'::jsonb) on conflict (run_id, entity_id) do update set role = excluded.role, document = excluded.document;" >/dev/null
  done
}
seed_catalogue "dana-demo" "run-dana-demo"
seed_catalogue "dana-demo" "run-dana-demo-2"
seed_catalogue "wildfire-demo" "run-wildfire-demo"
echo "→ Verificación:"
psql "$DATABASE_URL" -Atc "select run_id || '|' || pack_id || '|' || status || '|' || state_version from scenario_runs where run_id in ('run-dana-demo','run-wildfire-demo') order by run_id;"
for valte_run in run-dana-demo run-wildfire-demo run-dana-demo-2; do
  echo "→ Counts $valte_run (deben ser 0 salvo resources=1, zones/entities populated):"
  psql "$DATABASE_URL" -Atc "
    select 'signals:' || count(*) from signals where run_id='$valte_run'
    union all select 'incidents:' || count(*) from incidents where run_id='$valte_run'
    union all select 'plans:' || count(*) from plans where run_id='$valte_run'
    union all select 'actions:' || count(*) from actions where run_id='$valte_run'
    union all select 'outcomes:' || count(*) from outcomes where run_id='$valte_run'
    union all select 'resources:' || count(*) from resources where run_id='$valte_run'
    union all select 'zones:' || count(*) from scenario_zones where run_id='$valte_run'
    union all select 'entities:' || count(*) from scenario_entities where run_id='$valte_run'
    order by 1;"
done
echo "✓ Runs limpios — listos para E2E sin contaminación cruzada (ready, state_version=0)."
