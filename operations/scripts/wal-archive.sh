#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

if [[ $# -ne 2 ]]; then
  echo "usage: $0 WAL_PATH WAL_FILE" >&2
  exit 64
fi

wal_path="$1"
wal_file="$2"
if [[ ! "$wal_file" =~ ^[0-9A-F]{24}([.][0-9A-F]{8}[.]backup|[.]partial)?$ \
      && ! "$wal_file" =~ ^[0-9A-F]{8}[.]history$ ]]; then
  echo "refusing unexpected WAL filename" >&2
  exit 64
fi
if [[ ! -f "$wal_path" || -L "$wal_path" ]]; then
  echo "WAL source is not a regular file" >&2
  exit 66
fi
if [[ "${wal_path##*/}" != "$wal_file" ]]; then
  echo "WAL source basename does not match PostgreSQL placeholder" >&2
  exit 64
fi

: "${PGBACKREST_CONFIG:=/etc/m-ranked/pgbackrest.conf}"
: "${PGBACKREST_STANZA:=m-ranked}"
if [[ ! -r "$PGBACKREST_CONFIG" ]]; then
  echo "pgBackRest configuration is not readable" >&2
  exit 77
fi
if ! command -v pgbackrest >/dev/null 2>&1; then
  echo "required command is missing: pgbackrest" >&2
  exit 69
fi

# With multiple repositories and archive-async enabled, pgBackRest pushes WAL
# to every repository but may return success once at least one repository has
# stored it. Monitor per-repository lag: PostgreSQL retains WAL only when none
# of the repositories accepts the segment.
exec pgbackrest --config="$PGBACKREST_CONFIG" --stanza="$PGBACKREST_STANZA" \
  archive-push "$wal_path"
