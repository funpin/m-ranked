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
  echo "cannot resolve deployment entrypoint origin" >&2
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
    echo "deployment entrypoint or transition lock helper is unsafe" >&2
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
    echo "deployment entrypoint directory chain is unsafe" >&2
    exit 73
  fi
  [[ "$transition_secure_dir" == / ]] && break
  transition_secure_dir="${transition_secure_dir%/*}"
  [[ -n "$transition_secure_dir" ]] || transition_secure_dir=/
done
if [[ ! -r "$transition_lock_helper" ]]; then
  echo "deployment entrypoint or transition lock helper is unsafe" >&2
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

release_source=""
release_id=""
operator=""
ticket=""
activate_shadow=false
confirmation=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-dir) release_source="${2:-}"; shift 2 ;;
    --release-id) release_id="${2:-}"; shift 2 ;;
    --operator) operator="${2:-}"; shift 2 ;;
    --ticket) ticket="${2:-}"; shift 2 ;;
    --activate-shadow) activate_shadow=true; shift ;;
    --confirm) confirmation="${2:-}"; shift 2 ;;
    *)
      echo "usage: $0 --release-dir DIR --release-id ID --operator ID --ticket ID [--activate-shadow --confirm TOKEN]" >&2
      exit 64
      ;;
  esac
done

if [[ ! "$release_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]]; then
  echo "release id is missing or unsafe" >&2
  exit 64
fi
if [[ -z "$operator" || -z "$ticket" ]]; then
  echo "named operator and approved change ticket are required" >&2
  exit 64
fi
case "$operator:$ticket" in
  *[Rr][Ee][Pp][Ll][Aa][Cc][Ee]-[Ww][Ii][Tt][Hh]-*)
    echo "operator and change ticket must not contain replace-with placeholders" >&2
    exit 64
    ;;
esac
if (( EUID != 0 )); then
  echo "deployment must run as root" >&2
  exit 77
fi
if [[ "$activate_shadow" == true \
      && "$confirmation" != "DEPLOY:${release_id}:${ticket}" ]]; then
  echo "activation requires --confirm DEPLOY:${release_id}:${ticket}" >&2
  exit 77
fi

mranked_transition_lock_acquire

: "${MRANKED_INSTALL_ROOT:=/opt/m-ranked/releases}"
: "${MRANKED_CURRENT_LINK:=/opt/m-ranked/current}"
: "${DEPLOY_REPORT_DIR:=/var/lib/m-ranked/deploy-reports}"
: "${FLYWAY_BIN:=/usr/local/bin/flyway}"
: "${FLYWAY_CONFIG_FILES:=/etc/m-ranked/credentials/flyway.conf}"
: "${TARGET_API_HEALTH_URL:=http://127.0.0.1:8080/api/v1/health/ready}"
: "${TARGET_WEB_HEALTH_URL:=http://127.0.0.1:3000/}"
: "${TARGET_ACTIVATION_GATE_SECONDS:=90}"

validate_deploy_namespace() {
  case "$MRANKED_INSTALL_ROOT:$MRANKED_CURRENT_LINK" in
    /opt/m-ranked/releases:/opt/m-ranked/current) ;;
    *)
      echo "install root and current link must use one exact production namespace" >&2
      return 64
      ;;
  esac
  if [[ "$DEPLOY_REPORT_DIR" != /var/lib/m-ranked/deploy-reports ]]; then
    echo "deploy report directory must be /var/lib/m-ranked/deploy-reports" >&2
    return 64
  fi
  current_parent="${MRANKED_CURRENT_LINK%/*}"
  if ! _mranked_transition_secure_directory_chain \
      "$MRANKED_INSTALL_ROOT" 0 / \
      || ! _mranked_transition_secure_directory_chain \
        "$current_parent" 0 / \
      || ! _mranked_transition_secure_directory_chain \
        "$DEPLOY_REPORT_DIR" 0 /; then
    echo "deployment namespace must be pre-provisioned, canonical, root-owned and non-writable" >&2
    return 73
  fi
}

capture_deploy_namespace_identity() {
  install_root_chain_identity="$(_mranked_transition_directory_chain_identity \
    "$MRANKED_INSTALL_ROOT" 0 /)" || return 73
  current_parent_chain_identity="$(_mranked_transition_directory_chain_identity \
    "$current_parent" 0 /)" || return 73
  report_dir_chain_identity="$(_mranked_transition_directory_chain_identity \
    "$DEPLOY_REPORT_DIR" 0 /)" || return 73
}

assert_deploy_namespace_stable() {
  local actual
  actual="$(_mranked_transition_directory_chain_identity \
    "$MRANKED_INSTALL_ROOT" 0 /)" || actual=""
  if [[ "$actual" != "$install_root_chain_identity" ]]; then
    echo "immutable release namespace changed during deployment" >&2
    return 73
  fi
  actual="$(_mranked_transition_directory_chain_identity \
    "$current_parent" 0 /)" || actual=""
  if [[ "$actual" != "$current_parent_chain_identity" ]]; then
    echo "current-link namespace changed during deployment" >&2
    return 73
  fi
  actual="$(_mranked_transition_directory_chain_identity \
    "$DEPLOY_REPORT_DIR" 0 /)" || actual=""
  if [[ "$actual" != "$report_dir_chain_identity" ]]; then
    echo "deploy-report namespace changed during deployment" >&2
    return 73
  fi
}

validate_deploy_namespace
capture_deploy_namespace_identity
assert_deploy_namespace_stable

for command_name in sha256sum install cp readlink ln mv systemctl curl jq date \
  cut find chmod chown dirname mktemp awk sort cmp rm sed sleep; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done
if [[ ! "$TARGET_ACTIVATION_GATE_SECONDS" =~ ^[1-9][0-9]*$ \
      || "$TARGET_ACTIVATION_GATE_SECONDS" -gt 900 ]]; then
  echo "TARGET_ACTIVATION_GATE_SECONDS must be between 1 and 900" >&2
  exit 64
fi
bind_release_source_to_entrypoint() {
  local requested_source="$1"
  if [[ ! -d "$requested_source" || -L "$requested_source" ]]; then
    echo "release source must be a real directory" >&2
    return 66
  fi
  artifact_root="$(readlink -f -- "$transition_entry_dir/../..")" || {
    echo "cannot resolve physical deployment artifact root" >&2
    return 73
  }
  canonical_release_source="$(readlink -f -- "$requested_source")" || {
    echo "cannot resolve release source" >&2
    return 66
  }
  if [[ "$artifact_root" == / \
        || "$transition_entry_path" \
          != "$artifact_root/operations/scripts/deploy-shadow.sh" \
        || "$requested_source" != "$canonical_release_source" \
        || "$canonical_release_source" != "$artifact_root" \
        || "${artifact_root##*/}" != "$release_id" ]]; then
    echo "release source must exactly equal the physical root containing this deploy entrypoint" >&2
    return 64
  fi
  release_source="$canonical_release_source"
}

bind_release_source_to_entrypoint "$release_source"
source_root_identity="$(_mranked_transition_stat_identity "$release_source")" \
  || exit 73
source_chain_identity="$(_mranked_transition_directory_chain_identity \
  "$release_source" 0 /)" || exit 73

validate_release_tree_trust() {
  local tree="$1"
  local expected_uid="${2:-0}"
  local inventory
  local candidate
  local metadata
  local device
  local inode
  local owner
  local group
  local mode
  local links
  local mode_value

  inventory="$(mktemp)"
  if ! find "$tree" -print0 >"$inventory"; then
    rm -f -- "$inventory"
    echo "cannot inventory release ownership and modes" >&2
    return 65
  fi
  while IFS= read -r -d '' candidate; do
    metadata="$(_mranked_transition_stat_identity "$candidate")" \
      || metadata=""
    IFS=: read -r device inode owner group mode links <<<"$metadata"
    if [[ "$owner" != "$expected_uid" || ! "$links" =~ ^[0-9]+$ \
          || ! "$mode" =~ ^[0-7]{3,4}$ ]]; then
      rm -f -- "$inventory"
      echo "release path has unsafe ownership or metadata: $candidate" >&2
      return 65
    fi
    mode_value=$((8#$mode))
    if [[ -L "$candidate" ]]; then
      if [[ "$links" != 1 ]]; then
        rm -f -- "$inventory"
        echo "release symlink must have one filesystem link: $candidate" >&2
        return 65
      fi
    elif [[ -f "$candidate" ]]; then
      if [[ "$links" != 1 ]] \
          || (( (mode_value & 8#7022) != 0 )); then
        rm -f -- "$inventory"
        echo "release file is hard-linked or writable/unexpected-mode: $candidate" >&2
        return 65
      fi
    elif [[ -d "$candidate" ]]; then
      if (( (mode_value & 8#7022) != 0 )); then
        rm -f -- "$inventory"
        echo "release directory is writable/unexpected-mode: $candidate" >&2
        return 65
      fi
    else
      rm -f -- "$inventory"
      echo "release contains an unsupported filesystem object: $candidate" >&2
      return 65
    fi
  done <"$inventory"
  rm -f -- "$inventory"
}

assert_release_source_stable() {
  local actual_root
  local actual_identity
  local actual_chain
  actual_root="$(readlink -f -- "$transition_entry_dir/../..")" \
    || actual_root=""
  actual_identity="$(_mranked_transition_stat_identity \
    "$release_source" 2>/dev/null)" || actual_identity=""
  actual_chain="$(_mranked_transition_directory_chain_identity \
    "$release_source" 0 / 2>/dev/null)" || actual_chain=""
  if [[ "$actual_root" != "$release_source" \
        || "$actual_identity" != "$source_root_identity" \
        || "$actual_chain" != "$source_chain_identity" ]]; then
    echo "physical release source changed during deployment" >&2
    return 73
  fi
  validate_release_tree_trust "$release_source"
}

secret_candidate="$(
  find "$release_source" -type f \
    \( -name '.env' -o -name '.env.*' -o -name '.pgpass' \
       -o -name '*private*.pem' -o -name '*privkey*.pem' \
       -o -name '*.key' -o -name 'id_rsa' -o -name 'id_ed25519' \
       -o -name '*.p12' \
       -o -name '*.pfx' -o -name '*.jks' -o -name '*.session' \
       -o -name '*.session-journal' -o -name '*.sqlite' \
       -o -name '*.sqlite3' -o -name '*.dump' \
       -o -path '*/credentials/*' \) \
    -print -quit
)"
if [[ -n "$secret_candidate" ]]; then
  echo "release contains a forbidden credential/data candidate: $secret_candidate" >&2
  exit 65
fi

required_files=(
  SHA256SUMS
  SYMLINKS.sha256
  backend/m-ranked-backend.jar
  backend/src/main/resources/db/migration/V1__target_baseline.sql
  backend/src/main/resources/db/migration/V2__rebuild_core_projections.sql
  backend/src/main/resources/db/migration/V3__collector_observation_times_and_identity_grants.sql
  backend/src/main/resources/db/migration/V4__admin_collection_run_status_grants.sql
  backend/src/main/resources/db/migration/V5__legacy_activity_period_projection.sql
  backend/src/main/resources/db/migration/V6__comparison_valid_observation_hourly_projection.sql
  backend/src/main/resources/db/migration/V7__activity_rating_read_grants.sql
  backend/src/main/resources/db/migration/V8__legacy_overview_projection.sql
  backend/src/main/resources/db/migration/V9__immutable_observations_quality_archive_fence.sql
  backend/src/main/resources/db/migration/V10__consistent_public_queries_and_formula_guards.sql
  backend/src/main/resources/db/migration/V11__bridge_identity_lineage_and_reconciliation.sql
  backend/src/main/resources/db/migration/V12__detail_history_projection.sql
  backend/src/main/resources/db/migration/V13__immutable_account_identity_history.sql
  backend/src/main/resources/db/migration/V14__public_archived_publication_text.sql
  backend/src/main/resources/db/migration/V15__verified_source_preservation.sql
  backend/src/main/resources/db/migration/V16__audited_catalog_commands.sql
  backend/src/main/resources/db/migration/V17__legacy_csv_compatibility_projection.sql
  backend/src/main/resources/db/migration/V18__official_rating_commands.sql
  backend/src/main/resources/db/migration/V19__safe_health_operational_snapshot.sql
  backend/src/main/resources/db/migration/V20__catalog_url_and_version_compatibility.sql
  backend/src/main/resources/db/migration/V21__legacy_period_first_observation_policy.sql
  backend/src/main/resources/db/migration/V22__durable_legacy_csv_archive_facts.sql
  backend/src/main/resources/db/migration/V23__official_rating_entity_context.sql
  backend/src/main/resources/db/migration/V24__ordered_history_reaction_details.sql
  backend/src/main/resources/db/migration/V25__safe_legacy_account_presentation.sql
  backend/src/main/resources/db/migration/V26__independent_projection_verifier_reads.sql
  backend/src/main/resources/db/migration/V27__retained_disabled_platform_period_metrics.sql
  backend/src/main/resources/db/migration/V28__identity_command_receipt_verifier_acl.sql
  backend/src/main/resources/db/migration/V29__monotonic_native_identity_transitions.sql
  backend/src/main/resources/db/migration/V30__preserve_legacy_forced_history_baseline.sql
  frontend/server.js
  .venv/bin/python
  collector_target/__main__.py
  collector_target/auth.py
  collector_target/evidence.py
  migration/release_manifest.py
  migration/bridge/reconciliation.py
  migration/bridge/preservation.py
  operations/env/projection-publisher.env.example
  operations/collector_parity_evidence.py
  operations/bin/collector-parity-evidence
  operations/bin/pg-to-legacy-sync
  operations/scripts/backup.sh
  operations/scripts/cache-outbox-worker.sh
  operations/scripts/collector-preflight.sh
  operations/scripts/cutover-preflight.sh
  operations/scripts/deploy-shadow.sh
  operations/scripts/restore-verify.sh
  operations/scripts/run-maintenance.sh
  operations/scripts/switch-routing.sh
  operations/scripts/transition-lock.sh
  operations/scripts/projection-publisher.sh
  operations/scripts/wal-archive.sh
  operations/scripts/writer-cutover.sh
  operations/scripts/rollback.sh
  operations/systemd/m-ranked-target-projection-publisher.service
  operations/tmpfiles.d/m-ranked-transition.conf
)
executable_files=(
  operations/bin/collector-parity-evidence
  operations/bin/pg-to-legacy-sync
  operations/scripts/backup.sh
  operations/scripts/cache-outbox-worker.sh
  operations/scripts/collector-preflight.sh
  operations/scripts/cutover-preflight.sh
  operations/scripts/deploy-shadow.sh
  operations/scripts/projection-publisher.sh
  operations/scripts/restore-verify.sh
  operations/scripts/rollback.sh
  operations/scripts/run-maintenance.sh
  operations/scripts/switch-routing.sh
  operations/scripts/wal-archive.sh
  operations/scripts/writer-cutover.sh
)
for relative_path in "${required_files[@]}"; do
  if [[ ! -e "$release_source/$relative_path" ]]; then
    echo "release artifact is incomplete: $relative_path" >&2
    exit 65
  fi
  if [[ "$relative_path" != .venv/bin/python \
        && ( ! -f "$release_source/$relative_path" \
             || -L "$release_source/$relative_path" ) ]]; then
    echo "required release artifact must be a regular non-symlink file: $relative_path" >&2
    exit 65
  fi
done
validate_executable_cohort() {
  local tree="$1"
  local expected_mode="${2:-safe}"
  local expected_uid="${3:-0}"
  local executable_path
  local metadata
  local device
  local inode
  local owner
  local group
  local mode
  local links

  for executable_path in "${executable_files[@]}"; do
    metadata="$(_mranked_transition_stat_identity \
      "$tree/$executable_path")" || metadata=""
    IFS=: read -r device inode owner group mode links <<<"$metadata"
    if [[ ! -f "$tree/$executable_path" \
          || -L "$tree/$executable_path" \
          || ! -x "$tree/$executable_path" \
          || "$owner" != "$expected_uid" || "$links" != 1 \
          || ! "$mode" =~ ^[0-7]{3,4}$ ]] \
        || (( (8#$mode & 8#7022) != 0 )); then
      echo "release executable cohort member is unsafe: $executable_path" >&2
      return 65
    fi
    if [[ "$expected_mode" == installed \
          && "$mode" != 755 && "$mode" != 0755 ]]; then
      echo "installed release executable has an unexpected mode: $executable_path" >&2
      return 65
    fi
  done
  if [[ ! -f "$tree/.venv/bin/python" \
        || ! -x "$tree/.venv/bin/python" ]]; then
    echo "release Python interpreter must resolve to an executable regular file" >&2
    return 65
  fi
}

assert_release_source_stable
validate_executable_cohort "$release_source"

expected_migration_files="$(printf '%s\n' \
  V10__consistent_public_queries_and_formula_guards.sql \
  V11__bridge_identity_lineage_and_reconciliation.sql \
  V12__detail_history_projection.sql \
  V13__immutable_account_identity_history.sql \
  V14__public_archived_publication_text.sql \
  V15__verified_source_preservation.sql \
  V16__audited_catalog_commands.sql \
  V17__legacy_csv_compatibility_projection.sql \
  V18__official_rating_commands.sql \
  V19__safe_health_operational_snapshot.sql \
  V1__target_baseline.sql \
  V20__catalog_url_and_version_compatibility.sql \
  V21__legacy_period_first_observation_policy.sql \
  V22__durable_legacy_csv_archive_facts.sql \
  V23__official_rating_entity_context.sql \
  V24__ordered_history_reaction_details.sql \
  V25__safe_legacy_account_presentation.sql \
  V26__independent_projection_verifier_reads.sql \
  V27__retained_disabled_platform_period_metrics.sql \
  V28__identity_command_receipt_verifier_acl.sql \
  V29__monotonic_native_identity_transitions.sql \
  V2__rebuild_core_projections.sql \
  V30__preserve_legacy_forced_history_baseline.sql \
  V3__collector_observation_times_and_identity_grants.sql \
  V4__admin_collection_run_status_grants.sql \
  V5__legacy_activity_period_projection.sql \
  V6__comparison_valid_observation_hourly_projection.sql \
  V7__activity_rating_read_grants.sql \
  V8__legacy_overview_projection.sql \
  V9__immutable_observations_quality_archive_fence.sql)"
actual_migration_files="$(
  cd -- "$release_source/backend/src/main/resources/db/migration"
  find . -mindepth 1 -maxdepth 1 -print | sed 's#^\./##' | sort
)"
if [[ "$actual_migration_files" != "$expected_migration_files" ]]; then
  echo "Flyway migration directory does not match the frozen V1-V30 manifest" >&2
  exit 65
fi

verify_release_tree() {
  local tree="$1"
  local manifest_paths
  local actual_paths
  local special_path
  manifest_paths="$(mktemp)"
  actual_paths="$(mktemp)"
  if ! awk '
      !/^[0-9a-f]{64} [ *][A-Za-z0-9._+@%\/-]+$/ { exit 1 }
      {
          path = substr($0, 67)
          if (path ~ /^\// || path ~ /(^|\/)\.\.?(\/|$)/ || seen[path]++) {
              exit 1
          }
          print path
      }
      END { if (NR == 0) exit 1 }
    ' "$tree/SHA256SUMS" | sort >"$manifest_paths"; then
    rm -f -- "$manifest_paths" "$actual_paths"
    echo "SHA256SUMS contains an unsafe, duplicate or malformed path" >&2
    return 65
  fi
  (
    cd -- "$tree"
    find . -type f ! -path './SHA256SUMS' -print \
      | sed 's#^\./##' \
      | sort
  ) >"$actual_paths"
  if ! cmp --silent "$manifest_paths" "$actual_paths"; then
    rm -f -- "$manifest_paths" "$actual_paths"
    echo "SHA256SUMS does not cover exactly every regular release file" >&2
    return 65
  fi
  rm -f -- "$manifest_paths" "$actual_paths"
  special_path="$(find "$tree" ! -type f ! -type d ! -type l -print -quit)"
  if [[ -n "$special_path" ]]; then
    echo "release contains a socket, device, FIFO or other special path" >&2
    return 65
  fi
  (
    cd -- "$tree"
    sha256sum --check --strict SHA256SUMS
  )
}

validate_release_symlinks() {
  local tree="$1"
  local symlink_manifest="$tree/SYMLINKS.sha256"
  local expected_records
  local actual_records
  local link_path
  local relative_path
  local raw_target
  local raw_target_after
  local raw_target_record
  local raw_target_record_after
  local resolved_path
  local resolved_path_after
  local target_path
  local target_parent_real
  local target_sha256
  local tree_real
  local symlink_manifest_sha256
  local symlink_manifest_sha256_after

  if [[ ! -f "$symlink_manifest" || -L "$symlink_manifest" \
        || ! -f "$tree/SHA256SUMS" || -L "$tree/SHA256SUMS" ]]; then
    echo "release requires regular non-symlink SHA256SUMS and SYMLINKS.sha256" >&2
    return 65
  fi
  tree_real="$(readlink -f -- "$tree")" || {
    echo "release root cannot be resolved for symlink verification" >&2
    return 65
  }
  expected_records="$(mktemp)"
  actual_records="$(mktemp)"
  symlink_manifest_sha256="$(
    sha256sum "$symlink_manifest" | cut -d' ' -f1
  )" || {
    rm -f -- "$expected_records" "$actual_records"
    return 65
  }
  if [[ ! "$symlink_manifest_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    rm -f -- "$expected_records" "$actual_records"
    return 65
  fi
  if ! LC_ALL=C awk '
      !/^[0-9a-f]{64}  [A-Za-z0-9._+@%\/-]+$/ { exit 1 }
      {
          path = substr($0, 67)
          if (path ~ /^\// || path ~ /(^|\/)\.\.?(\/|$)/ || seen[path]++) {
              exit 1
          }
          print $0
      }
    ' "$symlink_manifest" | LC_ALL=C sort >"$expected_records" \
      || ! cmp --silent "$symlink_manifest" "$expected_records"; then
    rm -f -- "$expected_records" "$actual_records"
    echo "SYMLINKS.sha256 is malformed, duplicate or not canonically sorted" >&2
    return 65
  fi
  if ! (
    cd -- "$tree" || exit 1
    find . -type l -print0 |
      while IFS= read -r -d '' link_path; do
        relative_path="${link_path#./}"
        raw_target_record="$(
          {
            readlink -- "$link_path" || exit 1
            printf '.'
          }
        )" || exit 1
        if [[ "$raw_target_record" != *$'\n.' ]]; then
          exit 1
        fi
        raw_target="${raw_target_record%$'\n.'}"
        if [[ ! "$relative_path" =~ ^[A-Za-z0-9._+@%/-]+$ \
              || "$relative_path" == /* \
              || "$relative_path" == . \
              || "$relative_path" == .. \
              || "$relative_path" == ../* \
              || "$relative_path" == */../* \
              || "$relative_path" == */.. \
              || ! "$raw_target" =~ ^[-A-Za-z0-9._+@%/=:,~]+$ ]]; then
          exit 1
        fi
        if [[ ! -e "$link_path" ]]; then
          exit 1
        fi
        if [[ "$raw_target" == /* ]]; then
          target_path="$raw_target"
        else
          target_path="${link_path%/*}/$raw_target"
        fi
        target_parent_real="$(
          readlink -f -- "$(dirname -- "$target_path")"
        )" || exit 1
        resolved_path="$(readlink -f -- "$link_path")" || exit 1
        case "$resolved_path" in
          "$tree_real"/*)
            if [[ "$raw_target" == /* ]]; then
              exit 1
            fi
            case "$target_parent_real" in
              "$tree_real"|"$tree_real"/*) ;;
              *) exit 1 ;;
            esac
            ;;
          *)
            case "$relative_path:$resolved_path" in
              .venv/bin/python:/usr/bin/python3.13|\
              .venv/bin/python:/usr/local/bin/python3.13|\
              .venv/bin/python3:/usr/bin/python3.13|\
              .venv/bin/python3:/usr/local/bin/python3.13|\
              .venv/bin/python3.13:/usr/bin/python3.13|\
              .venv/bin/python3.13:/usr/local/bin/python3.13) ;;
              *) exit 1 ;;
            esac
            if [[ "$raw_target" == /* ]]; then
              case "$raw_target" in
                /usr/bin/python3.13|/usr/local/bin/python3.13) ;;
                *) exit 1 ;;
              esac
            else
              case "$target_parent_real" in
                "$tree_real"|"$tree_real"/*) ;;
                *) exit 1 ;;
              esac
            fi
            ;;
        esac
        raw_target_record_after="$(
          {
            readlink -- "$link_path" || exit 1
            printf '.'
          }
        )" || exit 1
        if [[ "$raw_target_record_after" != *$'\n.' ]]; then
          exit 1
        fi
        raw_target_after="${raw_target_record_after%$'\n.'}"
        resolved_path_after="$(readlink -f -- "$link_path")" || exit 1
        if [[ "$raw_target_after" != "$raw_target" \
              || "$resolved_path_after" != "$resolved_path" ]]; then
          exit 1
        fi
        target_sha256="$(
          printf '%s' "$raw_target" | sha256sum | cut -d' ' -f1
        )" || exit 1
        if [[ ! "$target_sha256" =~ ^[0-9a-f]{64}$ ]]; then
          exit 1
        fi
        printf '%s  %s\n' "$target_sha256" "$relative_path"
      done
  ) | LC_ALL=C sort >"$actual_records"; then
    rm -f -- "$expected_records" "$actual_records"
    echo "release contains an unsafe, broken or unpinned symlink" >&2
    return 65
  fi
  if ! cmp --silent "$expected_records" "$actual_records"; then
    rm -f -- "$expected_records" "$actual_records"
    echo "release symlink paths or targets do not match SYMLINKS.sha256" >&2
    return 65
  fi
  symlink_manifest_sha256_after="$(
    sha256sum "$symlink_manifest" | cut -d' ' -f1
  )" || symlink_manifest_sha256_after=""
  if [[ "$symlink_manifest_sha256_after" != "$symlink_manifest_sha256" ]] \
      || ! LC_ALL=C awk -v sha256="$symlink_manifest_sha256" '
        $0 == sha256 "  SYMLINKS.sha256" \
          || $0 == sha256 " *SYMLINKS.sha256" { matches++ }
        END { exit(matches == 1 ? 0 : 1) }
      ' "$tree/SHA256SUMS"; then
    rm -f -- "$expected_records" "$actual_records"
    echo "SYMLINKS.sha256 changed or is not bound by SHA256SUMS" >&2
    return 65
  fi
  rm -f -- "$expected_records" "$actual_records"
}

capture_frozen_release_provenance() {
  local tree="$1"
  captured_manifest_sha256="$(sha256sum "$tree/SHA256SUMS" | cut -d' ' -f1)"
  captured_v1_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V1__target_baseline.sql" | cut -d' ' -f1)"
  captured_v2_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V2__rebuild_core_projections.sql" | cut -d' ' -f1)"
  captured_v3_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V3__collector_observation_times_and_identity_grants.sql" | cut -d' ' -f1)"
  captured_v4_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V4__admin_collection_run_status_grants.sql" | cut -d' ' -f1)"
  captured_v5_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V5__legacy_activity_period_projection.sql" | cut -d' ' -f1)"
  captured_v6_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V6__comparison_valid_observation_hourly_projection.sql" | cut -d' ' -f1)"
  captured_v7_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V7__activity_rating_read_grants.sql" | cut -d' ' -f1)"
  captured_v8_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V8__legacy_overview_projection.sql" | cut -d' ' -f1)"
  captured_v9_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V9__immutable_observations_quality_archive_fence.sql" | cut -d' ' -f1)"
  captured_v10_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V10__consistent_public_queries_and_formula_guards.sql" | cut -d' ' -f1)"
  captured_v11_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V11__bridge_identity_lineage_and_reconciliation.sql" | cut -d' ' -f1)"
  captured_v12_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V12__detail_history_projection.sql" | cut -d' ' -f1)"
  captured_v13_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V13__immutable_account_identity_history.sql" | cut -d' ' -f1)"
  captured_v14_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V14__public_archived_publication_text.sql" | cut -d' ' -f1)"
  captured_v15_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V15__verified_source_preservation.sql" | cut -d' ' -f1)"
  captured_v16_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V16__audited_catalog_commands.sql" | cut -d' ' -f1)"
  captured_v17_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V17__legacy_csv_compatibility_projection.sql" | cut -d' ' -f1)"
  captured_v18_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V18__official_rating_commands.sql" | cut -d' ' -f1)"
  captured_v19_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V19__safe_health_operational_snapshot.sql" | cut -d' ' -f1)"
  captured_v20_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V20__catalog_url_and_version_compatibility.sql" | cut -d' ' -f1)"
  captured_v21_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V21__legacy_period_first_observation_policy.sql" | cut -d' ' -f1)"
  captured_v22_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V22__durable_legacy_csv_archive_facts.sql" | cut -d' ' -f1)"
  captured_v23_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V23__official_rating_entity_context.sql" | cut -d' ' -f1)"
  captured_v24_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V24__ordered_history_reaction_details.sql" | cut -d' ' -f1)"
  captured_v25_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V25__safe_legacy_account_presentation.sql" | cut -d' ' -f1)"
  captured_v26_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V26__independent_projection_verifier_reads.sql" | cut -d' ' -f1)"
  captured_v27_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V27__retained_disabled_platform_period_metrics.sql" | cut -d' ' -f1)"
  captured_v28_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V28__identity_command_receipt_verifier_acl.sql" | cut -d' ' -f1)"
  captured_v29_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V29__monotonic_native_identity_transitions.sql" | cut -d' ' -f1)"
  captured_v30_sha256="$(sha256sum "$tree/backend/src/main/resources/db/migration/V30__preserve_legacy_forced_history_baseline.sql" | cut -d' ' -f1)"
  if [[ "$captured_v1_sha256" != dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1 \
        || "$captured_v2_sha256" != 113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd \
        || "$captured_v3_sha256" != 5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1 \
        || "$captured_v4_sha256" != d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82 \
        || "$captured_v5_sha256" != d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41 \
        || "$captured_v6_sha256" != 4ac99091046d40345c7024d3fab96ceb779fafb836c18c6a750f748f7bd29c64 \
        || "$captured_v7_sha256" != 95244a71a992fb8d9de387622224ddb52365120ac47c4d0cf4cbb20f4e36f0eb \
        || "$captured_v8_sha256" != dc855dde66a705808e1565e3f56c4555995d370805cee68ee9293ae7fa0aec9c \
        || "$captured_v9_sha256" != 2e165a561c9f839ec36af5bcc4c88b967778a9f11fb69e28dc71bbe5e053db50 \
        || "$captured_v10_sha256" != 126bc5263ecc56eb6a09342bc92f62bf74ef32d1bf1ca285e54454d7e9cf3b0b \
        || "$captured_v11_sha256" != 1e804126491b16f77be5af6db60ac45947d7ba782f5829de39f42d62f5240cff \
        || "$captured_v12_sha256" != 60dc3c9fd9d4997959f5b168e12f63a9553b93146023e826a0b57b607a43b100 \
        || "$captured_v13_sha256" != ab306bda84d76d4239e67d33232247c1d318d306ebd183962eda5d2b2a4b2cd0 \
        || "$captured_v14_sha256" != 261c257e7816c93ea84cb7d1318b711cbb0e6c518b30df57877cef92afb5f9e6 \
        || "$captured_v15_sha256" != 07891ccbeb0cfcf881b090f91c6efd2da5c0fc9fd45b49e4dc1bd9a90e15d941 \
        || "$captured_v16_sha256" != a350e3564567c4fd9e99ff69f0b541cc5de2d8c661dbb505c9efe4abfc2b35ad \
        || "$captured_v17_sha256" != 44696090aabda6ba3c971aa27b933b7f31a4d9392d2266d8294e158015a52b83 \
        || "$captured_v18_sha256" != 481fde448839a5a164cf7aea16d9c109126f0005fb227d97ab8e2b521b4e60c9 \
        || "$captured_v19_sha256" != 85cb7579c6c1c91f47a250014f4d522a4a2e9a3d785afbe490516d5b5f86a503 \
        || "$captured_v20_sha256" != e8e96cf550e31311a0d0b96a915c09bf4f93cec69ff3cce84b932dbd29cb4aa2 \
        || "$captured_v21_sha256" != 6270ec9827ec901728b309eb537f06ab4f2487d541bd4b8e32f92c26cc840ba8 \
        || "$captured_v22_sha256" != a645b247e1fd6055e17e05636f7f0ec05ed240ac95106178fc7fdfe9d5c0921f \
        || "$captured_v23_sha256" != dcea6278b2c218803984d27e4828fcb8f7d42af34cf357e619b7ae93768b652c \
        || "$captured_v24_sha256" != 0f0886c8804b7bc4329c7f7461322ad9eb62924412cac02b24caca06942863db \
        || "$captured_v25_sha256" != c6497ad2f0bd4ceeb39efff48ad62cbbf625d64969cd68b15dd36e30031d7fa1 \
        || "$captured_v26_sha256" != 1ff9ed8a785641972a290b7f9fcc48dff6e1130fdf7e83d0adf9e572b9b96ea8 \
        || "$captured_v27_sha256" != 95736d8f4d4f7be9c5904f7118b85532e508f93b6fc94130e5395fb31e92ed97 \
        || "$captured_v28_sha256" != 215a382daced28ca93dd6580f68c768ee050964fc57ab9591d76b63da5c83020 \
        || "$captured_v29_sha256" != b608a4ccfa204348033203bdd9b6dd3eea2b0d79ff72f2af8fbb776687b095de \
        || "$captured_v30_sha256" != 79b4fa544c534f5c6794f99addd33827452300c55435721658799c1a8ae9ce46 ]]; then
    echo "frozen Flyway V1-V30 checksum mismatch" >&2
    return 65
  fi
}

release_directory_inode_identity() {
  local path="$1"
  local metadata
  local device
  local inode
  local owner
  local group
  local mode
  local links
  metadata="$(_mranked_transition_stat_identity "$path")" || return 1
  IFS=: read -r device inode owner group mode links <<<"$metadata"
  if [[ ! -d "$path" || -L "$path" || ! "$device" =~ ^[0-9]+$ \
        || ! "$inode" =~ ^[0-9]+$ ]]; then
    return 1
  fi
  printf '%s:%s\n' "$device" "$inode"
}

assert_installed_release_stable() {
  local actual_identity
  assert_deploy_namespace_stable || return
  actual_identity="$(_mranked_transition_stat_identity \
    "$release_path" 2>/dev/null)" || actual_identity=""
  if [[ "$actual_identity" != "$installed_release_identity" \
        || ! -d "$release_path" || -L "$release_path" ]] \
      || ! _mranked_transition_secure_directory_chain "$release_path" 0 /; then
    echo "installed release path changed during deployment" >&2
    return 73
  fi
}

assert_active_release_ready_for_report() {
  local current_real
  local current_raw
  assert_installed_release_stable || return
  current_real="$(readlink -f -- "$MRANKED_CURRENT_LINK" 2>/dev/null)" \
    || current_real=""
  current_raw="$(readlink -- "$MRANKED_CURRENT_LINK" 2>/dev/null)" \
    || current_raw=""
  if [[ "$current_real" != "$release_path" || "$current_raw" != "$release_path" ]] \
      || ! validate_release_tree_trust "$release_path" \
      || ! validate_executable_cohort "$release_path" installed \
      || ! verify_release_tree "$release_path" \
      || ! validate_release_symlinks "$release_path" \
      || ! capture_frozen_release_provenance "$release_path" \
      || [[ "$captured_manifest_sha256" != "$release_manifest_sha256" ]]; then
    echo "active release changed before pass-report publication" >&2
    return 75
  fi
}

verify_release_tree "$release_source"
validate_release_symlinks "$release_source"
capture_frozen_release_provenance "$release_source"
source_manifest_sha256="$captured_manifest_sha256"
assert_release_source_stable
validate_executable_cohort "$release_source"

assert_deploy_namespace_stable
release_path="$MRANKED_INSTALL_ROOT/$release_id"
if [[ -e "$release_path" || -L "$release_path" ]]; then
  echo "release destination already exists; immutable releases are never overwritten" >&2
  exit 73
fi
staging_path="$(mktemp -d "$MRANKED_INSTALL_ROOT/.${release_id}.staging.XXXXXX")"
staging_inode_identity="$(release_directory_inode_identity "$staging_path")" \
  || exit 73
report_incomplete_stage() {
  if [[ -n "${staging_path:-}" && -d "$staging_path" ]]; then
    echo "incomplete release retained for operator inspection: $staging_path" >&2
  fi
}
trap report_incomplete_stage EXIT

cp -a --no-preserve=ownership -- "$release_source/." "$staging_path/"
assert_deploy_namespace_stable
if [[ "$(release_directory_inode_identity "$staging_path")" \
      != "$staging_inode_identity" ]]; then
  echo "staging release path changed during copy" >&2
  exit 73
fi
assert_release_source_stable
verify_release_tree "$staging_path"
validate_release_symlinks "$staging_path"
capture_frozen_release_provenance "$staging_path"
if [[ "$captured_manifest_sha256" != "$source_manifest_sha256" ]]; then
  echo "release source changed while the immutable staging copy was created" >&2
  exit 65
fi
staged_manifest_sha256="$captured_manifest_sha256"
install -d -m 0755 "$staging_path/frontend/.next/cache"
chown -hR root:root -- "$staging_path"
find "$staging_path" -type d -exec chmod 0755 {} +
find "$staging_path" -type f -exec chmod 0644 {} +
for relative_path in "${executable_files[@]}"; do
  chmod 0755 "$staging_path/$relative_path"
done
if [[ ! -L "$staging_path/.venv/bin/python" ]]; then
  chmod 0755 "$staging_path/.venv/bin/python"
fi
validate_release_tree_trust "$staging_path"
validate_executable_cohort "$staging_path" installed
assert_release_source_stable
assert_deploy_namespace_stable
if [[ "$(release_directory_inode_identity "$staging_path")" \
      != "$staging_inode_identity" \
      || -e "$release_path" || -L "$release_path" ]]; then
  echo "staging or installed release path changed before activation" >&2
  exit 73
fi
mv -T -- "$staging_path" "$release_path"
if [[ "$(release_directory_inode_identity "$release_path")" \
      != "$staging_inode_identity" ]]; then
  echo "installed release does not match the verified staging inode" >&2
  exit 73
fi
staging_path=""
trap - EXIT

installed_release_identity="$(_mranked_transition_stat_identity "$release_path")" \
  || exit 73
assert_installed_release_stable
validate_release_tree_trust "$release_path"
validate_executable_cohort "$release_path" installed
verify_release_tree "$release_path"
validate_release_symlinks "$release_path"
capture_frozen_release_provenance "$release_path"
if [[ "$captured_manifest_sha256" != "$staged_manifest_sha256" ]]; then
  echo "installed release provenance differs from its verified staging tree" >&2
  exit 65
fi
release_manifest_sha256="$captured_manifest_sha256"
v1_hash="$captured_v1_sha256"
v2_hash="$captured_v2_sha256"
v3_hash="$captured_v3_sha256"
v4_hash="$captured_v4_sha256"
v5_hash="$captured_v5_sha256"
v6_hash="$captured_v6_sha256"
v7_hash="$captured_v7_sha256"
v8_hash="$captured_v8_sha256"
v9_hash="$captured_v9_sha256"
v10_hash="$captured_v10_sha256"
v11_hash="$captured_v11_sha256"
v12_hash="$captured_v12_sha256"
v13_hash="$captured_v13_sha256"
v14_hash="$captured_v14_sha256"
v15_hash="$captured_v15_sha256"
v16_hash="$captured_v16_sha256"
v17_hash="$captured_v17_sha256"
v18_hash="$captured_v18_sha256"
v19_hash="$captured_v19_sha256"
v20_hash="$captured_v20_sha256"
v21_hash="$captured_v21_sha256"
v22_hash="$captured_v22_sha256"
v23_hash="$captured_v23_sha256"
v24_hash="$captured_v24_sha256"
v25_hash="$captured_v25_sha256"
v26_hash="$captured_v26_sha256"
v27_hash="$captured_v27_sha256"
v28_hash="$captured_v28_sha256"
v29_hash="$captured_v29_sha256"
v30_hash="$captured_v30_sha256"
assert_installed_release_stable

if [[ "$activate_shadow" == false ]]; then
  echo "release staged path=$release_path operator=$operator ticket=$ticket"
  exit 0
fi

if [[ ! -x "$FLYWAY_BIN" || ! -r "$FLYWAY_CONFIG_FILES" ]]; then
  echo "Flyway executable or migration-owner credential file is unavailable" >&2
  exit 69
fi

previous_release=""
if [[ -L "$MRANKED_CURRENT_LINK" ]]; then
  previous_release="$(readlink -f -- "$MRANKED_CURRENT_LINK")"
  previous_release_target="$(readlink -- "$MRANKED_CURRENT_LINK")"
  case "$previous_release" in
    "$MRANKED_INSTALL_ROOT"/*) ;;
    *) echo "current release symlink escapes the immutable release root" >&2; exit 73 ;;
  esac
  if [[ "$previous_release_target" != "$previous_release" \
        || "${previous_release#"$MRANKED_INSTALL_ROOT"/}" == */* \
        || ! -d "$previous_release" || -L "$previous_release" ]] \
      || ! _mranked_transition_secure_directory_chain "$previous_release" 0 /; then
    echo "current release link is indirect, dangling or unsafe" >&2
    exit 73
  fi
elif [[ -e "$MRANKED_CURRENT_LINK" ]]; then
  echo "current release path exists but is not an atomic symlink" >&2
  exit 73
fi

migration_location="filesystem:$release_path/backend/src/main/resources/db/migration"
assert_installed_release_stable
"$FLYWAY_BIN" -configFiles="$FLYWAY_CONFIG_FILES" \
  -locations="$migration_location" validate
assert_installed_release_stable
"$FLYWAY_BIN" -configFiles="$FLYWAY_CONFIG_FILES" \
  -locations="$migration_location" migrate
assert_installed_release_stable
"$FLYWAY_BIN" -configFiles="$FLYWAY_CONFIG_FILES" \
  -locations="$migration_location" validate
assert_installed_release_stable
flyway_info_json="$(
  "$FLYWAY_BIN" -configFiles="$FLYWAY_CONFIG_FILES" \
    -locations="$migration_location" info -outputType=json
)"
assert_installed_release_stable
if ! jq -e '
    .schemaVersion == "30"
    and (.migrations | type) == "array"
    and (.migrations | length) == 30
    and ([.migrations[] | .version] | sort)
        == ["1", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "2", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "3", "30", "4", "5", "6", "7", "8", "9"]
    and all(.migrations[]; .category == "Versioned" and .state == "Success")
  ' <<<"$flyway_info_json" >/dev/null; then
  echo "Flyway schema version/count/state does not match frozen V1-V30" >&2
  exit 65
fi
flyway_engine_version="$(jq -r '.flywayVersion // empty' <<<"$flyway_info_json")"
if [[ -z "$flyway_engine_version" ]]; then
  echo "Flyway info did not report its engine version" >&2
  exit 65
fi

assert_installed_release_stable
next_link="$MRANKED_CURRENT_LINK.next"
if [[ -e "$next_link" || -L "$next_link" ]]; then
  echo "stale next-release link exists: $next_link" >&2
  exit 73
fi
ln -s -- "$release_path" "$next_link"
assert_installed_release_stable
mv -Tf -- "$next_link" "$MRANKED_CURRENT_LINK"

activation_failed=false
if ! assert_installed_release_stable; then
  activation_failed=true
fi
if [[ "$activation_failed" == false ]]; then
  systemctl daemon-reload || activation_failed=true
fi
if [[ "$activation_failed" == false ]]; then
  systemctl restart m-ranked-target-projection-publisher.service \
    m-ranked-target-api.service m-ranked-target-web.service \
    m-ranked-target-cache-outbox.service || activation_failed=true
fi
if [[ "$activation_failed" == false ]]; then
  activation_deadline=$(( $(date -u +%s) + TARGET_ACTIVATION_GATE_SECONDS ))
  activation_healthy=false
  while (( $(date -u +%s) < activation_deadline )); do
    if ! systemctl is-active --quiet m-ranked-target-projection-publisher.service; then
      activation_failed=true
      break
    fi
    if curl --fail --silent --show-error --max-time 15 \
        "$TARGET_API_HEALTH_URL" >/dev/null \
        && curl --fail --silent --show-error --max-time 15 \
        "$TARGET_WEB_HEALTH_URL" >/dev/null; then
      activation_healthy=true
      break
    fi
    sleep 2
  done
  if [[ "$activation_healthy" != true ]]; then
    activation_failed=true
  fi
fi

if [[ "$activation_failed" == false ]]; then
  if ! assert_installed_release_stable; then
    activation_failed=true
  fi
fi

if [[ "$activation_failed" == false ]]; then
  active_release_path="$(readlink -f -- "$MRANKED_CURRENT_LINK")" \
    || active_release_path=""
  active_release_target="$(readlink -- "$MRANKED_CURRENT_LINK")" \
    || active_release_target=""
  if [[ "$active_release_path" != "$release_path" \
        || "$active_release_target" != "$release_path" ]]; then
    activation_failed=true
  elif ! validate_release_tree_trust "$release_path" \
      || ! validate_executable_cohort "$release_path" installed \
      || ! verify_release_tree "$release_path" \
      || ! validate_release_symlinks "$release_path" \
      || ! capture_frozen_release_provenance "$release_path"; then
    activation_failed=true
  elif [[ "$captured_manifest_sha256" != "$release_manifest_sha256" ]]; then
    activation_failed=true
  else
    release_manifest_sha256="$captured_manifest_sha256"
    v1_hash="$captured_v1_sha256"
    v2_hash="$captured_v2_sha256"
    v3_hash="$captured_v3_sha256"
    v4_hash="$captured_v4_sha256"
    v5_hash="$captured_v5_sha256"
    v6_hash="$captured_v6_sha256"
    v7_hash="$captured_v7_sha256"
    v8_hash="$captured_v8_sha256"
    v9_hash="$captured_v9_sha256"
    v10_hash="$captured_v10_sha256"
    v11_hash="$captured_v11_sha256"
    v12_hash="$captured_v12_sha256"
    v13_hash="$captured_v13_sha256"
    v14_hash="$captured_v14_sha256"
    v15_hash="$captured_v15_sha256"
    v16_hash="$captured_v16_sha256"
    v17_hash="$captured_v17_sha256"
    v18_hash="$captured_v18_sha256"
    v19_hash="$captured_v19_sha256"
    v20_hash="$captured_v20_sha256"
    v21_hash="$captured_v21_sha256"
    v22_hash="$captured_v22_sha256"
    v23_hash="$captured_v23_sha256"
    v24_hash="$captured_v24_sha256"
    v25_hash="$captured_v25_sha256"
    v26_hash="$captured_v26_sha256"
    v27_hash="$captured_v27_sha256"
    v28_hash="$captured_v28_sha256"
    v29_hash="$captured_v29_sha256"
    v30_hash="$captured_v30_sha256"
  fi
fi

if [[ "$activation_failed" == true ]]; then
  if [[ -n "$previous_release" && -d "$previous_release" ]]; then
    systemctl stop m-ranked-target-projection-publisher.service || true
    rollback_link="$MRANKED_CURRENT_LINK.rollback.$BASHPID"
    ln -s -- "$previous_release" "$rollback_link"
    mv -Tf -- "$rollback_link" "$MRANKED_CURRENT_LINK"
    systemctl restart m-ranked-target-api.service m-ranked-target-web.service \
      m-ranked-target-cache-outbox.service || true
  else
    systemctl stop m-ranked-target-api.service m-ranked-target-web.service \
      m-ranked-target-cache-outbox.service \
      m-ranked-target-projection-publisher.service || true
    failed_link="$MRANKED_CURRENT_LINK.failed-$release_id.$BASHPID"
    mv -- "$MRANKED_CURRENT_LINK" "$failed_link"
  fi
  echo "shadow activation failed; routing and legacy units were not changed" >&2
  exit 75
fi

assert_active_release_ready_for_report
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
report="$DEPLOY_REPORT_DIR/deploy-${release_id}.json"
report_sidecar="$report.sha256"
if [[ -e "$report" || -L "$report" \
      || -e "$report_sidecar" || -L "$report_sidecar" ]]; then
  echo "release-scoped deploy report already exists" >&2
  exit 73
fi
report_tmp="$(mktemp "$DEPLOY_REPORT_DIR/.deploy-${release_id}.json.XXXXXX")"
jq -n \
  --arg status pass --arg releaseId "$release_id" --arg releasePath "$release_path" \
  --arg releaseManifestSha256 "$release_manifest_sha256" \
  --arg previousRelease "$previous_release" --arg operator "$operator" \
  --arg ticket "$ticket" --arg finishedAt "$finished_at" \
  --arg v1Sha256 "$v1_hash" \
  --arg v2Sha256 "$v2_hash" \
  --arg v3Sha256 "$v3_hash" \
  --arg v4Sha256 "$v4_hash" \
  --arg v5Sha256 "$v5_hash" \
  --arg v6Sha256 "$v6_hash" \
  --arg v7Sha256 "$v7_hash" \
  --arg v8Sha256 "$v8_hash" \
  --arg v9Sha256 "$v9_hash" \
  --arg v10Sha256 "$v10_hash" \
  --arg v11Sha256 "$v11_hash" \
  --arg v12Sha256 "$v12_hash" \
  --arg v13Sha256 "$v13_hash" \
  --arg v14Sha256 "$v14_hash" \
  --arg v15Sha256 "$v15_hash" \
  --arg v16Sha256 "$v16_hash" \
  --arg v17Sha256 "$v17_hash" \
  --arg v18Sha256 "$v18_hash" \
  --arg v19Sha256 "$v19_hash" \
  --arg v20Sha256 "$v20_hash" \
  --arg v21Sha256 "$v21_hash" \
  --arg v22Sha256 "$v22_hash" \
  --arg v23Sha256 "$v23_hash" \
  --arg v24Sha256 "$v24_hash" \
  --arg v25Sha256 "$v25_hash" \
  --arg v26Sha256 "$v26_hash" \
  --arg v27Sha256 "$v27_hash" \
  --arg v28Sha256 "$v28_hash" \
  --arg v29Sha256 "$v29_hash" \
  --arg v30Sha256 "$v30_hash" \
  --arg flywayVersion "$flyway_engine_version" \
  '{status:$status,releaseId:$releaseId,
    releaseManifestSha256:$releaseManifestSha256,releasePath:$releasePath,
    previousRelease:(if $previousRelease=="" then null else $previousRelease end),
    operator:$operator,changeTicket:$ticket,finishedAt:$finishedAt,
    flyway:{schemaVersion:"30",migrationCount:30,engineVersion:$flywayVersion,
      v1Sha256:$v1Sha256,v2Sha256:$v2Sha256,v3Sha256:$v3Sha256,v4Sha256:$v4Sha256,v5Sha256:$v5Sha256,v6Sha256:$v6Sha256,v7Sha256:$v7Sha256,v8Sha256:$v8Sha256,v9Sha256:$v9Sha256,v10Sha256:$v10Sha256,v11Sha256:$v11Sha256,v12Sha256:$v12Sha256,v13Sha256:$v13Sha256,v14Sha256:$v14Sha256,v15Sha256:$v15Sha256,v16Sha256:$v16Sha256,v17Sha256:$v17Sha256,v18Sha256:$v18Sha256,v19Sha256:$v19Sha256,v20Sha256:$v20Sha256,v21Sha256:$v21Sha256,v22Sha256:$v22Sha256,v23Sha256:$v23Sha256,v24Sha256:$v24Sha256,v25Sha256:$v25Sha256,v26Sha256:$v26Sha256,v27Sha256:$v27Sha256,v28Sha256:$v28Sha256,v29Sha256:$v29Sha256,v30Sha256:$v30Sha256,validated:true},
    projectionPublisherActive:true,
    publicRoutingChanged:false,legacyUnitsChanged:false}' >"$report_tmp"
chmod 0600 "$report_tmp"
report_sidecar_tmp="$(mktemp "$DEPLOY_REPORT_DIR/.deploy-${release_id}.sha256.XXXXXX")"
report_sha256="$(sha256sum "$report_tmp" | cut -d' ' -f1)"
printf '%s  %s\n' "$report_sha256" "$report" >"$report_sidecar_tmp"
chmod 0600 "$report_sidecar_tmp"
assert_installed_release_stable
if [[ -e "$report" || -L "$report" \
      || -e "$report_sidecar" || -L "$report_sidecar" ]]; then
  echo "release-scoped deploy report appeared during publication" >&2
  exit 73
fi
mv -T -- "$report_tmp" "$report"
mv -T -- "$report_sidecar_tmp" "$report_sidecar"
current_report_tmp="$(mktemp "$DEPLOY_REPORT_DIR/.current.XXXXXX")"
install -m 0600 "$report" "$current_report_tmp"
current_sidecar_tmp="$(mktemp "$DEPLOY_REPORT_DIR/.current.sha256.XXXXXX")"
printf '%s  %s\n' "$report_sha256" "$DEPLOY_REPORT_DIR/current.json" \
  >"$current_sidecar_tmp"
chmod 0600 "$current_sidecar_tmp"
assert_installed_release_stable
mv -Tf -- "$current_report_tmp" "$DEPLOY_REPORT_DIR/current.json"
mv -Tf -- "$current_sidecar_tmp" "$DEPLOY_REPORT_DIR/current.json.sha256"

echo "shadow release active release=$release_id operator=$operator ticket=$ticket report=$report"
