#!/bin/bash -p
set -Eeuo pipefail

umask 077
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
unset BASH_ENV CDPATH ENV PYTHONHOME PYTHONPATH TMPDIR __PYVENV_LAUNCHER__

transition_entry_source="${BASH_SOURCE[0]}"
case "$transition_entry_source" in
  /*) ;;
  *) transition_entry_source="$(pwd -P)/$transition_entry_source" ;;
esac
transition_entry_dir="${transition_entry_source%/*}"
transition_entry_name="${transition_entry_source##*/}"
transition_entry_dir="$(cd -- "$transition_entry_dir" && pwd -P)" || {
  echo "cannot resolve rollback entrypoint origin" >&2
  exit 73
}
transition_entry_path="$transition_entry_dir/$transition_entry_name"
transition_lock_helper="$transition_entry_dir/transition-lock.sh"
_mranked_bootstrap_stat() {
  /usr/bin/stat -c '%d:%i:%u:%g:%a:%h' -- "$1" 2>/dev/null \
    || /usr/bin/stat -f '%d:%i:%u:%g:%Lp:%l' "$1" 2>/dev/null
}
for transition_secure_file in "$transition_entry_path" "$transition_lock_helper"; do
  transition_metadata="$(_mranked_bootstrap_stat "$transition_secure_file")" \
    || transition_metadata=""
  IFS=: read -r transition_device transition_inode transition_owner \
    transition_group transition_mode transition_links <<<"$transition_metadata"
  if [[ ! -f "$transition_secure_file" || -L "$transition_secure_file" \
        || "$transition_owner" != 0 || "$transition_links" != 1 \
        || ! "$transition_mode" =~ ^[0-7]{3,4}$ ]] \
      || (( (8#$transition_mode & 8#022) != 0 )); then
    echo "rollback entrypoint or transition lock helper is unsafe" >&2
    exit 73
  fi
done
transition_helper_identity="$(_mranked_bootstrap_stat "$transition_lock_helper")"
transition_secure_dir="$transition_entry_dir"
while :; do
  transition_metadata="$(_mranked_bootstrap_stat "$transition_secure_dir")" \
    || transition_metadata=""
  IFS=: read -r transition_device transition_inode transition_owner \
    transition_group transition_mode transition_links <<<"$transition_metadata"
  if [[ ! -d "$transition_secure_dir" || -L "$transition_secure_dir" \
        || "$transition_owner" != 0 || ! "$transition_mode" =~ ^[0-7]{3,4}$ ]] \
      || (( (8#$transition_mode & 8#022) != 0 )); then
    echo "rollback entrypoint directory chain is unsafe" >&2
    exit 73
  fi
  [[ "$transition_secure_dir" == / ]] && break
  transition_secure_dir="${transition_secure_dir%/*}"
  [[ -n "$transition_secure_dir" ]] || transition_secure_dir=/
done
if [[ ! -r "$transition_lock_helper" ]]; then
  echo "rollback entrypoint or transition lock helper is unsafe" >&2
  exit 73
fi
# shellcheck source=operations/scripts/transition-lock.sh
source "$transition_lock_helper"
if [[ "$transition_helper_identity" != "$(_mranked_bootstrap_stat "$transition_lock_helper")" \
      || "$MRANKED_TRANSITION_HELPER_PATH" != "$transition_lock_helper" ]]; then
  echo "transition lock helper changed while it was sourced" >&2
  exit 73
fi
unset -f _mranked_bootstrap_stat
unset transition_secure_file transition_secure_dir transition_metadata \
  transition_device transition_inode transition_owner transition_group \
  transition_mode transition_links transition_helper_identity

confirmation=""
if [[ "${1:-}" == "--confirm" && $# -eq 2 ]]; then
  confirmation="$2"
else
  echo "usage: $0 --confirm ROLLBACK:<ticket>" >&2
  exit 64
fi

: "${OPERATOR_ID:?OPERATOR_ID is required}"
: "${CHANGE_TICKET:?CHANGE_TICKET is required}"
: "${REVERSE_SYNC_EXECUTABLE:?REVERSE_SYNC_EXECUTABLE is required}"
: "${LEGACY_HEALTH_URL:=http://127.0.0.1:8090/health}"
: "${MRANKED_INSTALL_ROOT:=/opt/m-ranked/releases}"
: "${MRANKED_CURRENT_LINK:=/opt/m-ranked/current}"

if [[ "$confirmation" != "ROLLBACK:${CHANGE_TICKET}" ]]; then
  echo "confirmation mismatch" >&2
  exit 77
fi
if (( EUID != 0 )); then
  echo "rollback must run as root" >&2
  exit 77
fi
mranked_transition_lock_acquire
mranked_transition_require_active_entrypoint "$transition_entry_path"
mranked_transition_require_active_file \
  "$REVERSE_SYNC_EXECUTABLE" operations/bin/pg-to-legacy-sync true
for command_name in systemctl curl date install jq; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done

script_dir="$transition_entry_dir"
route_switch="$script_dir/switch-routing.sh"
mranked_transition_require_active_file \
  "$route_switch" operations/scripts/switch-routing.sh true

# Reads move first. No target data or release is removed.
"$route_switch" --phase legacy --confirm "ROUTE:legacy:${CHANGE_TICKET}"
systemctl stop \
  m-ranked-target-collector@telegram.service \
  m-ranked-target-collector@vk.service \
  m-ranked-target-collector@max.service \
  m-ranked-target-collector@rutube.service
systemctl stop m-ranked-target-reverse-sync.service

if [[ ! -x "$REVERSE_SYNC_EXECUTABLE" ]]; then
  echo "reverse-sync adapter is unavailable; legacy writer remains stopped to avoid split brain" >&2
  exit 1
fi
"$REVERSE_SYNC_EXECUTABLE" drain --operator "$OPERATOR_ID" --ticket "$CHANGE_TICKET"
"$REVERSE_SYNC_EXECUTABLE" verify
"$REVERSE_SYNC_EXECUTABLE" stop

systemctl start m-ranked-collector.service
if ! curl --fail --silent --show-error --max-time 15 "$LEGACY_HEALTH_URL" >/dev/null; then
  echo "legacy health failed after rollback" >&2
  exit 1
fi

state_dir=/var/lib/m-ranked/cutover
install -d -m 0700 "$state_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
state_file="$state_dir/rollback-$stamp.json"
jq -n --arg status pass --arg operator "$OPERATOR_ID" --arg ticket "$CHANGE_TICKET" \
  --arg completedAt "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{status:$status,operator:$operator,changeTicket:$ticket,completedAt:$completedAt,
    publicRoute:"legacy",targetCollectorsStopped:true,reverseSyncDrained:true,
    legacyCollectorStarted:true,targetDataDeleted:false}' >"$state_file"
chmod 0600 "$state_file"

echo "rollback completed without deleting target data state=$state_file"
