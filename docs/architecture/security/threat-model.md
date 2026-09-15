# Threat model

- Status: **Proposed**
- Scope: целевая архитектура M-Ranked
- Method: STRIDE + отдельные риски качества публичных данных
- Diagram: [trust boundaries](threat-boundaries.puml)

## Цели безопасности

1. Не раскрыть Telegram/Telegram Web/MAX sessions, VK token, OIDC credentials,
   ключи backup и учетные данные БД.
2. Не позволить незаметно изменить историю наблюдений, опубликованную формулу,
   сопоставление университета или результат рейтинга.
3. Сохранять происхождение, время и качество каждого результата так, чтобы его
   можно было воспроизвести.
4. Не смешивать административные и публичные права или cache entries.
5. Выдерживать отказ/лимиты одной социальной сети без остановки остальных сетей
   и публичного сайта.
6. Восстанавливаться после потери primary, ошибочного изменения и повреждения
   данных в пределах утвержденных RPO/RTO.

## Защищаемые активы

| Актив | Требование |
|---|---|
| Platform credentials и session files | Конфиденциальность, ротация, минимальные права |
| История метрик и subscriber counts | Целостность, происхождение, доступность |
| Формулы, компоненты и версии | Целостность, неизменяемость опубликованных версий |
| Institution/account mappings | Целостность и аудит, поскольку ошибка меняет рейтинг вуза |
| Admin identities, roles и audit log | Подлинность, неотказуемость, минимальные права |
| Dataset revision и cache key space | Целостность и изоляция public/private данных |
| Backup/WAL/cold archive | Конфиденциальность, целостность, восстанавливаемость |
| Публичная доступность сайта/API | Доступность и контролируемая деградация |

## Trust boundaries

- **TB-1 Internet edge:** весь пользовательский ввод недоверенный; только Nginx
  доступен из Internet.
- **TB-2 application:** Next.js, FastAPI и collectors запускаются разными Unix
  users/units; вызовы revalidation и management аутентифицируются.
- **TB-3 data:** PostgreSQL доступен только локально или по приватной сети;
  каждому процессу выдается отдельная минимальная роль.
- **TB-4 DR:** репликация, WAL и архив пересекают границу физического сервера
  только по шифрованному каналу и проверяются checksum.
- Ответы социальных сетей и M-Рейтинга остаются недоверенными даже при HTTPS.

## Основные потоки данных

| Поток | Вход | Контроль | Выход |
|---|---|---|---|
| Public request | path/query/header | limits, schema validation, canonicalization | LRU или bounded read-only query |
| Admin command | identity, CSRF token, JSON | RBAC, optimistic lock, validation, audit | transaction + revision event |
| Collection | platform response | allowlisted endpoint, size limits, normalization, quality flags | append-only observation |
| Rating run | formula version + immutable input revision | validation, deterministic decimal calculation | result + component trace |
| Export | bounded query | authorization where needed, row/size/time quota, CSV escaping | streamed file |
| Backup | PostgreSQL pages/WAL | encryption, checksum, retention, restore drill | recoverable restore point |

## Реестр угроз

Оценки качественные: `H` — высокая, `M` — средняя, `L` — низкая. Владелец
контроля назначается перед реализацией.

| ID | STRIDE | Угроза и последствие | L/I | Обязательные контрмеры | Проверка |
|---|---|---|---|---|---|
| TM-01 | I/E | Утечка platform session/token из env, логов, backup или raw payload | M/H | Отдельный secret store/file `0600`, запрет secret logging, redaction, ротация, encrypted backup | secret scanning; тест redaction; quarterly rotation drill |
| TM-02 | S/E | Захват admin session или ошибочная выдача роли | M/H | OIDC/MFA где доступно, short sessions, secure cookies, deny-by-default RBAC, отдельный management surface | integration tests по каждой роли; auth event alerts |
| TM-03 | T/E | CSRF или mass assignment меняет вуз, аккаунт, mapping, formula | M/H | CSRF, command DTO allowlist, method authorization, optimistic version, audit before/after | negative security tests |
| TM-04 | T/I | XSS через title/username/source URL либо unsafe JSON в SSR | M/H | Escape by default, запрет raw HTML, CSP, URL scheme allowlist, sanitize rich content, local pinned assets | CSP report; browser security tests |
| TM-05 | I/E | SSRF через account URL, emoji proxy, redirect или import endpoint | M/H | Host allowlist after every redirect, DNS/IP validation, no link-local/private targets, egress allowlist, byte/time limits | SSRF test corpus including redirects and DNS rebinding |
| TM-06 | T | SQL injection или небезопасный dynamic order/filter | L/H | Bind parameters, enum allowlists, static SQL modules, no raw user fragments | SAST plus endpoint fuzzing |
| TM-07 | T/R | Подмена, replay или дублирование platform response создает ложные snapshots | M/H | TLS, source fingerprint, idempotency constraints, collection_run lineage, append-only corrections | replay/duplicate contract tests |
| TM-08 | T/R | Админ незаметно меняет опубликованную формулу или external mapping | M/H | Published formula immutable, four-eyes approval для publish, version/hash, append-only audit | audit reconciliation; mutation tests |
| TM-09 | D | Дорогой compare/export истощает DB, heap или network | H/H | Pagination, statement timeout, bounded windows, async export quota, rate limit, cancellation, bounded live queries | load/soak tests and per-route budgets |
| TM-10 | D | Рост snapshots/raw/WAL заполняет 30 GB и останавливает БД | H/H | Partition retention, raw TTL, WAL/archive monitoring, disk quotas, alerts at 70/85%, fail-safe purge | capacity forecast; forced-low-disk game day |
| TM-11 | D | FloodWait/лимит/изменение API одной сети блокирует общий цикл | H/M | Independent units/leases, per-platform timeout/bulkhead, bounded retry+jitter, last-known-data UI | dependency failure injection |
| TM-12 | T/I | Cache poisoning, устаревший ответ или попадание private response в public cache | M/H | Canonical keys, tag invalidation, `no-store` admin/auth, explicit Vary, payload schema/version, short TTL | cache isolation and lost-event tests |
| TM-13 | I/T | CSV formula injection при открытии export в spreadsheet | M/M | Prefix dangerous leading cells, correct RFC 4180 quoting, content disposition, document behavior | malicious value fixture |
| TM-14 | T/D | Ошибочный DELETE/DDL мгновенно повторяется на standby | M/H | Least privilege, DDL review, PITR backups independent of replica, delayed/immutable copy where feasible | restore to time before destructive event |
| TM-15 | I | Backup или cold archive скопирован с DR-сервера | M/H | Encryption at rest with separate key, restricted Unix user, no public port, access log, key rotation | restore with rotated key; permission audit |
| TM-16 | T | Supply-chain compromise Python dependency, npm или container | M/H | Lockfiles+hashes, pin git commit, dependency review, SBOM, signed releases, minimal build permissions | CI vulnerability/license scan; provenance check |
| TM-17 | T | Ошибка времени/часового пояса меняет bucket, delta или рейтинг | M/H | UTC `timestamptz`, NTP alert, DB clock for commit, explicit `as_of`, deterministic tests around DST | clock-skew and boundary tests |
| TM-18 | T | Внешний участник искусственно меняет публичные счетчики | H/M | Сохранять наблюдение как факт источника, quality/provenance, устойчивые агрегаты, anomaly signal и sensitivity analysis | synthetic manipulation datasets |
| TM-19 | R | UI или отчет называет сигнал доказанной «накруткой» | M/H | ADR-006 terminology, explanation/evidence, human review, publication checklist | content tests and review gate |
| TM-20 | R/I | Подробные ошибки/health раскрывают внутренние пути, версии или account IDs | M/M | Публичный health минимален, details только оператору, sanitized error codes, request ID | unauthenticated endpoint review |

## Ключевые abuse cases

### Публичный API

- Клиент перебирает очень широкие интервалы или тысячи university IDs.
- Клиент создает множество уникальных cache keys параметрами с тем же смыслом.
- Бот параллельно формирует крупные экспорты и не скачивает результаты.
- Внешнее название начинается с `=`, `+`, `-` или `@` и попадает в CSV.

### Админка

- Пользователь с `VIEWER` вызывает командный endpoint напрямую.
- Две вкладки одновременно меняют официальный account mapping.
- Импорт рейтинга повторно публикует тот же источник под новой датой.
- Администратор вставляет URL на private IP или redirect chain.

### Collectors

- Платформа возвращает `0` после ранее положительного счетчика.
- Ответ неожиданно огромный, содержит неверный timestamp или меняет тип поля.
- Account переименован или внешний ID переиспользован.
- Два экземпляра collector одновременно обрабатывают один account.
- Session истекла, но бесконечный retry создает блокировку аккаунта.

## Security requirements перед public release

- Все external endpoints имеют allowlist, timeout, максимальный размер ответа и
  bounded retry.
- PostgreSQL roles разделены как минимум на `api_read`, `api_write_admin`,
  `collector_ingest`, `migration_owner`, `backup`.
- Ни PostgreSQL, ни административные health details не доступны из Internet.
- Административная команда создает audit event с identity, correlation ID,
  target, outcome и безопасным before/after.
- Публичные запросы имеют rate/row/time limits; экспорт выполняется потоково.
- В CI есть dependency scanning, secret scanning, SAST и security integration
  tests для RBAC/cache/SSRF/CSV.
- Backup считается существующим только после успешного автоматического restore;
  полный drill проводится не реже одного раза в квартал.
- Тексты и API следуют ADR-006 и не утверждают намеренную искусственную
  активность без независимых подтверждений.

### Где эти требования реализованы

- Fetch по ссылкам каталога ограничен списком хостов и проверяется дважды: на
  входе админского API (`_rutube_url` в `api/routes/admin.py`) и в самом
  коллекторе перед запросом (`channel_page_url` в `collector_runtime/rutube.py`).
  Клиент коллектора не следует redirect вовсе: и страница канала, и вызовы API
  проверяют каждый переход, а `IPAddressDeny` в
  `m-ranked-target-collector@.service` закрывает внутренние диапазоны.
- Вход администратора — отдельная транзакция: имя, пароль и одноразовый код
  предъявляются один раз в `POST /api/v1/admin/session`, код тратится при
  создании сессии, дальше работает непрозрачный токен в куке `__Host-`
  (`api/security.py`, `api/sessions.py`). Сессии, учёт кодов и замедление
  перебора лежат в PostgreSQL (`db/migrations/0025_admin_session.sql`), поэтому
  переживают перезапуск и общие для воркеров.
- Замедление считается по адресу источника, а не по учётной записи: чужие
  неудачные попытки не могут закрыть вход владельцу. Проверка пароля идёт под
  ограниченным по числу семафором, поэтому поток входов не съедает ядро.
- Известное и неизвестное имя проходят одинаковый путь: одна проверка bcrypt
  одинаковой стоимости у всех записей и одинаковое число проверок кода.
- CSRF-токен привязан к конкретной сессии подписью её идентификатора: токен
  одной сессии не подходит к другой и перестаёт работать после выхода.
- Строгая политика содержимого с одноразовым nonce включена для панели
  управления (`frontend/proxy.ts`). Присланные клиентом заголовки политики и
  nonce удаляются, поэтому чужой заголовок не задаст странице предсказуемый
  nonce.
- Журнал событий безопасности и счётчики — `api/security_events.py`; счётчики
  публикуются текстовым файлом Prometheus, алерты лежат в
  `operations/observability/security-alerts.yml`.
- Зависимости продуктовых образов закреплены хешами
  (`requirements/*.lock`), образы собираются и сканируются в CI по факту, SBOM
  снимается с самого образа, а вложение провенанса заверяет SBOM. Пороги выпуска
  и порядок исключений — `dependency-policy.md`.
- Ограничение состава продуктовых образов проверяется автоматически: задание
  `supply-chain` сверяет SBOM каждого окружения со списком запрещённого
  инструментария.

Не закрыто:

- Федеративный вход (OIDC) остаётся отдельной работой: выбор поставщика —
  решение не кода. Граница для него уже есть — `current_session` и `principal`
  в `api/security.py` — и пароль с кодом живут в одном месте.
- `style-src` сохраняет `'unsafe-inline'`: Recharts печатает `<style>` прямо в
  разметку. Владелец — фронтенд, срок — до 2026-12-31.
- Публичные страницы остаются на прежней политике со `script-src
  'unsafe-inline'`: они отдаются из кэша, а nonce в кэше устаревает раньше, чем
  доходит до читателя. Замер показал, что попытка выдавать nonce и им ломает
  отрисовку части страниц. Следующий шаг — хеши инлайн-скриптов, не nonce.
  Владелец — фронтенд, срок — до 2026-12-31.
- Отчёты о нарушениях политики никуда не отправляются: приёмник отчётов с
  ограничением частоты не поднят, нарушения видны только в консоли браузера.
  Владелец — эксплуатация, срок — до 2026-12-31.
