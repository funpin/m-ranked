#!/usr/bin/env bash
# Оставляет в готовом релизе только standalone runtime Next.js. Исходники
# проекта сохраняются, а pnpm store, полный node_modules и build cache уходят.
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 RELEASE_DIR" >&2
  exit 64
fi

release=$(realpath "$1")
frontend="$release/frontend"
standalone="$frontend/.next/standalone"
static="$frontend/.next/static"

if [[ -L "$release" || ! -d "$standalone" || ! -d "$static" ]]; then
  echo "release does not contain a verified Next.js standalone build" >&2
  exit 65
fi

runtime=$(mktemp -d "$release/.web-runtime.XXXXXX")
cleanup() { rm -rf -- "$runtime"; }
trap cleanup EXIT

if [[ -f "$standalone/frontend/server.js" ]]; then
  cp -a "$standalone/." "$runtime/"
elif [[ -f "$standalone/app/server.js" ]]; then
  install -d "$runtime/frontend"
  cp -a "$standalone/app/." "$runtime/frontend/"
else
  echo "standalone build has no frontend server entrypoint" >&2
  exit 65
fi
install -d "$runtime/frontend/.next"
cp -a "$static" "$runtime/frontend/.next/static"
test -f "$runtime/frontend/server.js"

# Сначала runtime полностью скопирован во временный каталог внутри того же
# release. Ошибка до этой точки не меняет исходное дерево.
rm -rf -- "$release/.pnpm-store" "$frontend/node_modules" "$frontend/.next" \
  "$frontend/deploy" "$frontend/m-ranked-web.tar.gz"
cp -a "$runtime/." "$release/"
install -d -m 0755 "$frontend/.next/cache"

test -f "$frontend/server.js"
test -d "$frontend/node_modules"
test -d "$frontend/.next/static"
