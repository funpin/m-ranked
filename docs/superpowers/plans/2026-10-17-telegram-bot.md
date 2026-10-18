# Telegram-бот m-ranked — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот в Telegram отвечает на запросы о лучших постах, шлёт дайджест и
контентные уведомления в рабочий чат и доставляет тревоги серверов лично
людям из списка. Подключение бота при деплое необязательно.

**Architecture:** Две части. Часть A дорабатывает существующие
`operations/scripts/alerts.py` и `api/tools/ops_sample.py`: новые пороги и
передача переходов тревог в каталог-очередь вместо прямой отправки в
Telegram. Часть A полезна и без бота. Часть B — новый пакет `telegram_bot/`:
long polling к Telegram, данные постов через локальный HTTP API (его кэш),
состояние сервера — из готовых строк `ops_and_admin.host_sample` и
`server_node_sample`, настройки — в новых таблицах миграции 0087.

**Tech Stack:** Python (тот же venv, что у API), httpx 0.28.1 и psycopg 3.3.5
(уже в `requirements/api.txt`), PostgreSQL, systemd, pytest.

**Spec:** `docs/superpowers/specs/2026-10-17-telegram-bot-design.md`

## Global Constraints

- Ничего из адресов, портов, ключей, токенов и Telegram ID — в репозитории (`AGENTS.md`). В примерах env — пустые значения.
- Новых зависимостей нет: только httpx и psycopg из `requirements/api.txt`; бот запускается из `/opt/m-ranked/current/.venv`.
- Часовой пояс всех расписаний — `Europe/Moscow`.
- Дайджест: понедельник 10:00, за прошлую неделю. «Выстрелил»: возраст поста < 48 ч и `interactionIndex` ≥ 3. «Накрутка»: уровень 3 — сообщение, уровень 2 — «вероятно», уровень 1 — ничего.
- Тихие часы 23:00–08:00: несрочные тревоги копятся до утра. «Заглушить» — на 2 часа. Напоминание — раз в 6 часов (как сейчас в `transitions()`).
- Тревоги — только людям (`kind='person'`). Это проверяется трижды: в `Recipient`, ограничением CHECK в базе и фильтром при доставке.
- Обращения к API: только публичные GET, `limit=50`, остальные параметры как у сайта (по умолчанию), не больше одного запроса одновременно. Новых SQL-чтений в API нет.
- Бот: `MemoryMax=128M`, `CPUQuota=20%`, `Nice=10`. В юнитах alerts и ops-sample лимиты не повышать.
- М-Рейтинг — только чтение снимка `/api/v1/rating/forecast`.
- Продвигаемые посты (`promotion: true`) показываются с пометкой «📣 продвижение». Подозрительные (уровни 2–3) по умолчанию скрыты (`anomalies=exclude`).
- В дайджесте «Лучшие у других» без нашего вуза. В `/top все` наш вуз показывается с пометкой «мы».
- Работа идёт в ветке `feat/telegram-bot` (worktree `.claude/worktrees/telegram-bot`). Main не трогать. В коммитах нет строки `Co-Authored-By: Claude` (правило владельца).
- Прод переключать только после явного «делай» владельца.

## Review Focus

1. **Первый запуск и перезапуск.** Старые Находки за неделю не должны разом обрушиться в чат как «выстрелил» и «накрутка». При первом запуске бот молча помечает их как уже объявленные (тест в Task 11).
2. **Длинные ответы.** Дайджест и `/top все … 20` с длинными названиями вузов не должны упираться в лимит Telegram 4096 символов: они делятся по строкам (тест в Task 8).
3. **HTML в данных.** Название вуза или URL с `<`, `&`, `"` экранируются и не ломают `parse_mode=HTML` (тест в Task 8).
4. **Бот выключен, а alerts.py пишет.** Очередь не растёт без конца: alerts.py держит в ней не больше 500 файлов и удаляет самые старые (тест в Task 1).
5. **API недоступен, Telegram ответил 429 или 403.** Бот отвечает «данные временно недоступны», уважает `retry_after`, а получателя, который заблокировал бота или удалил его из чата, убирает. Цикл при этом не падает и не повторяет ошибку каждую минуту (тесты в Task 6 и Task 10).

---

## Файлы

Часть A (тревоги):
- Modify `operations/scripts/alerts.py` — события, очередь, новые правила.
- Modify `api/tools/ops_sample.py` — файл входных данных для тревог.
- Modify `operations/systemd/m-ranked-target-alerts.service`, `operations/env/alerts.env.example`, `operations/runbooks/TRAFFIC.md` (раздел про тревоги).
- Test: `tests/test_alerts.py`, `tests/test_ops_sample.py`.

Часть B (бот):
- Modify `api/system_overview.py`, `api/routes/system.py` — общая сводка состояния.
- Create `db/migrations/0087_telegram_bot.sql`; Modify `infra/postgres/init/001-create-roles.sh`.
- Create пакет `telegram_bot/`:

  | Файл | За что отвечает |
  |---|---|
  | `config.py` | настройки из env, чтение токена |
  | `telegram.py` | HTTP-клиент Bot API |
  | `words.py` | разбор слов `/top`, синонимы, поиск вуза |
  | `source.py` | чтение локального API |
  | `render.py` | тексты, кнопки, деление сообщений |
  | `store.py` | настройки и состояние в базе плюс копия в памяти для тестов |
  | `access.py` | кто какие команды может вызывать |
  | `handlers.py` | разбор входящих сообщений и кнопок |
  | `content.py` | дайджест, «выстрелил», «накрутка», неделя к неделе |
  | `alerts_inbox.py` | доставка тревог из очереди |
  | `status.py` | ответ на `/status` |
  | `__main__.py` | основной цикл |

- Create `operations/systemd/m-ranked-target-telegram-bot.service`, `operations/env/telegram-bot.env.example`, `operations/runbooks/TELEGRAM_BOT.md`; Modify `operations/runbooks/DEPLOY.md`.
- Tests: `tests/test_telegram_bot_*.py`.

---

## Часть A — тревоги

### Task 1: События тревог и очередь вместо прямой отправки

**Files:**
- Modify: `operations/scripts/alerts.py` (`Rule`, `transitions`, `send`, `token`, `main`)
- Modify: `operations/systemd/m-ranked-target-alerts.service`, `operations/env/alerts.env.example`
- Test: `tests/test_alerts.py`

**Interfaces:**
- Produces:
  - `Rule(key: str, firing: bool, text: str, urgent: bool = False)`;
  - `Event(key: str, kind: Literal["open","repeat","resolve"], urgent: bool, text: str, since: float)`;
  - `transitions(rules, state, now) -> list[Event]`;
  - `format_event(event: Event) -> str`;
  - `write_event(spool: Path, event: Event, server: str, now: float) -> None`.
  - Формат файла очереди (его читает Task 12): JSON `{"version": 1, "server": str, "key": str, "kind": str, "urgent": bool, "text": str, "since": float, "at": float}`. Имя файла: `f"{time_ns}-{key}.json"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_alerts.py`:
  - `test_transitions_return_events`: правило, сработавшее в первый раз, даёт `Event(kind="open")`; то же через 6 ч + 1 с — `"repeat"`; погасшее — `"resolve"`. Поле `urgent` берётся из правила.
  - `test_format_event_keeps_current_texts`: `format_event` даёт ровно нынешние строки: `"🔴 {text}"`, `"🔴 Всё ещё: {text} (с dd.mm HH:MM)"`, `"🟢 Прошло: {text}"`.
  - `test_write_event_is_atomic_and_world_readable`: после записи в каталоге ровно один `*.json` (без `.tmp`), права `0o644`, JSON совпадает с форматом выше.
  - `test_spool_is_capped_at_500_files`: при 500 файлах запись нового удаляет самый старый (по имени).
  - `test_without_spool_dir_only_prints`: при отсутствующем `ALERTS_BOT_SPOOL_DIR` вызов `main()` ничего не создаёт и печатает сообщение.
  - `test_spool_failure_reopens_next_minute`: если `write_event` бросил `OSError`, ключ убирается из `state["active"]`.
  - `test_no_direct_telegram_path`: `not hasattr(alerts, "send")` и `"api.telegram.org" not in SCRIPT.read_text()`.

  Существующие тесты, которые ждут строки от `transitions`, переписать на `format_event(...)`.
- [ ] **Step 2: Run** `python -m pytest tests/test_alerts.py -q`. Expected: новые тесты FAIL.
- [ ] **Step 3: Implement.**
  - Удалить `send()`, `token()`, `ALERTS_TELEGRAM_*`.
  - Каталог очереди — `ALERTS_BOT_SPOOL_DIR` (по умолчанию `/var/lib/m-ranked/telegram-bot/inbox`), запись — только если каталог существует.
  - Имя сервера в событии — `ALERTS_SERVER_NAME` (по умолчанию `"Сервер 2"`).
  - Писать во временный файл, затем `os.fchmod(fd, 0o644)` и `os.replace`.
  - В юните добавить `ReadWritePaths=-/var/lib/m-ranked/telegram-bot/inbox` и убрать «to Telegram» из `Description`.
  - В env-примере убрать строки Telegram, описать `ALERTS_BOT_SPOOL_DIR` и `ALERTS_SERVER_NAME`.
- [ ] **Step 4: Run** `python -m pytest tests/test_alerts.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alerts): переходы тревог — в очередь бота вместо прямой отправки`.

### Task 2: Пороги нагрузки, памяти, диска и роботов

**Files:**
- Modify: `operations/scripts/alerts.py` (`evaluate`, `main`, лимиты)
- Modify: `operations/env/alerts.env.example`
- Test: `tests/test_alerts.py`

**Interfaces:**
- Consumes: `Rule` из Task 1.
- Produces:
  - `Host(disk_free: int, disk_total: int, load5_series: list[float], cpu_series: list[float], memory_used_share: float | None, swap_used_bytes: int | None, failed: list[str], dump_mtime: float | None, bots_per_minute: list[int])`;
  - `evaluate(now, traffic, values, host: Host, inputs: dict | None, limits: dict) -> list[Rule]` (заменяет прежние именованные аргументы);
  - `push_series(state: dict, name: str, value: float, keep: int) -> list[float]`;
  - `cpu_busy_percent(state: dict) -> float | None` (по разности `/proc/stat` с прошлого запуска);
  - `read_memory() -> tuple[float | None, int | None]`;
  - `bots_per_minute(state: dict, minute: int, count: int) -> list[int]`.
  - Новые ключи `limits`: `load15=6.0` (env `ALERTS_LOAD15_X10=60`, заменяет `ALERTS_LOAD5_X10`), `cpu_percent=90`, `cpu_minutes=45`, `page_p95_seconds=3.0`, `memory_percent=90`, `swap_bytes=10**9` (`ALERTS_SWAP_MB=1000`), `disk_urgent_share=0.07`, `bots_per_minute=150`, `bot_minutes=5`.

- [ ] **Step 1: Write the failing tests.** Перевести хелпер `healthy()` на `Host`. Добавить:
  - `test_load_uses_15_minute_mean`: 15 значений со средним 6.0 — не срабатывает; 6.1 — срабатывает; 14 значений со средним 7 — не срабатывает.
  - `test_cpu_sustained_45_minutes`: 45 значений со средним 90.5 — `cpu` срабатывает, `urgent=False`. При `inputs={"pageP95Median15m": 3.5}` дополнительно срабатывает `cpu_slow` с `urgent=True`. 44 значения — не срабатывает ничего.
  - `test_memory_and_swap`: занято 0.91 — `memory`; подкачка `1.1e9` — `memory`; 0.89 и 0.5e9 — нет.
  - `test_disk_urgent_is_separate_key`: свободно 8 % — срабатывает `disk`, но не `disk_urgent`; 6 % — оба, `disk_urgent.urgent is True`.
  - `test_bots_surge_needs_five_minutes`: `[151]*5` — `bots` срабатывает, `urgent=True`; `[151]*4 + [100]` — нет.
  - `test_existing_urgency`: `units` и `human_5xx` срочные; `backup`, `ingest`, `analysis`, `docker`, `misses`, `hit_ratio`, `bot_503`, `analysis_reference`, `analysis_tail` — нет.
- [ ] **Step 2: Run** `python -m pytest tests/test_alerts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Ряды `load5`, `cpu` и предыдущий `/proc/stat` хранить в `state` (держать 15 и 45 значений).
  - Пока ряд неполный, правило молчит.
  - Тексты правил писать в стиле существующих, например `"Процессор {x:.0f}% в среднем за 45 мин"`.
  - Значения из `inputs` используются, только если `inputs` не `None`.
- [ ] **Step 4: Run** `python -m pytest tests/test_alerts.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(alerts): пороги нагрузки по замерам — load 6/15 мин, процессор 90%/45 мин, память, диск 7%, роботы`.

### Task 3: Сбор по площадкам, MAX и Сервер 1 через снимок ops-sample

**Files:**
- Modify: `api/tools/ops_sample.py` (`COLLECTION`, `collection`, `store`)
- Modify: `operations/scripts/alerts.py`
- Test: `tests/test_ops_sample.py`, `tests/test_alerts.py`

**Interfaces:**
- Consumes: `Rule`, `evaluate(... inputs ...)` из Task 2.
- Produces:
  - `ops_sample.summarize_collection(hour_rows: list[dict], window_rows: list[dict], baseline_hours: list[list[dict]]) -> dict[str, dict]`. Аргументы — значения `sample->'collection'` за последние 60 минут, за 3 часа и за тот же час 1–4 недели назад.
  - `ops_sample.write_alert_inputs(path: Path, inputs: dict) -> None` пишет `alert-inputs.json` в `OPS_SAMPLE_STATE_DIR`, права 0644.
  - Формат файла: `{"at": float, "collection": {platform: {"hourOk": int, "hourFailed": int, "hourResults": int, "baselineOk": float | null, "lastOk": float | null, "lastResult": float | null}}, "pageP95Median15m": float | null, "nodes": {node_id: {"name": str, "observedAt": float, "diskTotal": int, "diskFree": int, "memoryTotal": int, "memoryAvailable": int, "load1": float, "cpus": int | null}}}`.
  - `alerts.read_inputs(path: Path, now: float, max_age: float = 300) -> dict | None`.
  - `alerts.FRESH_SECONDS = {"telegram": 2700, "vk": 2700, "max": 2700, "rutube": 5400}`.
  - `alerts.suppress(rules: list[Rule]) -> list[Rule]`.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_ops_sample.py::test_summarize_collection`: суммы за час, `lastOk` и `lastResult` — максимум по трём часам, `baselineOk` — медиана четырёх недельных сумм. Если недель с данными нет, `baselineOk is None`.
  - `test_collection_query_reports_last_result`: в `COLLECTION` есть столбец `last_result`, а `collection()` кладёт `lastResult`.
  - `tests/test_alerts.py`, пороги из спека:
    - `test_rutube_uses_90_minutes`: 80 минут без успешного опроса — нет, 95 — `collection_rutube`.
    - `test_telegram_45_minutes`: 50 минут — `collection_telegram` с `urgent=True`.
    - `test_hour_below_30_percent_of_baseline`: при `baselineOk=100` значение `hourOk=29` срабатывает, `31` — нет.
    - `test_failure_share_over_20_percent`: 21 из 100 — срабатывает, 19 из 100 — нет; при `hourResults < 20` доля не проверяется.
    - `test_max_without_any_results_is_auth`: у MAX `lastResult` старше 50 минут. Срабатывает `max_auth` (срочная, текст содержит «переавторизац» и `reauth-max-session.sh`), а `collection_max` подавлен.
    - `test_ingest_down_suppresses_collection`: при сработавшем `ingest` все `collection_*` и `max_auth` молчат.
    - `test_stale_inputs`: при `read_inputs(...) is None` из этой группы срабатывает только `inputs_stale` (несрочная).
    - `test_node_rules`: у узла `server-1` свободно 6 % — срабатывают `node_server-1_disk` и `node_server-1_disk_urgent`; память 91 % — `node_server-1_memory`; `load1 > 3*cpus` — `node_server-1_load`; снимок старше 30 минут — `node_server-1_silent`.
- [ ] **Step 2: Run** `python -m pytest tests/test_ops_sample.py tests/test_alerts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - В `store()` после вставки снимка выполнить три запроса:
    - строки `host_sample` за 3 часа (диапазон по первичному ключу);
    - четыре окна того же часа 1–4 недели назад;
    - последний `server_node_sample` каждого узла с `role <> 'main'` вместе с `display_name` и `report->'metrics'->>'cpus'`.
  - Затем вызвать `summarize_collection` и `write_alert_inputs`. Ошибка здесь логируется и не роняет снимок.
  - `pageP95Median15m` — медиана `traffic.p95` за 15 последних строк, `null` пропускать.
- [ ] **Step 4: Measure.**
  - На копии `mranked_prod_20261013` выполнить `EXPLAIN (ANALYZE, BUFFERS)` для каждого нового запроса, под ролью `maintenance` с `SET jit=off`.
  - Каждый должен идти по диапазону ключа и выполняться быстрее 50 мс. Записать время в описание коммита.
  - Если какой-то медленнее — переписать запрос, а не поднимать лимит.
- [ ] **Step 5: Run** `python -m pytest tests/test_ops_sample.py tests/test_alerts.py -q`. Expected: PASS.
- [ ] **Step 6: Docs.** В `operations/runbooks/TRAFFIC.md`, раздел про тревоги: новый список правил с порогами (таблица из спека), очередь бота, `alert-inputs.json`.
- [ ] **Step 7: Commit** `feat(alerts): сбор по площадкам, отозванный вход MAX и ресурсы Сервера 1`.

---

## Часть B — бот

### Task 4: Общая сводка состояния для админки и бота

**Files:**
- Modify: `api/system_overview.py`, `api/routes/system.py:33-60`
- Test: `tests/test_system_overview.py`

**Interfaces:**
- Produces: `system_overview.status_summary(rows: list[dict], now: float, threshold: Callable[[str], int]) -> dict` → `{"sampledAt": str | None, "checks": list[dict], "collection": list[dict]}`.
  - `rows` — строки `{"observed_at": datetime, "sample": dict}` за последние 3 часа и больше.
  - Свежесть, `recent` и вызов `checks()`/`collection()` переезжают сюда из роута без изменения логики.

- [ ] **Step 1: Write the failing test** `test_status_summary_matches_route_logic`. Фикстура из 4 строк, в одной площадка без `lastOk`. Ожидаемые `checks` и `collection` такие же, как раньше собирал роут: зафиксировать их значения в тесте до переноса.
- [ ] **Step 2: Run** `python -m pytest tests/test_system_overview.py -q`. Expected: FAIL (`status_summary` нет).
- [ ] **Step 3: Implement.** Роут вызывает `status_summary(rows, now, lambda p: _threshold(settings, p))` и берёт из результата `checks` и `collection`. Остальное тело ответа не меняется.
- [ ] **Step 4: Run** `python -m pytest tests/test_system_overview.py tests/test_api_admin.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `refactor(admin): сводка проверок — отдельной функцией для бота`.

### Task 5: Миграция 0087 и роль бота

**Files:**
- Create: `db/migrations/0087_telegram_bot.sql`
- Modify: `infra/postgres/init/001-create-roles.sh`, `operations/runbooks/DEPLOY.md` (раздел «2. Миграции»)
- Test: `tests/test_telegram_bot_store_postgres.py` (часть контрактных тестов из Task 9; здесь только схема)

**Interfaces:**
- Produces. Таблицы в `ops_and_admin`:
  - `bot_setting(key text PK, value jsonb NOT NULL, updated_at timestamptz, updated_by bigint)`;
  - `bot_recipient(chat_id bigint PK, kind text CHECK (kind IN ('person','chat')), title text, is_admin bool, alerts bool, digest bool, spike bool, anomaly bool, added_at timestamptz, added_by bigint)` с `CONSTRAINT bot_recipient_alerts_person CHECK (kind = 'person' OR (alerts = false AND is_admin = false))`;
  - `bot_announced(kind text, publication_id uuid, level smallint, announced_at timestamptz, PK(kind, publication_id))`;
  - `bot_alert_mute(key text PK, until timestamptz, muted_by bigint)`;
  - `bot_held_alert(id bigserial PK, event jsonb, received_at timestamptz)`;
  - `bot_week_snapshot(day date PK, stats jsonb)`;
  - `bot_job(name text PK, last_run_at timestamptz)`.
- Роль `telegram_bot`:
  - `SELECT, INSERT, UPDATE, DELETE` на `bot_*` и `USAGE` последовательности;
  - `SELECT` на `ops_and_admin.host_sample`;
  - больше ничего. Ресурсы Сервера 1 читает ops-sample (Task 3), боту права на таблицы узлов не нужны.

- [ ] **Step 1: Write the failing test** `test_chat_cannot_receive_alerts`. Тест пропускается без `MRANKED_TEST_TELEGRAM_BOT_DSN`. `INSERT` чата с `alerts=true` бросает `psycopg.errors.CheckViolation`, человека с `alerts=true` — проходит.
- [ ] **Step 2: Run** на одноразовом кластере (порядок — в памяти «Local pytest + Postgres»). Expected: FAIL (таблиц нет).
- [ ] **Step 3: Implement.**
  - Миграция пишется в стиле 0084: заголовок с откатом, `BEGIN`, `SET LOCAL lock_timeout = '5s'`, `COMMIT`.
  - Роль создать нельзя (у `migration_owner` нет `CREATEROLE`). Поэтому:
    - в init-скрипт добавить `CREATE ROLE telegram_bot NOLOGIN`, если её нет, и `GRANT CONNECT`;
    - в DEPLOY.md: «до 0087 от `mranked_bootstrap`: `CREATE ROLE telegram_bot NOLOGIN`». `LOGIN` и пароль даёт только включение бота (Task 13).
- [ ] **Step 4: Run** тест. Expected: PASS.
- [ ] **Step 5: Commit** `feat(db): 0087 — таблицы и роль Telegram-бота`.

### Task 6: Настройки и клиент Telegram

**Files:**
- Create: `telegram_bot/__init__.py`, `telegram_bot/config.py`, `telegram_bot/telegram.py`
- Test: `tests/test_telegram_bot_client.py`

**Interfaces:**
- Produces:
  - `BotConfig(token: str, admin_ids: frozenset[int], api_base_url: str, dsn: str, spool_dir: Path, timezone: str = "Europe/Moscow")` и `BotConfig.from_env(environ: Mapping[str, str]) -> BotConfig`.
    - env: `TELEGRAM_BOT_TOKEN_FILE`, `TELEGRAM_BOT_ADMIN_IDS` (через запятую), `TELEGRAM_BOT_API_BASE_URL` (по умолчанию `http://127.0.0.1:8080`), `TELEGRAM_BOT_DSN`, `TELEGRAM_BOT_SPOOL_DIR` (по умолчанию `/var/lib/m-ranked/telegram-bot/inbox`).
  - `class TelegramClient(token: str, transport: httpx.AsyncBaseTransport | None = None)` с методами:
    - `get_updates(offset: int | None, timeout: int = 50) -> list[dict]`;
    - `send_message(chat_id: int, text: str, keyboard: list[list[dict]] | None = None) -> dict`;
    - `edit_message(chat_id: int, message_id: int, text: str, keyboard: list[list[dict]] | None = None) -> None`;
    - `answer_callback(callback_id: str, text: str | None = None) -> None`;
    - `set_commands(commands: list[tuple[str, str]], scope: dict) -> None`;
    - `leave_chat(chat_id: int) -> None`.
  - Исключения: `BotBlocked(chat_id)` (403 и «chat not found»), `TelegramError`.

- [ ] **Step 1: Write the failing tests** (`httpx.MockTransport`):
  - `test_token_file_first_non_empty_line`: файл `"\n123:abc\n\n"` → `token == "123:abc"`. Если файла нет — `SystemExit` с текстом о пути.
  - `test_send_uses_html_without_previews`: в теле запроса `parse_mode=HTML` и `disable_web_page_preview=true`.
  - `test_retry_after_429_once`: на 429 с `retry_after=1` клиент ждёт (подменённым `sleep`) и повторяет один раз.
  - `test_not_modified_is_ignored`: 400 «message is not modified» — без исключения.
  - `test_forbidden_raises_bot_blocked`.
  - `test_token_never_in_errors_or_logs`: текст `TelegramError` и записи `caplog` не содержат токена.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_client.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.** `logging.getLogger("httpx").setLevel(logging.WARNING)`: httpx пишет URL с токеном на уровне INFO. `trust_env=False`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): настройки и клиент Telegram`.

### Task 7: Разбор слов `/top`

**Files:**
- Create: `telegram_bot/words.py`
- Test: `tests/test_telegram_bot_words.py`

**Interfaces:**
- Produces:
  - `Institution(legacy_id: int, short_name: str | None, name: str)`;
  - `TopQuery(who: Literal["ours","all","institution"] = "ours", institution: int | None = None, platform: Literal["all","telegram","vk","max","rutube"] = "all", period: Literal["1d","7d","30d"] = "7d", count: int | None = None, suspicious: bool = False, unknown: tuple[str, ...] = (), candidates: tuple[int, ...] = (), suggestions: tuple[str, ...] = ())`;
  - `split_command(text: str) -> tuple[str | None, str]` — `"/top@examplebot все тг"` → `("top", "все тг")`; `"топ все тг"` → `("top", "все тг")`; `"привет"` → `(None, "привет")`;
  - `parse_top(args: str, institutions: Sequence[Institution]) -> TopQuery`;
  - `normalize(word: str) -> str`;
  - `from_wrong_layout(word: str) -> str`.

- [ ] **Step 1: Write the failing tests:**
  - `test_synonyms` параметризован по всем строкам таблицы «Варианты написания» из спека, каждое слово в трёх регистрах (`тг`, `ТГ`, `Tg`).
  - `test_yo_equals_e`: `всё` = `все`.
  - `test_wrong_layout`: `ен` → telegram, `мл` → vk.
  - `test_order_free`: `"тг все месяц"` и `"месяц все тг"` дают одинаковый результат.
  - `test_all_platforms_phrase`: `"все площадки"` → `platform="all"`, `who="ours"`.
  - `test_count_clamped`: `"50"` → 20, `"0"` → 1.
  - `test_institution_by_short_and_multiword`: `"мфти месяц"` → `who="institution"`, нужный `legacy_id`; `"ниу вшэ"` находит вуз с коротким названием «НИУ ВШЭ».
  - `test_ambiguous_institution_gives_candidates`: слово, подходящее двум вузам, → `len(candidates) == 2`.
  - `test_unknown_word_is_reported`: `"абырвалг тг"` → `platform="telegram"`, `unknown=("абырвалг",)`, `suggestions` из `difflib.get_close_matches(cutoff=0.75)`.
  - `test_command_with_bot_suffix`: `split_command("/top@examplebot все")`.
  - `test_defaults`: `parse_top("", [])` == `TopQuery()`.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_words.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Словари синонимов — константы модуля, ровно по таблице спека.
  - «все» — это `who`, кроме случая, когда следом идёт «площадки».
  - Название вуза ищется сначала по самым длинным сочетаниям оставшихся слов (n-граммы), потом по точному совпадению с нормализованными `short_name`/`name`, потом по уникальной подстроке.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): разбор слов /top с синонимами и поиском вуза`.

### Task 8: Чтение API и тексты сообщений

**Files:**
- Create: `telegram_bot/source.py`, `telegram_bot/render.py`
- Test: `tests/test_telegram_bot_render.py`, `tests/test_telegram_bot_source.py`, фикстуры `tests/fixtures/telegram_bot/*.json` (ответы findings, anomalous, dashboard, forecast; снять с локального стенда или собрать по `dto.finding`)

**Interfaces:**
- Consumes: `TopQuery`, `Institution` (Task 7).
- Produces:
  - `class ApiSource(client: httpx.AsyncClient)` с методами:
    - `findings(*, institution: int | None, platform: str, period: str, suspicious: bool) -> dict` → `GET /api/v1/findings` с `mode=institution|all`, `limit=50` и `anomalies=include|exclude`, без `sort`/`direction`/`group`;
    - `anomalous(*, institution: int, period: str) -> dict`;
    - `dashboard() -> dict` (`period=7d`);
    - `forecast() -> dict | None` (404 → `None`);
    - `institutions() -> list[Institution]` — из поля `institutions` ответа findings, кэш в памяти 1 час.
  - `SourceUnavailable` для сетевых ошибок и ответов 5xx.
  - `Message(text: str, keyboard: list[list[dict]] | None = None)`.
  - Функции `render`:
    - `render_top(query: TopQuery, body: dict, our_id: int | None, period_label: str) -> list[Message]`;
    - `top_keyboard(query: TopQuery) -> list[list[dict]]`;
    - `encode_callback(query: TopQuery) -> str`, `decode_callback(data: str) -> TopQuery | None`;
    - `render_week(current: dict, previous: dict | None, forecast: dict | None, our_id: int) -> Message`;
    - `render_digest(ours: dict, others: dict, current: dict, previous: dict | None, forecast: dict | None, our_id: int) -> list[Message]`;
    - `render_help(*, alerts: bool, admin: bool) -> str`;
    - `split_message(text: str, limit: int = 4096) -> list[str]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_source_requests_match_site_defaults`: в запросе ровно `mode`, `platform`, `period`, `anomalies`, `limit=50` (плюс `institution` в режиме вуза), заголовок `user-agent: m-ranked-telegram-bot/1`.
  - `test_source_unavailable_on_5xx_and_connect_error`.
  - `test_render_ours_groups_by_platform`: по 3 поста на площадку; если выше нормы только 2 — строка «выше нормы только 2».
  - `test_render_all_marks_us_and_promotion`: пост нашего вуза помечен «мы», пост с `promotion: true` — «📣 продвижение»; внизу «Скрыто подозрительных: N» из `hiddenAnomalous`.
  - `test_line_format`: строка содержит вуз, `<a href="publicUrl">`, `×5,1` (десятичная запятая) и просмотры `9,2 тыс.`.
  - `test_html_is_escaped`: название `A<b>&"c` экранировано, `href` экранирован.
  - `test_long_output_is_split_on_lines`: каждая часть ≤ 4096 символов, строки не рвутся.
  - `test_callback_roundtrip_under_64_bytes`: для любого `TopQuery` из сетки (кто × площадка × период × сколько × подозрительные) `decode(encode(q)) == q` и `len(encode(q).encode()) <= 64`. Мусор → `None`.
  - `test_keyboard_marks_current_choice`.
  - `test_week_without_previous`: текст содержит «сравнение появится через неделю».
  - `test_week_forecast_line`: «≈12-е ± 7» берётся из `rows[…].categories.social.rank` и `errors.social`; при `early: true` добавлено «ранний прогноз».
  - `test_digest_others_exclude_us`: в блоке «у других» нет нашего `legacyId`, и в нём 10 постов.
  - `test_help_lists_all_word_kinds`: в `/help` есть «кто», «площадка», «период», «сколько», примеры `/top все тг` и `/top мфти месяц`. При `alerts=True` есть `/status`, при `admin=True` — `/settings`.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_render.py tests/test_telegram_bot_source.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - `httpx.AsyncClient(base_url=…, trust_env=False, timeout=30, limits=httpx.Limits(max_connections=1))`.
  - Тексты `/help` — блок из спека.
  - «Наши» и конкретный вуз: один запрос `platform=all`, разбор по площадкам на стороне бота. Если `hasMore` и на какой-то площадке меньше нужного — догрузить именно эту площадку.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): чтение API и тексты ответов`.

### Task 9: Хранилище

**Files:**
- Create: `telegram_bot/store.py`
- Test: `tests/test_telegram_bot_store.py` (на `MemoryStore`), `tests/test_telegram_bot_store_postgres.py` (тот же набор на `PostgresStore`, пропускается без `MRANKED_TEST_TELEGRAM_BOT_DSN`)

**Interfaces:**
- Produces:
  - `Recipient(chat_id: int, kind: Literal["person","chat"], title: str, is_admin: bool = False, alerts: bool = False, digest: bool = False, spike: bool = False, anomaly: bool = False)`. `__post_init__` бросает `ValueError`, если `kind == "chat"` и `alerts` или `is_admin` выставлены.
  - `class Store(Protocol)` с асинхронными методами:
    - `get_setting(key: str) -> Any`, `set_setting(key: str, value: Any, by: int) -> None`;
    - `recipients() -> list[Recipient]`, `upsert_recipient(r: Recipient, by: int | None) -> None`, `remove_recipient(chat_id: int) -> None`, `migrate_chat(old: int, new: int) -> None`;
    - `mark_announced(kind: str, publication_id: str, level: int) -> bool` — `True`, если запись новая или уровень вырос;
    - `has_announced_any(kind: str) -> bool`;
    - `set_mute(key: str, until: float, by: int) -> None`, `muted_until(key: str) -> float | None`;
    - `hold_alert(event: dict) -> None`, `take_held() -> list[dict]`;
    - `save_week_snapshot(day: date, stats: dict) -> None`, `week_snapshot(day: date) -> dict | None`;
    - `job_last_run(name: str) -> float | None`, `set_job_run(name: str, at: float) -> None`;
    - `prune(now: float) -> None` (объявления старше 60 дней, снимки старше 30 дней, истёкшие заглушки);
    - `status_rows(seconds: int) -> list[dict]` (`host_sample`).
  - `MemoryStore()` и `PostgresStore(dsn: str)` (psycopg `AsyncConnection`, одно соединение, переподключение при обрыве).
  - Ключи настроек: `"our_institution"` (legacy id, int).

- [ ] **Step 1: Write the failing tests** — один набор `@pytest.mark.parametrize("store", ...)`:
  - `test_chat_alerts_rejected`;
  - `test_announce_dedup_and_level_up`: 2 → `True`, 2 → `False`, 3 → `True`;
  - `test_take_held_empties`;
  - `test_migrate_chat_keeps_flags`;
  - `test_prune_drops_old`;
  - `test_mute_expiry`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** SQL — только по таблицам 0087 и `host_sample`. `statement_timeout = '5s'`.
- [ ] **Step 4: Run** (Postgres-вариант — на одноразовом кластере с применённой 0087). Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): хранилище настроек и состояния`.

### Task 10: Доступ, команды, кнопки, чаты

**Files:**
- Create: `telegram_bot/access.py`, `telegram_bot/handlers.py`, `telegram_bot/status.py`
- Test: `tests/test_telegram_bot_handlers.py` (`FakeTelegram` записывает вызовы, `FakeSource` отдаёт фикстуры Task 8, `MemoryStore`)

**Interfaces:**
- Consumes: Task 6–9; `system_overview.status_summary` (Task 4).
- Produces:
  - `Access(user_id: int | None, chat_id: int, private: bool, admin: bool, alerts: bool, known_person: bool, known_chat: bool)`;
  - `access_for(message: dict, recipients: list[Recipient]) -> Access`;
  - `allowed(command: str, access: Access) -> bool`;
  - `class Bot(telegram: TelegramClient, source: ApiSource, store: Store, config: BotConfig, clock: Callable[[], float])` с методами `setup() -> None`, `handle(update: dict) -> None`, `broadcast(text_or_messages, flag: Literal["digest","spike","anomaly","alerts"]) -> None`;
  - `status.render_status(rows: list[dict], now: float) -> str` — 5–6 строк: сбор по площадкам, приём с Сервера 1, очередь анализа, службы, диск, память.

- [ ] **Step 1: Write the failing tests:**
  - `test_allowed_matrix` — таблица команд из спека: `top/week/digest/help` разрешены `known_person or known_chat`; `status` — `alerts and private`; `settings` — `admin and private`; `id/start` — всем.
  - `test_stranger_gets_only_id_hint`: незнакомец на `/top` получает одну строку с подсказкой `/id`, источник данных не вызывается.
  - `test_group_member_can_top`: любой участник подключённого чата получает ответ с кнопками.
  - `test_status_refused_in_group`: в группе — отказ без данных; в личке человеку из списка тревог — `render_status`.
  - `test_callback_edits_same_message`: нажатие кнопки вызывает `edit_message` с тем же `message_id` и `answer_callback`.
  - `test_unknown_word_line`: ответ содержит «не понял: абырвалг» и `/help`.
  - `test_no_institution_yet`: если `our_institution` не задан, `/top` отвечает «админ ещё не выбрал наш вуз: /settings».
  - `test_source_down_message`: `SourceUnavailable` → «данные временно недоступны», без исключения.
  - `test_added_by_admin_registers_chat`: `my_chat_member` от админа → `Recipient(kind="chat", digest=True, spike=True, anomaly=True)`. От не-админа → `leave_chat`. Бот удалён → `remove_recipient`.
  - `test_migrate_to_supergroup`: `migrate_to_chat_id` → `migrate_chat`.
  - `test_blocked_recipient_removed`: при `BotBlocked` во время `broadcast` получатель удаляется, рассылка продолжается.
  - `test_settings_flow`: админ ставит наш вуз (ввод названия, затем выбор кнопкой при неоднозначности), добавляет человека по ID и включает ему тревоги. Включить тревоги чату нельзя: кнопки нет, `Recipient` бросает исключение.
  - `test_setup_commands_scopes`: `set_commands` вызывается для групп `[top, week, digest, help, id]`, для каждого человека из списка тревог — плюс `status`, для админа — плюс `settings`. Админы из `config.admin_ids` записаны как люди с `is_admin=True, alerts=True`.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_handlers.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Ожидание ввода в `/settings` хранится в памяти: `pending: dict[int, str]`.
  - Кнопки настроек — префикс callback `s|`, кнопки `/top` — `t|`, заглушка тревог — `m|`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): команды, кнопки, доступ и подключение чата`.

### Task 11: Дайджест и контентные уведомления

**Files:**
- Create: `telegram_bot/content.py`
- Test: `tests/test_telegram_bot_content.py`

**Interfaces:**
- Consumes: `Bot.broadcast`, `ApiSource`, `Store`, `render_digest`, `render_week`.
- Produces:
  - константы `SPIKE_INDEX = 3.0`, `SPIKE_MAX_AGE_HOURS = 48`, `CHECK_EVERY_SECONDS = 900`, `DIGEST_WEEKDAY = 0`, `DIGEST_HOUR = 10`, `SNAPSHOT_HOUR = 9`, `MORNING_HOUR = 8`;
  - `due(now: datetime, last: Mapping[str, float | None]) -> list[str]` — имена из `{"alerts", "spikes", "anomalies", "week_snapshot", "digest", "morning", "prune"}`;
  - `async check_spikes(bot) -> int`, `async check_anomalies(bot) -> int`, `async record_week(bot) -> None`, `async send_digest(bot) -> None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_due_digest_monday_10`: понедельник 09:59 — нет; 10:00 — `digest`; 10:05 после отправки на этой ISO-неделе — нет; вторник без отправки в понедельник — да (догнать один раз).
  - `test_due_every_15_minutes`: `spikes`/`anomalies` идут не чаще раза в 900 секунд, `alerts` — на каждом тике.
  - `test_spike_thresholds`: 47 ч и ×3.0 — объявляется; 49 ч — нет; ×2.9 — нет; повторный прогон — не повторяется; продвигаемый пост приходит с «📣 продвижение».
  - `test_first_run_seeds_silently`: при `has_announced_any("spike") is False` прогон помечает подходящие посты и ничего не шлёт. То же для `anomaly`.
  - `test_anomaly_levels`: уровень 2 — текст «Вероятно, накрутка», затем уровень 3 — «Накрутка» (второе сообщение); уровень 1 — ничего.
  - `test_spike_goes_only_to_subscribers`: только получатели с `spike=True`.
  - `test_record_week_saves_our_stats`: из `dashboard.stats` сохраняются строки нашего `institutionId` по площадкам.
  - `test_digest_contents`: наши топ-3 по площадкам, 10 у других без нас, неделя к неделе, строка прогноза.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_content.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - «Выстрелил» читает `findings(institution=ours, platform="all", period="7d", suspicious=True)`.
  - «Накрутка» читает `anomalous(institution=ours, period="7d")`.
  - Неделя к неделе сравнивает снимок за сегодня и за `today - 7 дней`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): дайджест, «выстрелил», «накрутка», неделя к неделе`.

### Task 12: Доставка тревог

**Files:**
- Create: `telegram_bot/alerts_inbox.py`
- Test: `tests/test_telegram_bot_alerts.py`

**Interfaces:**
- Consumes: формат файла очереди из Task 1; `Store`; `Bot.broadcast(..., "alerts")`.
- Produces:
  - `read_inbox(spool: Path) -> list[tuple[Path, dict]]` — по имени файла; файл с неверным JSON удаляется с записью в журнал;
  - `is_quiet(now: datetime) -> bool` — 23:00–08:00;
  - `async deliver(bot, now: datetime) -> None`;
  - `async morning(bot, now: datetime) -> None`;
  - `alert_text(event: dict) -> str` — `"m-ranked · {server}\n"` и строка в формате `format_event` из Task 1.

- [ ] **Step 1: Write the failing tests:**
  - `test_quiet_boundaries`: 22:59 — шлётся; 23:00 и 07:59 — откладывается; 08:00 — шлётся.
  - `test_urgent_breaks_quiet`: срочное в 03:00 отправлено.
  - `test_mute_drops_open_and_repeat_not_resolve`.
  - `test_mute_button`: под open/repeat есть кнопка `m|{key}`. Нажатие ставит заглушку на `now + 7200` и правит сообщение («🔕 заглушено … до HH:MM»).
  - `test_morning_collapses_night`: если за ночь тревога открылась и закрылась, утром одна строка «за ночь открылась и закрылась»; ещё открытые — отдельными строками; всё одним сообщением.
  - `test_send_failure_keeps_file`: при `TelegramError` файл остаётся до следующего тика.
  - `test_chats_never_get_alerts`: даже если в хранилище подложить чат с `alerts=True` в обход `Recipient`, `deliver` шлёт только `kind == "person"`.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_alerts.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): доставка тревог — тихие часы, заглушка, утренняя сводка`.

### Task 13: Основной цикл и необязательный деплой

**Files:**
- Create: `telegram_bot/__main__.py`, `operations/systemd/m-ranked-target-telegram-bot.service`, `operations/env/telegram-bot.env.example`, `operations/runbooks/TELEGRAM_BOT.md`
- Modify: `operations/runbooks/DEPLOY.md` (список юнитов, ссылка на TELEGRAM_BOT.md)
- Test: `tests/test_telegram_bot_main.py`, `tests/test_telegram_bot_deploy.py`

**Interfaces:**
- Consumes: всё из Task 6–12.
- Produces: `async run(config: BotConfig, *, stop: asyncio.Event) -> None` — `setup()`, затем параллельно `get_updates` и тик раз в 60 секунд по `due()`. `main() -> int` для `python -m telegram_bot`.

- [ ] **Step 1: Write the failing tests:**
  - `test_job_error_does_not_stop_loop`: исключение в одной задаче записано в журнал, следующий тик выполняется.
  - `test_stop_event_exits`.
  - `tests/test_telegram_bot_deploy.py`:
    - `test_unit_is_optional_and_bounded`: в юните есть `ConditionPathExists=/etc/m-ranked/credentials/telegram-bot-token`, `MemoryMax=128M`, `CPUQuota=20%`, `User=m-ranked-telegram-bot`; `ExecStart` идёт через `.venv/bin/python -m telegram_bot`.
    - `test_not_wanted_by_profiles`: ни один `operations/systemd/*.target` не содержит `telegram-bot`.
    - `test_env_example_has_no_values`: все значения в `telegram-bot.env.example` пустые или `http://127.0.0.1:8080`.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_main.py tests/test_telegram_bot_deploy.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Юнит:
    - защиты как у `m-ranked-target-ops-sample.service`;
    - токен через `LoadCredential=telegram-bot-token:/etc/m-ranked/credentials/telegram-bot-token` и `TELEGRAM_BOT_TOKEN_FILE=%d/telegram-bot-token`;
    - pgpass по образцу ops-sample;
    - `ExecStartPre=+/usr/bin/install -d -o m-ranked-telegram-bot -g root -m 0770 /var/lib/m-ranked/telegram-bot/inbox`;
    - `Restart=on-failure`, `RestartSec=30`, `Nice=10`.
  - Runbook:
    - **Включение:** `useradd --system m-ranked-telegram-bot`; `ALTER ROLE telegram_bot LOGIN PASSWORD …` и файл `/etc/m-ranked/credentials/telegram-bot-pgpass`; env-файл с ID админа; копия юнита; `daemon-reload`; `enable --now`; проверка `/id` и `/status`.
    - **Выключение:** `disable --now`, удалить каталог `inbox` (alerts.py вернётся к журналу), `ALTER ROLE telegram_bot NOLOGIN`.
    - **Откат порогов alerts.py.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): основной цикл, юнит и runbook — бот подключается по желанию`.

### Task 14: Проверка и замеры

**Files:** без новых файлов. Итоги — в описании PR.

- [ ] **Step 1: Full suite.** `python -m pytest -q` на одноразовом Postgres (память «Local pytest + Postgres»). Expected: падают только известные старые тесты (3 + 12 + 1 из памяти); сверить с `main`.
- [ ] **Step 2: Cache check on the local stand** (API на копии базы, память «Local web stand»):
  - вызвать каждый метод `ApiSource` дважды;
  - при втором вызове API не пересобирает ответ (журнал API или метрики кэша);
  - запрос findings бота попадает в тот же ключ, что запрос страницы «Находки» с теми же фильтрами.
- [ ] **Step 3: Resource baseline (production, read-only).** Снять за 24 часа до выкатки по `host_sample`: процессор, память, p95 страниц (те же запросы, что в приложении спека). Потом то же за 24 часа после.
  - `systemctl show m-ranked-target-telegram-bot -p MemoryCurrent,CPUUsageNSec` — меньше 100 МБ.
  - Длительность запуска alerts и ops-sample не выросла больше чем на 10 %.
- [ ] **Step 4: Prod rollout** — только после «делай» владельца: релиз-оверлей по памяти «Prod release procedure», миграция 0087, затем включение по runbook. Порядок: сначала часть A (тревоги пишутся в журнал), потом бот.
- [ ] **Step 5: Smoke in Telegram** (владелец):
  - `/id`, `/help`, `/top`, `/top все тг`, кнопки, `/week`, `/digest`, `/status` в личке и отказ в чате;
  - добавить бота в рабочий чат, затем в BotFather выключить «Allow Groups».
