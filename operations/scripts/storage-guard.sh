#!/usr/bin/env bash
set -Eeuo pipefail
exec python3 "$(dirname "$0")/storage_guard.py" observe \
 --peak-bytes "${MRANKED_STORAGE_OPERATION_PEAK_BYTES:-5000000000}"
