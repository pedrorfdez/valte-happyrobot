#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=_lib/happyrobot.sh
source "$(cd "$(dirname "$0")" && pwd)/_lib/happyrobot.sh"

workflow_id="$(workflow_id_from_arg_or_env "${1:-}")"
temperature_c="${2:-${TEMPERATURE_C:-9.5}}"
threshold_c="${TEMPERATURE_THRESHOLD_C:-8.0}"
shipment_id="${SHIPMENT_ID:-DHL-HEALTHCARE-001}"
sensor_id="${SENSOR_ID:-cold-chain-sensor-001}"
warehouse="${WAREHOUSE:-Madrid Control Tower}"
zone="${ZONE:-pharma-warehouse-a}"
commodity="${COMMODITY:-temperature-sensitive medicine}"
incident_id="${INCIDENT_ID:-temp-breach-$shipment_id}"
dry_run="${DRY_RUN:-true}"
observed_at="${OBSERVED_AT:-$(date -u '+%Y-%m-%dT%H:%M:%SZ')}"

if ! [[ "$temperature_c" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then
  printf 'TEMPERATURE_C no es un número: %s\n' "$temperature_c" >&2
  exit 1
fi

if ! [[ "$threshold_c" =~ ^-?[0-9]+([.][0-9]+)?$ ]]; then
  printf 'TEMPERATURE_THRESHOLD_C no es un número: %s\n' "$threshold_c" >&2
  exit 1
fi

if awk -v temperature="$temperature_c" -v threshold="$threshold_c" \
  'BEGIN { exit !(temperature > threshold) }'; then
  breach=true
  severity=critical
  recommended_action='Immediately contact the control tower and escalate through the cold-chain response levels.'
else
  breach=false
  severity=normal
  recommended_action='Continue monitoring; no escalation is required.'
fi

body="$(jq -n \
  --arg environment "$HAPPYROBOT_ENV" \
  --arg incident_id "$incident_id" \
  --arg shipment_id "$shipment_id" \
  --arg sensor_id "$sensor_id" \
  --arg warehouse "$warehouse" \
  --arg zone "$zone" \
  --arg commodity "$commodity" \
  --arg observed_at "$observed_at" \
  --argjson temperature_c "$temperature_c" \
  --argjson threshold_c "$threshold_c" \
  --argjson breach "$breach" \
  --arg severity "$severity" \
  --arg recommended_action "$recommended_action" \
  '{
    environment: $environment,
    payload: {
      event_type: "temperature_threshold_breach",
      incident_id: $incident_id,
      shipment_id: $shipment_id,
      commodity: $commodity,
      sensor_id: $sensor_id,
      location: {
        warehouse: $warehouse,
        zone: $zone
      },
      measurement: {
        temperature_c: $temperature_c,
        threshold_c: $threshold_c,
        unit: "C",
        breach: $breach,
        observed_at: $observed_at
      },
      severity: $severity,
      escalation_policy: [
        "warehouse_operator",
        "control_tower",
        "on_call_manager"
      ],
      recommended_action: $recommended_action,
      source: "dhl-temperature-alert-example"
    }
  }')"

if [[ "$dry_run" == "true" ]]; then
  printf '%s\n' 'Simulación (DRY_RUN=true): no se ha enviado ninguna alerta.' >&2
  printf '%s\n' "$body" | jq .
  exit 0
fi

if [[ "$breach" != "true" ]]; then
  printf 'Temperatura %s°C dentro del umbral %s°C; no se dispara ningún workflow.\n' \
    "$temperature_c" "$threshold_c" >&2
  exit 0
fi

printf 'Disparando alerta DHL para %s: %s°C > %s°C...\n' \
  "$shipment_id" "$temperature_c" "$threshold_c" >&2
api_request POST "/workflows/$workflow_id/runs" \
  --header 'Content-Type: application/json' \
  --data "$body" \
  | jq .
