#!/usr/bin/env bash
# Принудительная команда ключа выкатки (authorized_keys пользователя
# m-ranked-deploy, см. README.md рядом). Ключ GitHub Actions не получает
# оболочку: sshd передаёт запрошенную строку в SSH_ORIGINAL_COMMAND, и
# пропускаются ровно две формы — остальное отклоняется без исполнения.
#   install -o root -g root -m 0755 operations/deploy/deploy-entrypoint.sh \
#     /usr/local/libexec/m-ranked/deploy-entrypoint
set -Eeuo pipefail

request="${SSH_ORIGINAL_COMMAND:-}"
deploy_re='^deploy (v20[0-9]{2}\.(1[0-2]|[1-9])\.(0|[1-9][0-9]*)) ([0-9a-f]{64}) migrations=(yes|no) config=(yes|no)$'

logger -t m-ranked-deploy -- "request: ${request:0:200}"
if [[ "$request" == status ]]; then
  exec sudo -n /usr/local/libexec/m-ranked/deploy-release status
elif [[ "$request" =~ $deploy_re ]]; then
  exec sudo -n /usr/local/libexec/m-ranked/deploy-release deploy \
    "${BASH_REMATCH[1]}" "${BASH_REMATCH[4]}" \
    "migrations=${BASH_REMATCH[5]}" "config=${BASH_REMATCH[6]}"
fi
echo "отклонено: разрешены только «status» и «deploy <версия> <sha256> migrations=… config=…»" >&2
exit 64
