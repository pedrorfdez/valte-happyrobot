#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=_lib/happyrobot.sh
source "$(cd "$(dirname "$0")" && pwd)/_lib/happyrobot.sh"

workflow_id="$(workflow_id_from_arg_or_env "${1:-}")"
incident_id="${INCIDENT_ID:-demo-fire-001}"

body="$(jq -n \
  --arg environment "$HAPPYROBOT_ENV" \
  --arg incident_id "$incident_id" \
  '{
    environment: $environment,
    payload: {
      incident_id: $incident_id,
      type: "fire",
      severity: "high",
      location: "Campus UPM, Madrid",
      status: "active",
      source: "valte-example",
      observations: [
        "Smoke detected near the east entrance",
        "Evacuation route should be evaluated"
      ]
    }
  }')"

printf 'Disparando workflow %s en entorno %s...\n' "$workflow_id" "$HAPPYROBOT_ENV" >&2
api_request POST "/workflows/$workflow_id/runs" \
  --header 'Content-Type: application/json' \
  --data "$body" \
  | jq .
