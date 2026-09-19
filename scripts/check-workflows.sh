#!/usr/bin/env bash
set -euo pipefail
# Verifica que los 3 workflows dev están publicados y accesibles vía API v2.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$ROOT/.env" ]]; then set -a; source "$ROOT/.env"; set +a; fi
: "${HAPPYROBOT_KEY:?HAPPYROBOT_KEY requerido}"
: "${HAPPYROBOT_BASE_URL:=https://platform.eu.happyrobot.ai/api/v2}"
for var in HAPPYROBOT_INTAKE_WORKFLOW_ID HAPPYROBOT_COMMAND_WORKFLOW_ID HAPPYROBOT_COORDINATION_WORKFLOW_ID; do
  id="${!var:-}"; if [[ -z "$id" ]]; then echo "✗ $var vacío — publica el workflow en development y exporta su ID a .env"; exit 1; fi
  echo "→ $var=$id"
  if ! curl -fsS -H "Authorization: Bearer $HAPPYROBOT_KEY" "$HAPPYROBOT_BASE_URL/workflows/$id" | jq -e '.id // .data.id' >/dev/null; then
    echo "✗ No accesible $id (¿environment=development? ¿ID correcto?)"; exit 1
  fi
  echo "✓ $var OK"
done
echo "✓ Los 3 workflows dev accesibles — listo para: node scripts/e2e-demo.mjs --gateway \"\$GATEWAY_URL\" --dana-run \"\$DANA_RUN_ID\" --wildfire-run \"\$WILDFIRE_RUN_ID\" --effects dry-run"
