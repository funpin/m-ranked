#!/usr/bin/env bash
# Настройка GitHub-репозитория под поток веток и выпуска (AGENTS.md).
# Запускает владелец репозитория (нужны права admin) из корня клона:
#   bash operations/github/setup-repository.sh <логин одобряющего> [<логин> ...]
# Повторный запуск безопасен: правила с тем же именем обновляются.
# Секреты окружения production скрипт не задаёт — см. operations/deploy/README.md.
set -Eeuo pipefail

repo="${MRANKED_REPO:-funpin/m-ranked}"
dir="$(cd "$(dirname "$0")" && pwd)"
(($#)) || { echo "usage: $0 <reviewer-login> [<reviewer-login> ...]" >&2; exit 64; }

permission="$(gh api "repos/$repo" --jq .permissions.admin)"
[[ "$permission" == true ]] || { echo "нужны права admin на $repo" >&2; exit 1; }

echo "== ветка develop"
if ! gh api "repos/$repo/branches/develop" >/dev/null 2>&1; then
  sha="$(gh api "repos/$repo/git/ref/heads/main" --jq .object.sha)"
  gh api "repos/$repo/git/refs" -f ref=refs/heads/develop -f sha="$sha" >/dev/null
fi

echo "== настройки репозитория"
# develop — ветка по умолчанию: PR по умолчанию открываются в неё, ночной
# прогон ворот выпуска идёт по ней. Ветки задач удаляются после слияния.
gh api -X PATCH "repos/$repo" \
  -f default_branch=develop \
  -F delete_branch_on_merge=true \
  -F allow_squash_merge=true -F allow_merge_commit=true -F allow_rebase_merge=false \
  -F allow_auto_merge=true \
  -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=PR_BODY >/dev/null
gh api -X PUT "repos/$repo/vulnerability-alerts" >/dev/null
gh api -X PUT "repos/$repo/automated-security-fixes" >/dev/null || true
gh api -X PATCH "repos/$repo" --input - >/dev/null <<'JSON' || true
{"security_and_analysis": {"secret_scanning": {"status": "enabled"},
                           "secret_scanning_push_protection": {"status": "enabled"}}}
JSON

echo "== правила веток и тегов"
for file in "$dir"/rulesets/*.json; do
  name="$(jq -r .name "$file")"
  id="$(gh api "repos/$repo/rulesets" --jq ".[] | select(.name == \"$name\") | .id")"
  if [[ -n "$id" ]]; then
    gh api -X PUT "repos/$repo/rulesets/$id" --input "$file" >/dev/null
  else
    gh api -X POST "repos/$repo/rulesets" --input "$file" >/dev/null
  fi
  echo "  $name"
done

echo "== окружение production"
reviewers="$(for login in "$@"; do
  printf '{"type":"User","id":%s}\n' "$(gh api "users/$login" --jq .id)"
done | jq -s .)"
jq -n --argjson reviewers "$reviewers" '{
  wait_timer: 0, prevent_self_review: true, reviewers: $reviewers,
  deployment_branch_policy: {protected_branches: false, custom_branch_policies: true}
}' | gh api -X PUT "repos/$repo/environments/production" --input - >/dev/null
if ! gh api "repos/$repo/environments/production/deployment-branch-policies" \
    --jq '.branch_policies[].name' | grep -qx main; then
  gh api -X POST "repos/$repo/environments/production/deployment-branch-policies" \
    -f name=main -f type=branch >/dev/null
fi

echo
echo "Готово. Осталось вручную:"
echo "  1. Секреты окружения production — operations/deploy/README.md."
echo "  2. Settings → General → Releases: включить Immutable releases."
