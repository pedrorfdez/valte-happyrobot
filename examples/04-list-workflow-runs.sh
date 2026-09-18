#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=_lib/happyrobot.sh
source "$(cd "$(dirname "$0")" && pwd)/_lib/happyrobot.sh"

workflow_id="$(workflow_id_from_arg_or_env "${1:-}")"
status="${2:-}"
endpoint="/workflows/$workflow_id/runs?page=1&page_size=20&sort=desc"

if [[ -n "$status" ]]; then
  case "$status" in
    scheduled|running|completed|canceled|failed) ;;
    *)
      printf 'Estado no válido: %s\n' "$status" >&2
      printf 'Usa: scheduled, running, completed, canceled o failed.\n' >&2
      exit 1
      ;;
  esac
  endpoint="$endpoint&status=$status"
fi

api_request GET "$endpoint" \
  | jq '{pagination, runs: [.data[] | {id, status, timestamp, completed_at, failure_reason}]}'
