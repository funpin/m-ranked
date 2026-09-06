#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
exec docker compose --env-file infra/local/compose.env \
  -f infra/compose.yaml -f infra/compose.local.yaml -p mranked-local "$@"
