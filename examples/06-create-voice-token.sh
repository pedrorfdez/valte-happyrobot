#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=_lib/happyrobot.sh
source "$(cd "$(dirname "$0")" && pwd)/_lib/happyrobot.sh"

workflow_id="$(workflow_id_from_arg_or_env "${1:-}")"

body="$(jq -n \
  --arg workflow_id "$workflow_id" \
  --arg env "$HAPPYROBOT_ENV" \
  '{
    workflow_id: $workflow_id,
    env: $env,
    ttl_seconds: 3600,
    data: {
      client: "valte-dashboard",
      channel: "voice"
    }
  }')"

printf '%s\n' 'Este endpoint debe ejecutarse en el servidor; no expongas HAPPYROBOT_KEY al navegador.' >&2
api_request POST '/voice/tokens/' \
  --header 'Content-Type: application/json' \
  --data "$body" \
  | jq '{url, token, room_name, run_id}'
