#!/usr/bin/env bash

set -euo pipefail

EXAMPLES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$EXAMPLES_DIR/.." && pwd)"

if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.env"
  set +a
fi

: "${HAPPYROBOT_KEY:?Define HAPPYROBOT_KEY en .env antes de ejecutar este ejemplo}"

HAPPYROBOT_BASE_URL="${HAPPYROBOT_BASE_URL:-https://platform.eu.happyrobot.ai/api/v2}"
HAPPYROBOT_ENV="${HAPPYROBOT_ENV:-development}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Falta el comando requerido: %s\n' "$1" >&2
    exit 1
  }
}

require_command curl
require_command jq

api_request() {
  local method="$1"
  local endpoint="$2"
  shift 2

  curl --fail-with-body --silent --show-error \
    --request "$method" \
    --header "Authorization: Bearer $HAPPYROBOT_KEY" \
    --header 'Accept: application/json' \
    "$HAPPYROBOT_BASE_URL$endpoint" \
    "$@"
}

workflow_id_from_arg_or_env() {
  local workflow_id="${1:-${WORKFLOW_ID:-}}"

  if [[ -z "$workflow_id" ]]; then
    printf 'Uso: %s <workflow-id>\n' "$(basename "$0")" >&2
    printf 'También puedes definir WORKFLOW_ID en .env.\n' >&2
    exit 1
  fi

  printf '%s' "$workflow_id"
}
