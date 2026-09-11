#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

if [[ $# -ne 1 ]]; then
  echo "usage: $0 telegram|vk|max|rutube" >&2
  exit 64
fi
platform="$1"
case "$platform" in
  telegram|vk|max|rutube) ;;
  *) echo "unsupported collector platform" >&2; exit 64 ;;
esac

for command_name in id stat dirname; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done

require_private_writable_file() {
  local path="$1"
  local label="$2"
  if [[ "$path" != /* || ! -s "$path" || ! -f "$path" || -L "$path" \
        || ! -r "$path" || ! -w "$path" ]]; then
    echo "$label must be a nonempty private writable regular file" >&2
    exit 77
  fi
  if [[ "$(stat -c %u "$path")" != "$(id -u)" \
        || "$(stat -c %a "$path")" != 600 ]]; then
    echo "$label must be owned by the collector UID with mode 0600" >&2
    exit 77
  fi
  local parent
  parent="$(dirname -- "$path")"
  if [[ ! -d "$parent" || -L "$parent" || ! -r "$parent" \
        || ! -w "$parent" || ! -x "$parent" \
        || "$(stat -c %u "$parent")" != "$(id -u)" \
        || "$(stat -c %a "$parent")" != 700 ]]; then
    echo "$label parent directory is not private writable state" >&2
    exit 77
  fi
}

case "$platform" in
  telegram)
    case "${DATA_SOURCE:-mtproto}" in
      public_web) ;;
      mtproto)
        : "${TELEGRAM_SESSION_PATH:?TELEGRAM_SESSION_PATH is required}"
        require_private_writable_file "$TELEGRAM_SESSION_PATH" "Telegram session"
        ;;
      telegram_web)
        : "${TELEGRAM_WEB_PROFILE_PATH:?TELEGRAM_WEB_PROFILE_PATH is required}"
        if [[ "$TELEGRAM_WEB_PROFILE_PATH" != /* \
              || ! -d "$TELEGRAM_WEB_PROFILE_PATH" \
              || -L "$TELEGRAM_WEB_PROFILE_PATH" \
              || ! -r "$TELEGRAM_WEB_PROFILE_PATH" \
              || ! -w "$TELEGRAM_WEB_PROFILE_PATH" \
              || ! -x "$TELEGRAM_WEB_PROFILE_PATH" \
              || "$(stat -c %u "$TELEGRAM_WEB_PROFILE_PATH")" != "$(id -u)" \
              || "$(stat -c %a "$TELEGRAM_WEB_PROFILE_PATH")" != 700 ]]; then
          echo "Telegram Web profile must be private writable collector state" >&2
          exit 77
        fi
        ;;
      *) echo "DATA_SOURCE is invalid for Telegram" >&2; exit 64 ;;
    esac
    ;;
  max)
    : "${MAX_SESSION_PATH:?MAX_SESSION_PATH is required}"
    require_private_writable_file "$MAX_SESSION_PATH" "MAX session"
    ;;
esac

echo "collector state preflight passed platform=$platform"
