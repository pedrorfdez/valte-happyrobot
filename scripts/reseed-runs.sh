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

echo "→ Aplicando migración (idempotente)..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction \
  --file "$ROOT/supabase/migrations/202609190001_crisis_core.sql"
echo "→ Reseed run-dana-demo + run-wildfire-demo (state_version=0, ready)..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --file "$ROOT/supabase/seed.sql"
echo "→ Verificación:"
psql "$DATABASE_URL" -Atc "select run_id || '|' || pack_id || '|' || status || '|' || state_version from scenario_runs where run_id in ('run-dana-demo','run-wildfire-demo') order by run_id;"
for valte_run in run-dana-demo run-wildfire-demo; do
  echo "→ Counts $valte_run (deben ser 0 salvo resources=1):"
  psql "$DATABASE_URL" -Atc "
    select 'signals:' || count(*) from signals where run_id='$valte_run'
    union all select 'incidents:' || count(*) from incidents where run_id='$valte_run'
    union all select 'plans:' || count(*) from plans where run_id='$valte_run'
    union all select 'actions:' || count(*) from actions where run_id='$valte_run'
    union all select 'outcomes:' || count(*) from outcomes where run_id='$valte_run'
    union all select 'resources:' || count(*) from resources where run_id='$valte_run'
    order by 1;"
done
echo "✓ Runs limpios — listos para E2E sin contaminación cruzada (ready, state_version=0)."
