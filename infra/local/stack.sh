#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
exec docker compose --env-file "${MRANKED_COMPOSE_ENV:-infra/local/compose.env.example}" \
  -f infra/compose.yaml -f infra/compose.local.yaml -p mranked-local "$@"
