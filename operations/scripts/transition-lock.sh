#!/bin/bash -p
# Shared, source-only serialization and active-release helpers for production
# deployment/cutover entrypoints.  Production callers intentionally have no
# environment-variable override for the lock pathname, descriptor or flock
# executable.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "transition-lock.sh must be sourced by a production entrypoint" >&2
  exit 64
fi

readonly MRANKED_TRANSITION_LOCK_PATH=/run/lock/m-ranked-transition.lock
readonly MRANKED_TRANSITION_LOCK_DESCRIPTOR=8
readonly MRANKED_TRANSITION_FLOCK_BIN=/usr/bin/flock

_mranked_transition_helper_source="${BASH_SOURCE[0]}"
case "$_mranked_transition_helper_source" in
  /*) ;;
  *) _mranked_transition_helper_source="$(pwd -P)/$_mranked_transition_helper_source" ;;
esac
_mranked_transition_helper_dir="${_mranked_transition_helper_source%/*}"
_mranked_transition_helper_name="${_mranked_transition_helper_source##*/}"
_mranked_transition_helper_dir="$(
  cd -- "$_mranked_transition_helper_dir" && pwd -P
)" || {
  echo "cannot resolve transition-lock.sh origin" >&2
  return 73
}
readonly MRANKED_TRANSITION_HELPER_PATH="$_mranked_transition_helper_dir/$_mranked_transition_helper_name"
unset _mranked_transition_helper_source _mranked_transition_helper_dir \
  _mranked_transition_helper_name

_mranked_transition_stat() {
  local path="$1"
  local value
  value="$(/usr/bin/stat -c '%u:%g:%a:%h' -- "$path" 2>/dev/null)" \
    || value="$(/usr/bin/stat -f '%u:%g:%Lp:%l' "$path" 2>/dev/null)" \
    || return 1
  printf '%s\n' "$value"
}

_mranked_transition_stat_identity() {
  local path="$1"
  local value
  value="$(/usr/bin/stat -c '%d:%i:%u:%g:%a:%h' -- "$path" 2>/dev/null)" \
    || value="$(/usr/bin/stat -f '%d:%i:%u:%g:%Lp:%l' "$path" 2>/dev/null)" \
    || return 1
  printf '%s\n' "$value"
}

_mranked_transition_secure_directory() {
  local path="$1"
  local expected_uid="$2"
  local metadata
  local owner
  local group
  local mode
  local links
  local mode_value

  if [[ ! -d "$path" || -L "$path" ]]; then
    return 1
  fi
  metadata="$(_mranked_transition_stat "$path")" || return 1
  IFS=: read -r owner group mode links <<<"$metadata"
  if [[ "$owner" != "$expected_uid" || ! "$mode" =~ ^[0-7]{3,4}$ ]]; then
    return 1
  fi
  mode_value=$((8#$mode))
  (( (mode_value & 8#022) == 0 ))
}

_mranked_transition_secure_directory_chain() {
  local path="$1"
  local expected_uid="$2"
  local stop_path="${3:-/}"
  local canonical_path
  local canonical_stop
  local cursor="$path"

  if [[ "$path" != /* || "$stop_path" != /* ]]; then
    return 1
  fi
  canonical_path="$(/usr/bin/readlink -f -- "$path" 2>/dev/null)" || return 1
  canonical_stop="$(/usr/bin/readlink -f -- "$stop_path" 2>/dev/null)" \
    || return 1
  if [[ "$canonical_path" != "$path" || "$canonical_stop" != "$stop_path" ]]; then
    return 1
  fi
  if [[ "$stop_path" != / ]]; then
    case "$path" in
      "$stop_path"|"$stop_path"/*) ;;
      *) return 1 ;;
    esac
  fi
  while :; do
    if ! _mranked_transition_secure_directory "$cursor" "$expected_uid"; then
      return 1
    fi
    [[ "$cursor" == "$stop_path" ]] && break
    cursor="${cursor%/*}"
    [[ -n "$cursor" ]] || cursor=/
  done
}

_mranked_transition_directory_chain_identity() {
  local path="$1"
  local expected_uid="$2"
  local stop_path="${3:-/}"
  local cursor="$path"
  local metadata
  local device
  local inode
  local owner
  local group
  local mode
  local links

  _mranked_transition_secure_directory_chain \
    "$path" "$expected_uid" "$stop_path" \
    || return 1
  while :; do
    metadata="$(_mranked_transition_stat_identity "$cursor")" || return 1
    IFS=: read -r device inode owner group mode links <<<"$metadata"
    printf '%s|%s:%s:%s:%s:%s\n' \
      "$cursor" "$device" "$inode" "$owner" "$group" "$mode"
    [[ "$cursor" == "$stop_path" ]] && break
    cursor="${cursor%/*}"
    [[ -n "$cursor" ]] || cursor=/
  done
}

_mranked_transition_validate_lock_parent() {
  local lock_path="$1"
  local expected_uid="$2"
  local ancestor_stop="${3:-/}"
  local lock_parent="${lock_path%/*}"
  local lock_grandparent
  local lock_parent_real
  local metadata
  local owner
  local group
  local mode
  local links
  local mode_value

  if [[ "$lock_path" != /* || "$lock_parent" == "$lock_path" \
        || ! -d "$lock_parent" || -L "$lock_parent" ]]; then
    return 1
  fi
  lock_parent_real="$(/usr/bin/readlink -f -- "$lock_parent" 2>/dev/null)" \
    || return 1
  if [[ "$lock_parent_real" != "$lock_parent" ]]; then
    return 1
  fi
  metadata="$(_mranked_transition_stat "$lock_parent")" || return 1
  IFS=: read -r owner group mode links <<<"$metadata"
  if [[ "$owner" != "$expected_uid" || ! "$mode" =~ ^[0-7]{3,4}$ ]]; then
    return 1
  fi
  mode_value=$((8#$mode))
  # A writable group must be the trusted root group.  A world-writable lock
  # directory is acceptable only with sticky deletion protection (the normal
  # /run/lock layout on distributions that expose it that way).
  if (( (mode_value & 8#020) != 0 )) && [[ "$group" != 0 ]]; then
    return 1
  fi
  if (( (mode_value & 8#002) != 0 && (mode_value & 8#1000) == 0 )); then
    return 1
  fi
  if [[ "$lock_parent" != "$ancestor_stop" ]]; then
    lock_grandparent="${lock_parent%/*}"
    [[ -n "$lock_grandparent" ]] || lock_grandparent=/
    _mranked_transition_secure_directory_chain \
      "$lock_grandparent" "$expected_uid" "$ancestor_stop" || return 1
  fi
}

_mranked_transition_validate_lock_file() {
  local lock_path="$1"
  local expected_uid="$2"
  local metadata
  local owner
  local group
  local mode
  local links

  if [[ ! -f "$lock_path" || -L "$lock_path" ]]; then
    return 1
  fi
  metadata="$(_mranked_transition_stat "$lock_path")" || return 1
  IFS=: read -r owner group mode links <<<"$metadata"
  if [[ "$owner" != "$expected_uid" || "$links" != 1 \
        || ( "$mode" != 600 && "$mode" != 0600 ) ]]; then
    return 1
  fi
  return 0
}

_mranked_transition_fd_matches_lock() {
  local lock_path="$1"
  local fd_path="$2"
  local identity_mode="${3:-strict}"
  local lock_identity
  local fd_identity

  if [[ "$lock_path" -ef "$fd_path" ]]; then
    return 0
  fi
  # Darwin exposes /dev/fd on a synthetic device, so Bash -ef reports a false
  # negative.  This fallback is reachable only through the explicitly named
  # private test seam; the production wrapper always requests strict identity.
  if [[ "$identity_mode" != darwin-test ]]; then
    return 1
  fi
  lock_identity="$(/usr/bin/stat -f '%i:%u:%g:%z:%m:%c' "$lock_path" 2>/dev/null)" \
    || return 1
  fd_identity="$(/usr/bin/stat -f '%i:%u:%g:%z:%m:%c' "$fd_path" 2>/dev/null)" \
    || return 1
  [[ "$lock_identity" == "$fd_identity" ]]
}

# Private test seam: portable executable tests pass a protected temporary
# lock and a small flock-compatible helper.  Production entrypoints call only
# mranked_transition_lock_acquire, whose constants cannot be overridden.
_mranked_transition_lock_acquire() {
  local lock_path="$1"
  local flock_bin="$2"
  local expected_uid="$3"
  local fd_identity_mode="${4:-strict}"
  local lock_chain_stop="${5:-/}"
  local opened_here=false
  local flock_metadata
  local flock_owner
  local flock_group
  local flock_mode
  local flock_links
  local flock_mode_value

  if [[ "$flock_bin" != /* || ! -f "$flock_bin" || -L "$flock_bin" \
        || ! -x "$flock_bin" ]]; then
    echo "trusted flock executable is unavailable: $flock_bin" >&2
    return 69
  fi
  flock_metadata="$(_mranked_transition_stat "$flock_bin")" \
    || flock_metadata=""
  IFS=: read -r flock_owner flock_group flock_mode flock_links \
    <<<"$flock_metadata"
  if [[ "$flock_owner" != "$expected_uid" || "$flock_links" != 1 \
        || ! "$flock_mode" =~ ^[0-7]{3,4}$ ]] \
      || (( (8#$flock_mode & 8#022) != 0 )); then
    echo "trusted flock executable metadata is unsafe: $flock_bin" >&2
    return 69
  fi
  if ! _mranked_transition_validate_lock_parent \
      "$lock_path" "$expected_uid" "$lock_chain_stop"; then
    echo "transition lock parent is unsafe: ${lock_path%/*}" >&2
    return 73
  fi

  if [[ ! -e "$lock_path" && ! -L "$lock_path" ]]; then
    echo "transition lock is not provisioned: $lock_path" >&2
    return 73
  fi
  if ! _mranked_transition_validate_lock_file "$lock_path" "$expected_uid"; then
    echo "transition lock is unsafe: $lock_path" >&2
    return 73
  fi

  if [[ "${MRANKED_TRANSITION_LOCK_FD+x}" == x ]]; then
    if [[ "$MRANKED_TRANSITION_LOCK_FD" != "$MRANKED_TRANSITION_LOCK_DESCRIPTOR" \
          || ! -f "/dev/fd/$MRANKED_TRANSITION_LOCK_DESCRIPTOR" \
          ]] || ! _mranked_transition_fd_matches_lock \
            "$lock_path" "/dev/fd/$MRANKED_TRANSITION_LOCK_DESCRIPTOR" \
            "$fd_identity_mode"; then
      echo "inherited transition lock descriptor is invalid" >&2
      return 75
    fi
  else
    if ! exec 8<"$lock_path"; then
      echo "cannot open transition lock: $lock_path" >&2
      return 73
    fi
    opened_here=true
    if [[ ! -f "/dev/fd/$MRANKED_TRANSITION_LOCK_DESCRIPTOR" \
          ]] || ! _mranked_transition_fd_matches_lock \
            "$lock_path" "/dev/fd/$MRANKED_TRANSITION_LOCK_DESCRIPTOR" \
            "$fd_identity_mode"; then
      exec 8<&-
      echo "transition lock inode changed while opening" >&2
      return 73
    fi
  fi

  if ! "$flock_bin" -n -x "$MRANKED_TRANSITION_LOCK_DESCRIPTOR"; then
    if [[ "$opened_here" == true ]]; then
      exec 8<&-
    fi
    echo "another deployment or cutover transition is in progress" >&2
    return 75
  fi
  if ! _mranked_transition_validate_lock_file "$lock_path" "$expected_uid" \
      || ! _mranked_transition_fd_matches_lock \
        "$lock_path" "/dev/fd/$MRANKED_TRANSITION_LOCK_DESCRIPTOR" \
        "$fd_identity_mode"; then
    echo "transition lock inode changed after acquisition" >&2
    return 73
  fi
  export MRANKED_TRANSITION_LOCK_FD="$MRANKED_TRANSITION_LOCK_DESCRIPTOR"
}

mranked_transition_lock_acquire() {
  _mranked_transition_lock_acquire \
    "$MRANKED_TRANSITION_LOCK_PATH" \
    "$MRANKED_TRANSITION_FLOCK_BIN" \
    0
}

_mranked_transition_require_active_entrypoint() {
  local entry_path="$1"
  local install_root="$2"
  local current_link="$3"
  local expected_uid="$4"
  local current_parent="${current_link%/*}"
  local install_root_real
  local current_parent_real
  local raw_target
  local release_path
  local release_id
  local entry_name="${entry_path##*/}"
  local expected_entry
  local expected_helper
  local metadata
  local owner
  local group
  local mode
  local links
  local mode_value

  if [[ "$install_root" != /* || "$current_link" != /* \
        || "$entry_path" != /* ]]; then
    return 1
  fi
  install_root_real="$(/usr/bin/readlink -f -- "$install_root" 2>/dev/null)" \
    || return 1
  current_parent_real="$(/usr/bin/readlink -f -- "$current_parent" 2>/dev/null)" \
    || return 1
  if [[ "$install_root_real" != "$install_root" \
        || "$current_parent_real" != "$current_parent" \
        || ! -L "$current_link" \
        || ! -d "$install_root" || -L "$install_root" ]]; then
    return 1
  fi
  if ! _mranked_transition_secure_directory "$install_root" "$expected_uid" \
      || ! _mranked_transition_secure_directory "$current_parent" "$expected_uid"; then
    return 1
  fi

  raw_target="$(/usr/bin/readlink -- "$current_link" 2>/dev/null)" || return 1
  release_path="$(/usr/bin/readlink -f -- "$current_link" 2>/dev/null)" || return 1
  release_id="${release_path##*/}"
  if [[ "$raw_target" != "$release_path" \
        || "${release_path%/*}" != "$install_root" \
        || ! "$release_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ \
        || ! -d "$release_path" || -L "$release_path" \
        || ! -d "$release_path/operations" || -L "$release_path/operations" \
        || ! -d "$release_path/operations/scripts" \
        || -L "$release_path/operations/scripts" ]]; then
    return 1
  fi
  if ! _mranked_transition_secure_directory "$release_path" "$expected_uid" \
      || ! _mranked_transition_secure_directory \
        "$release_path/operations" "$expected_uid" \
      || ! _mranked_transition_secure_directory \
        "$release_path/operations/scripts" "$expected_uid"; then
    return 1
  fi

  case "$entry_name" in
    cutover-preflight.sh|switch-routing.sh|writer-cutover.sh|rollback.sh) ;;
    *) return 1 ;;
  esac
  expected_entry="$release_path/operations/scripts/$entry_name"
  expected_helper="$release_path/operations/scripts/transition-lock.sh"
  if [[ "$entry_path" != "$expected_entry" \
        || "$MRANKED_TRANSITION_HELPER_PATH" != "$expected_helper" \
        || ! -f "$entry_path" || -L "$entry_path" || ! -x "$entry_path" \
        || ! -f "$expected_helper" || -L "$expected_helper" ]]; then
    return 1
  fi
  for secure_file in "$entry_path" "$expected_helper"; do
    metadata="$(_mranked_transition_stat "$secure_file")" || return 1
    IFS=: read -r owner group mode links <<<"$metadata"
    if [[ "$owner" != "$expected_uid" || "$links" != 1 \
          || ! "$mode" =~ ^[0-7]{3,4}$ ]]; then
      return 1
    fi
    mode_value=$((8#$mode))
    if (( (mode_value & 8#022) != 0 )); then
      return 1
    fi
  done
  if [[ "$(/usr/bin/readlink -- "$current_link" 2>/dev/null)" != "$raw_target" \
        || "$(/usr/bin/readlink -f -- "$current_link" 2>/dev/null)" != "$release_path" ]]; then
    return 1
  fi
  if [[ "${MRANKED_ACTIVE_RELEASE_PATH+x}" == x \
        && "$MRANKED_ACTIVE_RELEASE_PATH" != "$release_path" ]]; then
    return 1
  fi
  export MRANKED_ACTIVE_RELEASE_PATH="$release_path"
}

mranked_transition_require_active_entrypoint() {
  local entry_path="$1"
  if [[ "${MRANKED_INSTALL_ROOT:-}" != /opt/m-ranked/releases \
        || "${MRANKED_CURRENT_LINK:-}" != /opt/m-ranked/current ]]; then
    echo "active release must use the exact production namespace" >&2
    return 73
  fi
  if ! _mranked_transition_secure_directory_chain \
      "$MRANKED_INSTALL_ROOT" 0 / \
      || ! _mranked_transition_secure_directory_chain \
        "${MRANKED_CURRENT_LINK%/*}" 0 /; then
    echo "active release namespace has an unsafe ancestor" >&2
    return 73
  fi
  if ! _mranked_transition_require_active_entrypoint \
      "$entry_path" "$MRANKED_INSTALL_ROOT" "$MRANKED_CURRENT_LINK" 0; then
    echo "entrypoint is not the canonical active-release copy: $entry_path" >&2
    return 73
  fi
}

_mranked_transition_require_active_file() {
  local candidate="$1"
  local relative_path="$2"
  local require_executable="${3:-false}"
  local expected_uid="$4"
  local candidate_parent="${candidate%/*}"
  local candidate_name="${candidate##*/}"
  local candidate_parent_real
  local candidate_real
  local expected
  local metadata
  local owner
  local group
  local mode
  local links
  local mode_value
  local secure_parent

  if [[ "${MRANKED_ACTIVE_RELEASE_PATH:-}" != /* \
        || ! "$relative_path" =~ ^[A-Za-z0-9._+@%/-]+$ \
        || "$relative_path" == /* || "$relative_path" == ../* \
        || "$relative_path" == */../* || "$relative_path" == */.. \
        || "$relative_path" == */./* || "$relative_path" == ./* ]]; then
    echo "active release sibling path is unsafe" >&2
    return 73
  fi
  if [[ "$(/usr/bin/readlink -- "$MRANKED_CURRENT_LINK" 2>/dev/null)" \
          != "$MRANKED_ACTIVE_RELEASE_PATH" \
        || "$(/usr/bin/readlink -f -- "$MRANKED_CURRENT_LINK" 2>/dev/null)" \
          != "$MRANKED_ACTIVE_RELEASE_PATH" ]]; then
    echo "active release changed while resolving a sibling" >&2
    return 73
  fi
  candidate_parent_real="$(
    cd -- "$candidate_parent" && pwd -P
  )" || return 73
  candidate_real="$candidate_parent_real/$candidate_name"
  expected="$MRANKED_ACTIVE_RELEASE_PATH/$relative_path"
  if [[ "$candidate_real" != "$expected" || ! -f "$candidate_real" \
        || -L "$candidate_real" ]]; then
    echo "required file is not from the captured active release: $relative_path" >&2
    return 73
  fi
  secure_parent="$candidate_parent_real"
  while :; do
    if ! _mranked_transition_secure_directory "$secure_parent" "$expected_uid"; then
      echo "required active-release directory is unsafe: $secure_parent" >&2
      return 73
    fi
    [[ "$secure_parent" == "$MRANKED_ACTIVE_RELEASE_PATH" ]] && break
    case "$secure_parent" in
      "$MRANKED_ACTIVE_RELEASE_PATH"/*) ;;
      *)
        echo "required file directory escapes the active release" >&2
        return 73
        ;;
    esac
    secure_parent="${secure_parent%/*}"
  done
  if [[ "$require_executable" == true && ! -x "$candidate_real" ]]; then
    echo "required active-release file is not executable: $relative_path" >&2
    return 69
  fi
  metadata="$(_mranked_transition_stat "$candidate_real")" || return 73
  IFS=: read -r owner group mode links <<<"$metadata"
  if [[ "$owner" != "$expected_uid" || "$links" != 1 \
        || ! "$mode" =~ ^[0-7]{3,4}$ ]]; then
    echo "required active-release file metadata is unsafe: $relative_path" >&2
    return 73
  fi
  mode_value=$((8#$mode))
  if (( (mode_value & 8#022) != 0 )); then
    echo "required active-release file is group/world writable: $relative_path" >&2
    return 73
  fi
  if [[ "$(/usr/bin/readlink -- "$MRANKED_CURRENT_LINK" 2>/dev/null)" \
          != "$MRANKED_ACTIVE_RELEASE_PATH" \
        || "$(/usr/bin/readlink -f -- "$MRANKED_CURRENT_LINK" 2>/dev/null)" \
          != "$MRANKED_ACTIVE_RELEASE_PATH" ]]; then
    echo "active release changed after resolving a sibling" >&2
    return 73
  fi
}

mranked_transition_require_active_file() {
  _mranked_transition_require_active_file "$1" "$2" "${3:-false}" 0
}
