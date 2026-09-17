# Выкатка M-Ranked

Владелец — оператор приложения; миграции и восстановление базы требуют
оператора базы. Релиз неизменяем: дерево лежит в
`/opt/m-ranked/releases/<релиз>`, а `/opt/m-ranked/current` — симлинк на него.

Документ читается сверху вниз и в этом же порядке выполняется. Порядок важнее
отдельных команд: почти каждый отказ выкатки — это правильная команда, сделанная
не в свой момент.

## 0. Преflight на своей машине

```bash
git fetch && git status --short            # дерево чистое
operations/scripts/release-preflight.sh <sha, выкаченный сейчас>
```

Скрипт печатает дельту релиза: новые миграции, изменившиеся юниты и nginx,
изменившиеся lock-файлы, новые переменные окружения. Всё, что он назвал, должно
быть сделано на сервере **до** перезапуска соответствующей службы.

Проверьте, что на этом коммите прошли задания `supply-chain` и
`container-images`, а вложения провенанса относятся к тем же SBOM:

```bash
gh attestation verify --owner funpin sbom-image-api.json
```

Оба задания обязаны быть required checks для `alpha` и релизной ветки
(Settings → Rules → Rulesets). Без этого ворота обходятся слиянием.

## 1. Точка отката

Запишите, куда смотрит симлинк сейчас, — это и есть план отката:

```bash
readlink -f /opt/m-ranked/current
systemctl is-active m-ranked-target-api m-ranked-target-web
```

## 2. Миграции — до кода, не после

Приложения не мигрируют базу на старте. Сначала резервная копия и проверенное
восстановление, потом по одному файлу:

```bash
psql --no-psqlrc --set ON_ERROR_STOP=1 -f db/migrations/00NN_*.sql
psql --no-psqlrc -tAc "SELECT contract_id FROM ops_and_admin.schema_contract"
```

Ожидаемое значение — `live-read-2026-09-13-text-fingerprint`. Для живого
кластера применяется только отдельно просмотренное прямое изменение; набор
bootstrap по населённой базе не проигрывается никогда.

Релиз, которому нужны новые таблицы, до миграции держит `/api/v1/health/ready`
в DOWN. Это не декорация: выкатка кода вперёд миграции — штатный способ получить
отказ на ровном месте.

## 3. Учётные данные и переменные

Секреты живут systemd-credential'ами в `/etc/m-ranked/credentials` и файлами
окружения mode 0600; в релиз они не копируются никогда. Если преflight назвал
новые обязательные переменные — правьте их сейчас, до перезапуска.

Интервал каждого коллектора задаётся отдельно в
`/etc/m-ranked/collector-common.env`: Telegram/VK/MAX — 300 секунд, Rutube —
3600 секунд. Общий `COLLECTOR_POLL_INTERVAL_SECONDS` удалите: это устаревший
fallback и для Rutube он намеренно игнорируется. Для MAX задайте
`MAX_REQUEST_TIMEOUT_SECONDS=30` в `collector-max.env`.

Watchdog читает необязательный `/etc/m-ranked/collector-watchdog.env`. Штатные
пороги — 45 минут для Telegram/VK/MAX и 90 минут для Rutube, с 15-минутной
льготой после старта юнита. После доставки обновлённого service-файла скопируйте
пример конфигурации, выполните `systemctl daemon-reload` и только затем
перезапускайте timer. Сторож оценивает завершённые account/run записи, а не
наличие новых metric snapshot: неизменившиеся метрики не считаются зависанием.

Настройка админки проверяется при старте. С версии c636b74 её ошибка **не
роняет API**: закрывается только административная поверхность (503 с причиной),
публичное чтение продолжает работать, в журнале появляется
`административный интерфейс отключён: …`, а по счётчику
`mranked_api_security_events_total{event="config.rejected"}` срабатывает алерт.
Требования к записи `ADMIN_AUTH_USERS`:

- `passwordHash` — bcrypt не меньше десяти раундов, и **одинаковой** стоимости
  у всех записей (разная стоимость выдаёт временем ответа, какие имена есть);
- `totpSecret` — base32 не меньше шестнадцати байт у каждой записи;
  `ADMIN_REQUIRE_MFA=false` допустим только на стенде, не на проде;
- `ADMIN_CSRF_SECRET` — не короче 32 байт, общий и постоянный: с его сменой
  разом отваливаются все CSRF-токены.

Секрет и ссылка для аутентификатора:

```bash
python - <<'SECRET'
import base64, os, urllib.parse
secret = base64.b32encode(os.urandom(20)).decode().rstrip("=")
print(secret)
print("otpauth://totp/" + urllib.parse.quote("m-ranked:admin")
      + "?secret=" + secret + "&issuer=m-ranked&digits=6&period=30")
SECRET
```

## 4. Доставка дерева

На машине нет rsync: дерево едет архивом и распаковывается поверх очищенного
каталога релиза. `.venv` переносится с предыдущего релиза жёсткими ссылками, а
не копируется.

Три вещи, которых нет в `git archive` и без которых выкатка падает молча:

1. **`frontend/.next/cache` обязан существовать в релизе.** Контейнер web
   монтирует туда `/var/lib/m-ranked/web-cache`, а точку монтирования в
   read-only слое создать не может: docker падает с кодом 125 и сайт ложится.
   Сборка standalone этот каталог не создаёт — создайте руками.
2. **`api/data/official-m-rating-channel-codes.json` под `.gitignore`**, но
   нужен ежедневному заданию официального рейтинга. Копируется отдельно.
3. `.env`, сессии площадок, дампы и учётные данные в релиз не попадают.

## 5. Зависимости

```bash
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
mkdir -p frontend/.next/cache
```

Python на проде — 3.11, а `requirements/*.lock` собраны под 3.13. Целиком их
поставить нельзя: пакет с колесом `cp313` (psycopg-binary, pydantic-core,
uvloop, httptools, watchfiles) на 3.11 просто не встанет. Ставятся только
изменившиеся пакеты и только по хешу из lock; для платформенных колёс нужна
сборка под 3.11 отдельно.

Частичное обновление опаснее полного: FastAPI без совместимого pydantic даёт
`ImportError` на старте и бесконечный перезапуск юнита. Меняете FastAPI или
Starlette — проверьте pydantic и уже потом перезапускайте.

Для справки, полная установка среды (пригодна там, где Python 3.13):

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes --no-deps --upgrade -r requirements/tooling.lock
.venv/bin/pip install --require-hashes --no-deps --only-binary=:all: -r requirements/api.lock
.venv/bin/pip install --require-hashes --no-deps --no-build-isolation -r requirements/collector.lock
.venv/bin/pip install --require-hashes --no-deps --only-binary=:all: -r requirements/anomaly.lock
.venv/bin/pip install --no-deps -r requirements/pymax.txt
# Режим telegram_web дополнительно требует браузера:
# .venv/bin/pip install -r requirements/telegram-web.txt
```

Lock-файлы правятся только пересозданием, целиком:

```bash
python3 operations/scripts/generate_python_lock.py requirements/api.txt requirements/api.lock
python3 operations/scripts/generate_python_lock.py requirements/collector.txt \
  requirements/collector.lock --extra setuptools==80.9.0 wheel==0.45.1
```

## 6. nginx

Конфигурация проверяется до перезагрузки, а не после:

```bash
nginx -t && systemctl reload nginx
```

Кука сессии админки несёт префикс `__Host-`: без HTTPS браузер её не сохранит.
Админка работает только через `https://`, не по адресу и не по http.

## 7. Переключение и перезапуск

Симлинк переключается атомарно, потом службы:

```bash
systemctl daemon-reload                      # если менялись юниты
systemctl restart m-ranked-target-api
systemctl restart m-ranked-target-web
```

Коллекторы перезапускаются **по одному**, с паузой: одновременный перезапуск
сводит их в одну фазу и удваивает пик на единственном ядре.

```bash
for platform in telegram vk max rutube; do
  systemctl restart "m-ranked-target-collector@$platform"
  sleep 60
done
```

## 8. Проверка

Выкатка не закончена, пока всё это не ответило:

```bash
systemctl is-active m-ranked-target-api m-ranked-target-web
curl -fsS http://127.0.0.1:8080/api/v1/health/live
curl -fsS http://127.0.0.1:8080/api/v1/health/ready
curl -fsS http://127.0.0.1:8080/api/v1/health/freshness
# публичные страницы и публичный API — снаружи, не с петли
curl -fsS -o /dev/null -w '%{http_code}\n' 'https://m.funpin.org/rating?platform=telegram'
curl -fsS -o /dev/null -w '%{http_code}\n' 'https://m.funpin.org/api/v1/rating?platform=telegram'
curl -fsS -o /dev/null -w '%{http_code}\n' 'https://m.funpin.org/'
journalctl -u m-ranked-target-api --since '-5 min' --no-pager | tail -30
```

Затем вход в админку целиком — он проверяет и сессии, и миграцию:

```bash
jar=$(mktemp)
curl -sS --cookie-jar "$jar" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"…","otp":"123456"}' \
  https://m.funpin.org/api/v1/admin/session      # 201, в теле CSRF-токен
curl -sS --cookie "$jar" 'https://m.funpin.org/api/v1/admin/jobs?limit=1'
curl -sS --cookie "$jar" -X DELETE -H "X-XSRF-TOKEN: $token" \
  https://m.funpin.org/api/v1/admin/session
rm -f "$jar"
```

Сверх этого: четыре юнита коллекторов, работник аномалий, возраст outbox, место
на диске, архив WAL и последнее успешное восстановление. Пока хоть один нужный
юнит перезапускается или свежесть выше порога — выкатка не завершена.

## 9. Если API не отвечает

Порядок разбора — от процесса к сети, а не наоборот:

```bash
systemctl status m-ranked-target-api --no-pager
journalctl -u m-ranked-target-api -n 100 --no-pager
```

Что встречается в журнале и что это значит:

| Строка | Причина | Что делать |
| --- | --- | --- |
| `ValueError: ADMIN_AUTH_USERS: …` при старте | релиз до c636b74 роняет весь процесс из-за настройки админки | привести `ADMIN_AUTH_USERS` к требованиям раздела 3; на c636b74 и позже это закрывает только админку |
| `ValueError: ADMIN_CSRF_SECRET короче 32 байт` | секрет короче нового минимума | выдать новый секрет ≥32 байт |
| `ModuleNotFoundError` / `ImportError` | частично обновлённый `.venv` | доставить недостающие пакеты по хешу из lock, см. раздел 5 |
| `/health/ready` даёт DOWN, `/health/live` — UP | миграция не применена | применить миграции раздела 2 |
| 502 от nginx при живом юните | API слушает не тот адрес или упал после старта | `ss -ltnp | grep 8080`, затем журнал |

Откат — переключение симлинка на предыдущий релиз и перезапуск тех же служб.
Миграция при этом остаётся применённой: прямые изменения схемы пишутся
совместимыми с предыдущим релизом именно ради этого.

## Что ещё читать

- `HEALTH.md` — что означает каждый health-endpoint;
- `BACKUP_RESTORE.md` — резервные копии и проверка восстановления;
- `docs/architecture/security/dependency-policy.md` — пороги выпуска по CVE.
