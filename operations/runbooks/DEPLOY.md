# Выкатка M-Ranked

Владелец — оператор приложения; миграции и восстановление базы требуют
оператора базы. Релиз неизменяем: дерево лежит в
`/opt/m-ranked/releases/<релиз>`, а `/opt/m-ranked/current` — симлинк на него.

Документ читается сверху вниз и в этом же порядке выполняется. Порядок важнее
отдельных команд: почти каждый отказ выкатки — это правильная команда, сделанная
не в свой момент.

Этот документ описывает процедуру, но не разрешает её выполнять. Production
backup/restore, выдача credentials и сертификатов, firewall, переключение
транспорта или трафика и обрезка требуют отдельных разрешений владельцев.

## Профили и один набор units

- **A, один хост:** `m-ranked-target.target` — API, web, четыре collector
  instance, slice, watchdog, cache GC, anomaly, maintenance, official rating и
  overview metrics. Файлов `api-profile.env` и `collector-profile.env` нет;
  остаются `API_DEPLOYMENT_PROFILE=a`, in-process LRU и transfer.
- **B, Сервер 1:** `m-ranked-target-profile-b-server1.target` — четыре
  collector instance, общий slice и watchdog. Установлен
  `collector-profile.env` из `collector-profile-b.env.example`.
- **B, Сервер 2:** `m-ranked-target-profile-b-server2.target` — API, web,
  cache GC, transfer-ingest, cache warmer, Redis, anomaly, maintenance,
  official rating и overview metrics. Установлен `api-profile.env` из
  `api-profile-b.env.example`.

Base service-файлы не копируются по профилям. Отличия B — два env overlay и
drop-in из `operations/systemd/profile-b-server{1,2}`. Одновременно включать
target A и target B на одном хосте нельзя.

Перед установкой статически проверьте контракт:

```bash
operations/scripts/check-runtime-config.py
operations/scripts/check-doc-links.py
```

Полный перечень файлов и форматов секретов находится в
[`operations/env/CREDENTIALS.md`](../env/CREDENTIALS.md). Каждый
`EnvironmentFile=` создаётся из одноимённого `.example`; placeholder заменяют
на хосте, а сам пример не превращают в хранилище секрета.

## Установка профиля A

1. Создайте отдельных непривилегированных users из `User=`/`Group=` units и
   каталоги состояния с владельцем конкретной службы. Node exporter textfile
   directory доступен на запись только через группу `node-exporter`.
2. Установите все базовые `operations/systemd/m-ranked-target-*`, без каталогов
   `profile-b-*`. Установите scripts неизменяемо внутри release.
3. Создайте `/etc/m-ranked/{api,web,web-cache-gc,collector-common,collector-telegram,collector-vk,collector-max,collector-rutube,collector-watchdog,anomaly-analysis,maintenance,overview-metrics}.env`
   из примеров. Не создавайте profile overlays. Установите credentials API,
   collectors, anomaly и maintenance из реестра.
4. Проверьте `COLLECTOR_TRANSFER_MODE=in-process`, оба deployment profile `a`
   и `COLLECTOR_WORKING_SET_RETENTION=off`.
5. Выполните `systemctl daemon-reload`, затем
   `systemctl enable --now m-ranked-target.target`. Backup/restore timers
   включаются отдельно по `BACKUP_RESTORE.md`.

## Установка профиля B

### Общие сертификаты и сеть

Выдайте отдельный client certificate каждому Серверу 1. CN должен совпадать с
`COLLECTOR_TRANSFER_PRODUCER_ID` или его ведущим сегментом; server certificate
содержит внутреннее DNS-имя/IP Сервера 2. Установите PEM через
`LoadCredential`, с 30-дневным overlap при ротации. Private key никогда не
кладётся в env.

На Сервере 2 ingest слушает только внутренний/VPN адрес. Host firewall
разрешает TCP 8443 только точным адресам Серверов 1 или узкой управляемой VPN
подсети и отклоняет всё остальное. После firewall отрендерите
`profile-b-server2/.../20-ingest-network.conf.example` теми же CIDR. Сначала
проверьте правила из существующей административной сессии и только потом
применяйте; не открывайте 8443 в public interface.

Collector unit сохраняет запрет `10/8`, `172.16/12`, `192.168/16`, CGNAT,
link-local и ULA. В профиле B отрендерите его drop-in с **точным** адресом
Сервера 2 (`/32` или `/128`). Более длинный allow prefix выигрывает у общего
private-range deny, не открывая collector'у остальную внутреннюю сеть.

### Сервер 1

1. Установите collector service, slice, watchdog service/timer и target B S1.
2. Создайте обычные collector env, затем `/etc/m-ranked/collector-profile.env`
   из `collector-profile-b.env.example`; retention оставьте `off`.
3. Установите collector DB/platform credentials и три mTLS credentials. Скопируйте
   отрендеренный drop-in в
   `/etc/systemd/system/m-ranked-target-collector@.service.d/20-transfer-network.conf`.
4. Выполните `systemctl daemon-reload` и пока не запускайте collectors до
   готовности receiver, если это миграция с профиля A.

### Сервер 2, Redis и presentation

1. Установите Redis из доверенного пакетного репозитория, отключите vendor
   service и используйте только `m-ranked-target-redis.service`. Скопируйте
   `operations/redis/m-ranked.conf` в `/etc/m-ranked/redis.conf`. Он слушает
   только loopback, не хранит persistence, ограничен 256 MiB data / 320 MiB
   cgroup и перезапускается только при failure. Redis — воспроизводимый cache,
   не источник данных.
2. Создайте случайный пароль один раз; из шаблонов подготовьте `redis.acl` и
   `redis-url` с одинаковым значением, mode 0600. ACL ограничена namespace
   `mranked:response:v1:*` и минимальным набором команд.
3. Создайте env API/web/cache GC/ingest/anomaly/maintenance/overview и
   `/etc/m-ranked/api-profile.env`. В `transfer-ingest.env` замените
   documentation IP на внутренний bind. Установите все credentials из реестра.
4. Установите target B S2, новые Redis/receiver/warmer units, базовые units и
   API Redis drop-in. Отрендерите ingest network drop-in. Создайте users
   `m-ranked-redis`, `m-ranked-transfer-ingest`, `m-ranked-cache-warmup` и их
   точные runtime/textfile directories.
5. Запускайте по слоям: Redis; transfer-ingest; API; web; cache warmer; затем
   analysis/timers. После каждой ступени проверяйте журнал и метрики. Итоговый
   target можно включить только после этих smoke checks.

API unit не содержит `After=` или `Requires=` Redis: target лишь `Wants=` cache.
При падении Redis API остаётся active, считает Redis error и строит ответ из
PostgreSQL. Cache warmer — один долгоживущий process с
`API_CACHE_WARMUP_INTERVAL_SECONDS`; отдельного timer нет, поэтому два
пересекающихся прогрева не возникают. Он обращается только к loopback API и не
получает DB/Redis credentials.

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

## 2. Миграции — обычно до кода

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

Исключение — миграция `0033_remove_csv_exports.sql`: она удаляет таблицу,
в которую старые collectors ещё пишут. Для неё сначала остановите все четыре
`m-ranked-target-collector@*.service`, переключите API, web и collectors на
релиз без CSV-экспорта, затем примените `0033` и запустите collectors. Не
применяйте `0029` перед заменой кода и не оставляйте старый collector работающим
во время удаления таблицы.

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

Четыре вещи, которых нет в `git archive` и без которых выкатка падает молча:

1. **Корень релиза обязан быть доступен runtime-пользователям.** Создавайте
   `/opt/m-ranked/releases/<релиз>` как `root:m-ranked-release-readers` с
   режимом `0750`; добавьте в эту системную группу существующих пользователей
   API, collectors и maintenance до их перезапуска. Режим `0700`, который
   оставляет `mktemp -d`, ломает поздние Python imports у ещё работающих
   процессов и даёт `status=200/CHDIR` при следующем старте unit. Проверка:

   ```bash
   getent group m-ranked-release-readers >/dev/null || groupadd --system m-ranked-release-readers
   for user in m-ranked-api m-ranked-web m-ranked-maintenance \
       m-ranked-collector-telegram m-ranked-collector-vk \
       m-ranked-collector-max m-ranked-collector-rutube; do
       usermod -a -G m-ranked-release-readers "$user"
   done
   chown root:m-ranked-release-readers /opt/m-ranked/releases/<релиз>
   chmod 0750 /opt/m-ranked/releases/<релиз>
   stat -c '%U:%G %a %n' /opt/m-ranked/releases/<релиз>
   runuser -u m-ranked-collector-max -- test -r /opt/m-ranked/releases/<релиз>/collector_target/__main__.py
   ```

   Не добавляйте nginx в эту группу: `/_next/static/` проксируется в тот же
   Next.js process, который отдал HTML, и не читает release tree напрямую.
2. **`frontend/.next/cache` обязан существовать в релизе.** Контейнер web
   монтирует туда `/var/lib/m-ranked/web-cache`, а точку монтирования в
   read-only слое создать не может: docker падает с кодом 125 и сайт ложится.
   Сборка standalone этот каталог не создаёт — создайте руками.
3. **`api/data/official-m-rating-channel-codes.json` под `.gitignore`**, но
   нужен ежедневному заданию официального рейтинга. Копируется отдельно.
4. `.env`, сессии площадок, дампы и учётные данные в релиз не попадают.

## 5. Зависимости

```bash
pnpm --dir frontend install --frozen-lockfile
MRANKED_DEPLOYMENT_ID=<уникальный-id-релиза> pnpm --dir frontend build
operations/scripts/finalize-web-release.sh "$PWD"
```

`MRANKED_DEPLOYMENT_ID` обязателен для production-сборки и должен отличаться у
каждого релиза (подходит имя каталога релиза: только буквы, цифры, `_` и `-`).
Next.js добавляет его как `?dpl=<id>` к URL клиентских ассетов. Это не даёт
браузеру переиспользовать `403/404`, ошибочно закэшированный старым nginx как
`immutable`, и отделяет ассеты параллельных blue/green-релизов. После запуска
проверьте наличие `?dpl=` в HTML публичной страницы.

`finalize-web-release.sh` сохраняет standalone runtime и static, но удаляет из
готового релиза полный `node_modules`, `.pnpm-store` и `.next/cache` сборщика.
Точка `frontend/.next/cache` затем создаётся пустой для writable bind mount.
Не переключайте `current`, если после финализации отсутствует
`frontend/server.js` или не прошёл пробный запуск web-контейнера.

Python на проде — 3.11, а `requirements/*.lock` собраны под 3.13. Целиком их
поставить нельзя: пакет с колесом `cp313` (psycopg-binary, pydantic-core,
uvloop, httptools, watchfiles) на 3.11 просто не встанет. Ставятся только
изменившиеся пакеты и только по хешу из lock; для платформенных колёс нужна
сборка под 3.11 отдельно. Анализ аномалий v2 добавил в `anomaly.lock` numpy и
scipy — тоже платформенные колёса: версии выбраны так, что колёса для 3.11
есть, но их хеши в lock — от cp313. Порядок выкатки анализа —
[`ANOMALY.md`](ANOMALY.md).

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
  requirements/collector.lock --extra setuptools==80.9.0 wheel==0.46.2
```

### Ограничение Next.js cache

Глобальный Next.js `cacheHandler` здесь не используется: он подменяет все виды
incremental cache (fetch, app page и route), зависит от внутренних форматов
Next.js и связывает неизменяемые релизы общим persistent-форматом. Публичные
API-представления вместо этого живут в process-local TTL/LRU: штатно 10 секунд,
128 записей и 16 MiB. Одинаковые конкурентные misses используют один producer;
перезапуск, deploy и rollback намеренно начинают с холодного кэша.

Writable mount сохраняется для совместимости Next.js и старых релизов. Его
активный `fetch-cache` ограничивает отдельный timer: файлы старше часа удаляются,
а при превышении 128 MiB oldest-first проход уменьшает объём до 96 MiB. Перед
unlink повторно сверяются inode, размер и mtime. Установите collector вне
immutable release, чтобы rollback не убрал защиту:

```bash
install -D -o root -g root -m 0755 operations/scripts/gc-next-cache.mjs \
  /usr/local/libexec/m-ranked/gc-next-cache.mjs
install -o root -g root -m 0644 operations/systemd/m-ranked-target-web-cache-gc.service \
  operations/systemd/m-ranked-target-web-cache-gc.timer /etc/systemd/system/
install -o root -g root -m 0600 operations/env/web-cache-gc.env.example \
  /etc/m-ranked/web-cache-gc.env
```

В `/etc/m-ranked/web-cache-gc.env` закрепите тот же проверенный Node image digest,
что в `m-ranked-target-web.service`, и числовые uid:gid владельца
`/var/lib/m-ranked/web-cache`. Collector работает без сети и capabilities, с
read-only root; единственный writable bind — точный активный cache.

`/var/lib/m-ranked/web-cache-b66ad66-retired-20260921` — сохранённое production-
свидетельство. Не удаляйте, не переименовывайте, не монтируйте его как active и
не меняйте без отдельного явного разрешения.

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
systemctl enable --now m-ranked-target-web-cache-gc.timer
systemctl restart m-ranked-target-api
systemctl restart m-ranked-target-web
```

При `COLLECTOR_SCHEDULE_MODE=legacy` коллекторы перезапускаются **по одному**,
с паузой: offsets не исключают overlap. В `phased` режиме одновременный restart
безопасен: workers сначала объявляют UTC-слоты, затем PostgreSQL пропускает в
тяжёлую фазу только один процесс.

```bash
for platform in telegram vk max rutube; do
  systemctl restart "m-ranked-target-collector@$platform"
  sleep 60
done
```

Для `phased` после проверки режима допустим один одновременный вызов:

```bash
systemctl restart m-ranked-target-collector@telegram.service \
  m-ranked-target-collector@vk.service m-ranked-target-collector@max.service \
  m-ranked-target-collector@rutube.service
```

`TimeoutStopSec=60s` оставляет 45 секунд на
`COLLECTOR_SHUTDOWN_GRACE_SECONDS` и ещё 15 секунд на закрытие соединений и
textfile. Если grace меняется, stop timeout должен оставаться строго больше.

Первое включение phased scheduler выполняется expand/contract:

1. Установить `COLLECTOR_SCHEDULE_MODE=shadow` на одном instance и проверить
   `scheduled_at`, `schedule_lag_seconds` и отсутствие provider calls.
2. Переключить canary на `phased`; убедиться, что checkpoint
   `collector.phase.v1` меняет `requested -> active -> completed`.
3. Включить `phased` на остальных instances.
4. Наблюдать не меньше полного часового интервала Rutube: phase wait, lag,
   overruns, coalesced slots, partial/failed runs и watchdog.
5. Не менять интервалы `300/300/300/3600` в том же rollout. Они остаются
   desired cadence; изменение production cadence требует отдельного решения.

## 8. Ограничение накопления релизов и Docker-артефактов

Host GC сохраняет current, один предыдущий rollback, реально используемые cwd/exe,
mounts всех containers и ссылки systemd для следующего запуска. Молодые каталоги
младше суток сохраняются. Удаление требует явного списка согласованных basenames
в `MRANKED_APPROVED_RELEASE_REMOVALS`; forensic и дополнительные rollback задаются
в `MRANKED_PROTECTED_RELEASES`. Blanket Docker prune отключён: images/containers
удаляются только по отдельно проверенным IDs без force; volumes не удаляются.
GC и deployment используют общий lock `/run/lock/m-ranked-release.lock`.

Установите collector вне immutable release, сначала проверьте dry-run, затем
включите еженедельный timer:

```bash
install -D -o root -g root -m 0755 operations/scripts/gc_host_storage.py \
  /usr/local/libexec/m-ranked/gc_host_storage.py
install -o root -g root -m 0644 \
  operations/systemd/m-ranked-target-host-storage-gc.service \
  operations/systemd/m-ranked-target-host-storage-gc.timer /etc/systemd/system/
install -o root -g root -m 0600 operations/env/host-storage-gc.env.example \
  /etc/m-ranked/host-storage-gc.env
/usr/local/libexec/m-ranked/gc_host_storage.py
systemctl daemon-reload
systemctl enable --now m-ranked-target-host-storage-gc.timer
```

## 9. Проверка

Выкатка не закончена, пока всё это не ответило:

```bash
systemctl is-active m-ranked-target-api m-ranked-target-web
systemctl is-active m-ranked-target-web-cache-gc.timer
journalctl -u m-ranked-target-web-cache-gc.service -n 20 --no-pager
du -sh /var/lib/m-ranked/web-cache
curl -fsS http://127.0.0.1:8080/api/v1/health/live
curl -fsS http://127.0.0.1:8080/api/v1/health/ready
curl -fsS http://127.0.0.1:8080/api/v1/health/freshness
# публичные страницы и публичный API — снаружи, не с петли
curl -fsS -o /dev/null -w '%{http_code}\n' 'https://m.funpin.org/statistics?platform=telegram'
curl -fsS -o /dev/null -w '%{http_code}\n' 'https://m.funpin.org/api/v1/statistics?platform=telegram'
# старые namespace свободны для будущего рейтинга
test "$(curl -sS -o /dev/null -w '%{http_code}' 'https://m.funpin.org/rating')" = 404
test "$(curl -sS -o /dev/null -w '%{http_code}' 'https://m.funpin.org/api/v1/rating')" = 404
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

Ожидание `phase=waiting` само по себе штатно. Растущий `schedule_lag_seconds`
означает нехватку сериализованной ёмкости и не должен маскироваться повышением
freshness threshold.

## 10. Если API не отвечает

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

## 10. Живой переезд A → B

Все значения курсоров, checksums, counts, время и operator identity сохраняются
в change record. На всём пути до шага 10 retention остаётся `off`; Сервер 1
остаётся полной и пригодной для чтения копией.

1. **Проверить откат и Сервер 2.** Проверить свежую backup и изолированное
   восстановление профиля A. Установить Сервер 2 как описано выше, но внешний
   трафик и receiver пока не включать. Сверить schema contract и миграции.
2. **Зафиксировать один DB snapshot и точный outbox cursor.** В первой psql
   сессии на Сервере 1 открыть read-only transaction и не закрывать её до конца
   `pg_dump`:

   ```sql
   BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
   SELECT pg_export_snapshot() AS snapshot_id,
          (SELECT coalesce(max(cursor), 0)
             FROM ops_and_admin.transfer_outbox) AS snapshot_cursor
   \gset migration_
   \echo snapshot=:migration_snapshot_id cursor=:migration_snapshot_cursor
   ```

   Во второй сессии выполнить `pg_dump -Fc --snapshot=<snapshot_id>` и записать
   SHA-256 dump. Только после успешного dump завершить первую transaction
   `COMMIT`. Snapshot id и `snapshot_cursor` записать дословно; повторный dump —
   это новый snapshot и новый cursor, их нельзя смешивать.
3. **Восстановить Сервер 2.** Передать dump по утверждённому защищённому каналу,
   проверить SHA-256, восстановить в пустую ReadyDB и сверить contract, row
   counts, `dataset_revision`, outbox/inbox и snapshot cursor. Старый профиль A
   продолжает собирать и обслуживать пользователей.
4. **Открыть только transport.** Применить firewall, ingest systemd allowlist и
   mTLS credentials. Запустить Redis и `m-ranked-target-transfer-ingest` на
   Сервере 2. Проверить refusal без client cert, refusal чужого producer и
   успешный совместимый smoke утверждённым client cert.
5. **Остановить producer на короткую границу.** Отключить автозапуск target A,
   затем остановить четыре collectors на Сервере 1: в legacy по одному с
   паузой, в phased одновременно. API/web профиля A остаются живыми. Дождаться
   bounded shutdown и записать `final_cursor=max(cursor)`, counts по state и
   отсутствие незавершённой collect transaction.
6. **Переоткрыть хвост после snapshot.** Строки `cursor <= snapshot_cursor` уже
   находятся в восстановленной DB. В С1 сначала убедиться, что после границы
   нет `terminal`; terminal batch блокирует миграцию. Затем в просмотренной
   operator transaction вернуть только хвост в доставляемое состояние. Открыть
   psql с `--set snapshot_cursor=<зафиксированный snapshot_cursor>`:

   ```sql
   BEGIN;
   SELECT state, count(*), min(cursor), max(cursor)
     FROM ops_and_admin.transfer_outbox
    WHERE cursor > :'snapshot_cursor'
    GROUP BY state ORDER BY state;
   -- Продолжать только если terminal отсутствует и counts совпали с change record.
   UPDATE ops_and_admin.transfer_outbox
      SET state='sealed', sent_at=NULL, acknowledged_at=NULL,
          ack_receipt_id=NULL, ack_checksum=NULL, last_error_code=NULL,
          available_at=transaction_timestamp(),
          attempt_window_started_at=NULL, attempt_window_count=0
    WHERE cursor > :'snapshot_cursor' AND state <> 'terminal';
   COMMIT;
   ```

   Это осознанный одноразовый replay границы: не редактировать строки до
   snapshot и не менять payload, checksum, batch id, producer id или cursor.
7. **Переключить collectors на HTTPS+mTLS.** Установить profile B overlay и
   collector network/credential drop-in, retention всё ещё `off`. Запустить
   target B S1. Дренаж идёт oldest-first; потерянный ACK безопасно повторяет тот
   же batch, а DataAdapter дедуплицирует его.
8. **Догнать хвост.** До переключения чтения должны одновременно выполняться:
   S1 `last_acknowledged_cursor = final_cursor`, S2
   `last_applied_cursor = final_cursor`, backlog равен нулю, quarantined и
   unaccounted равны нулю, checksums/counts совпадают. Наблюдать ещё минимум
   один обычный цикл каждой платформы.
9. **Переключить presentation traffic.** Запустить и проверить API, web,
   Redis/warmup, anomaly и timers на Сервере 2. Переключить upstream/DNS/nginx
   на С2, проверить public, admin, freshness, p95 и DB load. Затем остановить
   presentation units на С1, но не удалять их данные, env, release или cert.
10. **Стабилизация и dry-run retention.** После согласованного окна наблюдения
    поставить `COLLECTOR_WORKING_SET_RETENTION=dry-run`, перезапустить collectors
    по правилам scheduler mode и сохранить список candidate/deferred months.
    Сверить каждый candidate с ACK/applied cursor, tracking window, backup и
    capacity; dry-run ничего не удаляет.

    ```sql
    SELECT months.published_month,
           ops_and_admin.collector_working_set_month_releasable(
               months.published_month, 720) AS releasable
      FROM (SELECT DISTINCT published_month
              FROM ingest.publication_metric_snapshot) AS months
     ORDER BY months.published_month;
    ```

    Значение `720` должно буквально совпадать с просмотренным
    `TRACK_POST_FOR_HOURS`, а вывод прикладывается к отдельному approval шага 11.
11. **Отдельное необратимое подтверждение.** Только новым явным разрешением
    владельца данных поставить retention `on`. Изменение конфигурации ещё можно
    отменить; **первый фактически dropped monthly partition — единственная
    точка невозврата**. После неё возврат profile A требует восстановления
    полной истории из Сервера 2/backup, а не обратного переключения env.

### Порядок production-разрешений

Разрешения выдаются отдельно и в таком порядке: (1) backup и проверенное
restore/provisioning; (2) выпуск и установка DB/Redis/mTLS credentials; (3)
firewall и точные systemd IP allowlist; (4) snapshot/cursor и SQL переоткрытия
хвоста; (5) transport switch; (6) traffic/DNS/nginx switch; (7) retention
dry-run и review; (8) отдельное необратимое разрешение на `on` и первый drop.
Предыдущее разрешение не подразумевает следующее.

API master перед каждым стартом удаляет только
`m-ranked-api-cache-*.prom` из provisioned textfile directory. Так PID-файлы
погибших workers не удваивают cache counters после restart; security, warmup и
чужие `.prom` не затрагиваются.

## Что ещё читать

- `HEALTH.md` — что означает каждый health-endpoint;
- `BACKUP_RESTORE.md` — резервные копии и проверка восстановления;
- `docs/architecture/security/dependency-policy.md` — пороги выпуска по CVE.

## Storage rollout gate

Перед изменением retention, backup или GC используйте
[STORAGE_BUDGET.md](STORAGE_BUDGET.md). Подготовленный код не подтверждает
production rollout. Host GC больше не выполняет blanket Docker prune;
release deletion ограничено согласованным списком и проверками занятости.
