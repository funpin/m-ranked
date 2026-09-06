#!/bin/bash
# Sourced only from the protected routing entrypoint. No signals are sent.

_mranked_nginx_process_start() {
  local proc_root="$1" pid="$2" record suffix
  local -a fields
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  IFS= read -r record 2>/dev/null <"$proc_root/$pid/stat" || return 1
  suffix="${record##*) }"
  read -r -a fields <<<"$suffix"
  [[ ${#fields[@]} -ge 20 && "${fields[19]}" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "${fields[19]}"
}

_mranked_nginx_master_matches() {
  local proc_root="$1" binary="$2" current
  [[ "$proc_root/$MRANKED_NGINX_MASTER_PID/exe" -ef "$binary" ]] || return 1
  current="$(_mranked_nginx_process_start "$proc_root" "$MRANKED_NGINX_MASTER_PID")" || return 1
  [[ "$current" == "$MRANKED_NGINX_MASTER_START" ]]
}

_mranked_nginx_capture_workers() {
  local proc_root="$1" binary="$2" master="$3" children pid title started record suffix
  local -a fields
  [[ "$master" =~ ^[1-9][0-9]*$ && "$proc_root/$master/exe" -ef "$binary" ]] || {
    echo "nginx freeze barrier: master identity is unavailable" >&2; return 73;
  }
  MRANKED_NGINX_MASTER_PID="$master"
  MRANKED_NGINX_MASTER_START="$(_mranked_nginx_process_start "$proc_root" "$master")" || return 73
  MRANKED_NGINX_OLD_WORKERS=()
  IFS= read -r children <"$proc_root/$master/task/$master/children" || [[ -n "$children" ]] || return 73
  for pid in $children; do
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 73
    [[ "$proc_root/$pid/exe" -ef "$binary" ]] || continue
    title="$(tr '\0' ' ' 2>/dev/null <"$proc_root/$pid/cmdline")" || continue
    [[ "$title" == "nginx: worker process"* ]] || continue
    IFS= read -r record 2>/dev/null <"$proc_root/$pid/stat" || continue
    suffix="${record##*) }"; read -r -a fields <<<"$suffix"
    [[ ${#fields[@]} -ge 20 && "${fields[1]}" == "$master" && "${fields[19]}" =~ ^[0-9]+$ ]] || return 73
    started="${fields[19]}"
    MRANKED_NGINX_OLD_WORKERS+=("$pid:$started")
  done
  if [[ ${#MRANKED_NGINX_OLD_WORKERS[@]} -eq 0 ]] || ! _mranked_nginx_master_matches "$proc_root" "$binary"; then
    echo "nginx freeze barrier: no verified worker generation" >&2; return 73
  fi
}

mranked_nginx_freeze_capture() {
  local master
  master="$(systemctl show nginx.service --property=MainPID --value)" || return 73
  _mranked_nginx_capture_workers /proc "$1" "$master"
}

_mranked_nginx_wait_workers() {
  local proc_root="$1" binary="$2" timeout="$3" deadline identity pid expected current pending
  [[ "$timeout" =~ ^[1-9][0-9]*$ ]] && (( timeout <= 120 )) || {
    echo "nginx freeze barrier: invalid bounded timeout" >&2; return 64;
  }
  [[ ${#MRANKED_NGINX_OLD_WORKERS[@]} -gt 0 ]] || return 73
  deadline=$((SECONDS+timeout))
  while :; do
    if ! _mranked_nginx_master_matches "$proc_root" "$binary"; then
      echo "nginx freeze barrier: master changed during drain" >&2; return 75
    fi
    pending=0
    for identity in "${MRANKED_NGINX_OLD_WORKERS[@]}"; do
      pid="${identity%%:*}"; expected="${identity#*:}"
      current="$(_mranked_nginx_process_start "$proc_root" "$pid")" || continue
      [[ "$current" != "$expected" ]] || pending=$((pending+1))
    done
    if (( pending == 0 )); then
      _mranked_nginx_master_matches "$proc_root" "$binary" || return 75
      return 0
    fi
    if (( SECONDS >= deadline )); then
      echo "nginx freeze barrier: old workers did not exit; freeze remains installed" >&2; return 75
    fi
    sleep 0.1
  done
}

mranked_nginx_freeze_wait() {
  _mranked_nginx_wait_workers /proc "$1" "${2:-30}"
}
