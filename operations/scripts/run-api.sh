#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

# Profile B supplies the URL as a systemd credential. Keeping its value out of
# the unit and argv prevents accidental disclosure by systemctl/show or ps.
if [[ -n "${API_REDIS_URL_FILE:-}" ]]; then
  [[ -r "$API_REDIS_URL_FILE" ]] || {
    echo "API_REDIS_URL_FILE is not readable" >&2
    exit 66
  }
  API_REDIS_URL="$(<"$API_REDIS_URL_FILE")"
  export API_REDIS_URL
fi

exec /opt/m-ranked/current/.venv/bin/python -m api
