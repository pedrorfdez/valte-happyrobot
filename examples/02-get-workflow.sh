#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=_lib/happyrobot.sh
source "$(cd "$(dirname "$0")" && pwd)/_lib/happyrobot.sh"

workflow_id="$(workflow_id_from_arg_or_env "${1:-}")"

api_request GET "/workflows/$workflow_id" | jq .
