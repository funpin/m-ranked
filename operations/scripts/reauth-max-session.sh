#!/usr/bin/env bash
# Повторный вход MAX-сборщика по SMS-коду, когда MAX отозвал токен сессии
# (в журнале сборщика: error=login.token, FAIL_LOGIN_TOKEN).
#
# Запускается на сервере сборщиков интерактивно (ssh -t … 'bash -s' не
# подойдёт: нужен терминал для ввода кода). Код из SMS и, если включён,
# пароль двухэтапной проверки вводит владелец аккаунта; скрипт их не видит
# и никуда не пишет.
#
# Вход идёт в новый файл: в старом лежит отозванный токен, и клиент пытался
# бы войти с ним, а не запрашивать SMS. Юнит сборщика останавливается только
# на замену файла; старая сессия сохраняется рядом с суффиксом .revoked-<время>.
set -Eeuo pipefail

instance=${1:-max}
unit="m-ranked-target-collector@${instance}.service"
user="m-ranked-collector-${instance}"
state="/var/lib/m-ranked/collectors/${instance}"
session="${state}/max.session.db"
fresh="${state}/max.session.new.db"
auth="/etc/m-ranked/credentials/collector-${instance}-auth.env"
release=$(systemctl show -p WorkingDirectory --value "$unit")

[[ $EUID -eq 0 ]] || { echo "запустите от root" >&2; exit 64; }
[[ -t 0 ]] || { echo "нужен интерактивный терминал (ssh -t)" >&2; exit 64; }
[[ -x "$release/.venv/bin/python" ]] || { echo "нет окружения релиза: $release" >&2; exit 65; }
phone=$(sed -n 's/^MAX_USER_PHONE=//p' "$auth")
[[ -n "$phone" ]] || { echo "в $auth нет MAX_USER_PHONE" >&2; exit 65; }

rm -f -- "$fresh"
echo "Вход в MAX для номера, заканчивающегося на ${phone: -4}. Дождитесь SMS и введите код."
# Номер передаётся окружением дочернему процессу: в аргументах он был бы
# виден в списке процессов. Код Python идёт через -c, а не через stdin: stdin
# нужен PyMax для ввода SMS-кода.
login='
import asyncio, os, sqlite3, sys
from collector_runtime.max_user_api import MaxUserClient

path = sys.argv[1]
# connect() ждёт не дольше таймаута запроса: на SMS-код — 10 минут, а не 30 с.
client = MaxUserClient(os.environ["MAX_USER_PHONE"], path, request_timeout_seconds=600)
async def main():
    try:
        await client.authorize_interactive()
    finally:
        await client.close()
asyncio.run(main())
with sqlite3.connect(path) as db:
    ok = db.execute("SELECT 1 FROM sessions WHERE phone=? AND length(token)>0",
                    (os.environ["MAX_USER_PHONE"],)).fetchone()
sys.exit(0 if ok else "в новой сессии нет токена")
'
export MAX_USER_PHONE="$phone"
runuser -u "$user" -- env -C "$release" "$release/.venv/bin/python" -c "$login" "$fresh"
unset phone MAX_USER_PHONE

stamp=$(date +%Y%m%dT%H%M%S)
systemctl stop "$unit"
[[ -f "$session" ]] && mv -- "$session" "${session}.revoked-${stamp}"
mv -- "$fresh" "$session"
chown "$user:$user" "$session"; chmod 0600 "$session"
systemctl start "$unit"
sleep 45
journalctl -u "$unit" --since "-1 min" --no-pager -o cat \
  | grep -E "login|account (failed|completed)|phase (started|completed)" | tail -8
echo "Старая сессия: ${session}.revoked-${stamp}"
