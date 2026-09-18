#!/usr/bin/env bash

set -euo pipefail

# shellcheck source=_lib/happyrobot.sh
source "$(cd "$(dirname "$0")" && pwd)/_lib/happyrobot.sh"

api_request GET '/workflows/?page=1&page_size=100&sort=asc' \
  | jq '.data[] | {id, slug, name, latest_environment: (.latest_version.environment // null), latest_version: (.latest_version.id // null)}'
