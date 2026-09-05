#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

tier=""
if [[ "${1:-}" == "--tier" && $# -eq 2 ]]; then
  tier="$2"
else
  echo "usage: $0 --tier daily|weekly|monthly" >&2
  exit 64
fi

case "$tier" in
  daily) repo=1; expected_retention=14 ;;
  weekly) repo=2; expected_retention=8 ;;
  monthly) repo=3; expected_retention=12 ;;
  *) echo "unknown backup tier: $tier" >&2; exit 64 ;;
esac

: "${PGBACKREST_CONFIG:?PGBACKREST_CONFIG is required}"
: "${PGBACKREST_STANZA:=m-ranked}"
: "${BACKUP_REPORT_DIR:=/var/lib/m-ranked/backup-reports}"
: "${BACKUP_LOCK_FILE:=/var/spool/m-ranked/pgbackrest/m-ranked-backup.lock}"

case "$BACKUP_REPORT_DIR" in
  /var/lib/m-ranked/*) ;;
  *) echo "BACKUP_REPORT_DIR must be below /var/lib/m-ranked" >&2; exit 64 ;;
esac
case "$BACKUP_LOCK_FILE" in
  /var/spool/m-ranked/*) ;;
  *) echo "BACKUP_LOCK_FILE must be below /var/spool/m-ranked" >&2; exit 64 ;;
esac
if [[ -L "$BACKUP_REPORT_DIR" || -L "$BACKUP_LOCK_FILE" ]]; then
  echo "backup report directory and lock file must not be symlinks" >&2
  exit 73
fi

for command_name in pgbackrest jq sha256sum flock install date mv mktemp dirname chmod rm; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done
if [[ ! -r "$PGBACKREST_CONFIG" ]]; then
  echo "pgBackRest configuration is not readable" >&2
  exit 77
fi

install -d -m 0700 "$(dirname "$BACKUP_REPORT_DIR/.keep")"
install -d -m 0700 "$(dirname "$BACKUP_LOCK_FILE")"
exec 9>"$BACKUP_LOCK_FILE"
if ! flock -n 9; then
  echo "another base backup is running" >&2
  exit 75
fi

started_epoch="$(date -u +%s)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
report_tmp="$(mktemp "$BACKUP_REPORT_DIR/.backup-report.XXXXXX")"
report_final="$BACKUP_REPORT_DIR/backup-${tier}-${started_at//[:]/}.json"

cleanup() {
  if [[ -n "${report_tmp:-}" && -f "$report_tmp" ]]; then
    rm -f -- "$report_tmp"
  fi
}
trap cleanup EXIT

pgbackrest --config="$PGBACKREST_CONFIG" --stanza="$PGBACKREST_STANZA" \
  --repo="$repo" check
pgbackrest --config="$PGBACKREST_CONFIG" --stanza="$PGBACKREST_STANZA" \
  --repo="$repo" --type=full backup

finished_epoch="$(date -u +%s)"
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
info_json="$(
  pgbackrest --config="$PGBACKREST_CONFIG" --stanza="$PGBACKREST_STANZA" \
    --repo="$repo" --output=json info
)"
if ! jq -e --argjson started "$started_epoch" \
    --argjson expectedRetention "$expected_retention" '
      length == 1
      and .[0].status.code == 0
      and .[0].cipher == "aes-256-cbc"
      and (.[0].backup | length) > 0
      and .[0].backup[-1].type == "full"
      and (.[0].backup[-1].error // false) == false
      and .[0].backup[-1].timestamp.stop >= $started
      and ([.[0].backup[] | select(.type == "full")] | length) <= $expectedRetention
    ' <<<"$info_json" >/dev/null; then
  echo "backup metadata, encryption or retention assertion failed" >&2
  exit 65
fi

jq -n \
  --arg status pass \
  --arg tier "$tier" \
  --argjson repository "$repo" \
  --argjson expectedRetention "$expected_retention" \
  --arg startedAt "$started_at" \
  --arg finishedAt "$finished_at" \
  --argjson durationSeconds "$((finished_epoch - started_epoch))" \
  --argjson pgbackrest "$info_json" \
  '{
      status: $status,
      tier: $tier,
      repository: $repository,
      expectedRetentionPoints: $expectedRetention,
      startedAt: $startedAt,
      finishedAt: $finishedAt,
      durationSeconds: $durationSeconds,
      checks: {
          repositoryStatus: true,
          encrypted: true,
          latestFullCompletedInRun: true,
          retentionCountWithinLimit: true
      },
      pgbackrest: $pgbackrest
  }' >"$report_tmp"

chmod 0600 "$report_tmp"
mv -- "$report_tmp" "$report_final"
sha256sum "$report_final" >"$report_final.sha256"
chmod 0600 "$report_final.sha256"
trap - EXIT

echo "verified encrypted backup completed tier=$tier repo=$repo report=$report_final"
