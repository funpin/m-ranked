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
  echo "cannot resolve routing entrypoint origin" >&2
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
    echo "routing entrypoint or transition lock helper is unsafe" >&2
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
    echo "routing entrypoint directory chain is unsafe" >&2
    exit 73
  fi
  [[ "$transition_secure_dir" == / ]] && break
  transition_secure_dir="${transition_secure_dir%/*}"
  [[ -n "$transition_secure_dir" ]] || transition_secure_dir=/
done
if [[ ! -r "$transition_lock_helper" ]]; then
  echo "routing entrypoint or transition lock helper is unsafe" >&2
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

phase=""
confirmation=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase) phase="${2:-}"; shift 2 ;;
    --confirm) confirmation="${2:-}"; shift 2 ;;
    *) echo "usage: $0 --phase legacy|overview|public-read|writer-freeze --confirm TOKEN" >&2; exit 64 ;;
  esac
done

case "$phase" in
  legacy) route_file=phase-0-legacy.conf ;;
  overview) route_file=phase-1-overview.conf ;;
  public-read) route_file=phase-2-public-read.conf ;;
  writer-freeze) route_file=phase-3-writer-freeze.conf ;;
  *) echo "invalid routing phase" >&2; exit 64 ;;
esac

: "${CHANGE_TICKET:?CHANGE_TICKET is required}"
: "${OPERATOR_ID:?OPERATOR_ID is required}"
: "${NGINX_ACTIVE_ROUTES:=/etc/m-ranked/nginx/routes-active.conf}"
: "${NGINX_CONFIG:=/etc/nginx/nginx.conf}"
: "${NGINX_BIN:=/usr/sbin/nginx}"
: "${NGINX_ROUTE_LOCK:=/run/lock/m-ranked-routing.lock}"
: "${ROUTING_REPORT_DIR:=/var/lib/m-ranked/cutover}"
: "${MRANKED_INSTALL_ROOT:=/opt/m-ranked/releases}"
: "${MRANKED_CURRENT_LINK:=/opt/m-ranked/current}"

expected_confirmation="ROUTE:${phase}:${CHANGE_TICKET}"
if [[ "$confirmation" != "$expected_confirmation" ]]; then
  echo "confirmation mismatch; expected --confirm $expected_confirmation" >&2
  exit 77
fi
if (( EUID != 0 )); then
  echo "routing switch must run as root" >&2
  exit 77
fi

mranked_transition_lock_acquire
mranked_transition_require_active_entrypoint "$transition_entry_path"

script_dir="$transition_entry_dir"
source_file="$script_dir/../nginx/routes/$route_file"
preflight="$script_dir/cutover-preflight.sh"
mranked_transition_require_active_file \
  "$source_file" "operations/nginx/routes/$route_file"
mranked_transition_require_active_file \
  "$preflight" operations/scripts/cutover-preflight.sh true
if [[ ! -x "$NGINX_BIN" ]]; then
  echo "nginx executable is unavailable: $NGINX_BIN" >&2
  exit 69
fi
for command_name in install mktemp mv rm dirname systemctl flock jq date sha256sum chmod cut; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done

if [[ "$phase" == writer-freeze ]]; then
  "$preflight" --mode writer-cutover
elif [[ "$phase" != legacy ]]; then
  "$preflight" --mode public-read
fi

active_dir="$(dirname -- "$NGINX_ACTIVE_ROUTES")"
if [[ ! -d "$active_dir" || -L "$active_dir" \
      || ! -f "$NGINX_ACTIVE_ROUTES" || -L "$NGINX_ACTIVE_ROUTES" ]]; then
  echo "active nginx route path is unsafe or missing" >&2
  exit 73
fi
if [[ "$NGINX_ROUTE_LOCK" != /* || -L "$NGINX_ROUTE_LOCK" ]]; then
  echo "nginx route lock path is unsafe" >&2
  exit 73
fi
case "$ROUTING_REPORT_DIR" in
  /var/lib/m-ranked/*) ;;
  *) echo "ROUTING_REPORT_DIR must be below /var/lib/m-ranked" >&2; exit 64 ;;
esac
if [[ -L "$ROUTING_REPORT_DIR" ]]; then
  echo "routing report directory must not be a symlink" >&2
  exit 73
fi
exec 9>"$NGINX_ROUTE_LOCK"
if ! flock -n 9; then
  echo "another nginx routing change is in progress" >&2
  exit 75
fi

new_file="$(mktemp "$active_dir/.routes-new.XXXXXX")"
old_file="$(mktemp "$active_dir/.routes-old.XXXXXX")"
report_tmp=""
cleanup() {
  [[ -n "$new_file" && -f "$new_file" ]] && rm -f -- "$new_file"
  [[ -n "$old_file" && -f "$old_file" ]] && rm -f -- "$old_file"
  [[ -n "$report_tmp" && -f "$report_tmp" ]] && rm -f -- "$report_tmp"
}
trap cleanup EXIT

install -m 0644 "$source_file" "$new_file"
install -m 0644 "$NGINX_ACTIVE_ROUTES" "$old_file"
new_hash="$(sha256sum "$new_file" | cut -d' ' -f1)"
old_hash="$(sha256sum "$old_file" | cut -d' ' -f1)"

mv -- "$new_file" "$NGINX_ACTIVE_ROUTES"
new_file=""
if ! "$NGINX_BIN" -t -c "$NGINX_CONFIG"; then
  if [[ -n "$old_file" ]]; then
    mv -- "$old_file" "$NGINX_ACTIVE_ROUTES"
    old_file=""
  fi
  echo "nginx validation failed; prior routes restored" >&2
  exit 78
fi
if ! systemctl reload nginx.service; then
  if [[ -n "$old_file" ]]; then
    mv -- "$old_file" "$NGINX_ACTIVE_ROUTES"
    old_file=""
    "$NGINX_BIN" -t -c "$NGINX_CONFIG" && systemctl reload nginx.service || true
  fi
  echo "nginx reload failed; prior routes restored" >&2
  exit 75
fi

install -d -m 0700 "$ROUTING_REPORT_DIR"
completed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
report_tmp="$(mktemp "$ROUTING_REPORT_DIR/.route-report.XXXXXX")"
report_final="$ROUTING_REPORT_DIR/route-${phase}-${stamp}.json"
jq -n --arg status pass --arg phase "$phase" --arg operator "$OPERATOR_ID" \
  --arg ticket "$CHANGE_TICKET" --arg completedAt "$completed_at" \
  --arg previousSha256 "$old_hash" --arg activeSha256 "$new_hash" \
  '{status:$status,phase:$phase,operator:$operator,changeTicket:$ticket,
    completedAt:$completedAt,previousRouteSha256:$previousSha256,
    activeRouteSha256:$activeSha256,dnsChanged:false,upstreamChanged:false}' \
  >"$report_tmp"
chmod 0600 "$report_tmp"
mv -- "$report_tmp" "$report_final"

echo "routing phase=$phase operator=$OPERATOR_ID ticket=$CHANGE_TICKET report=$report_final"
