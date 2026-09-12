# Эксплуатация

Перенесено из README, чтобы корневой файл оставался коротким.

## Миграция на целевой стек

Текущая версия `alpha` использует Next.js 16 / React 19, Spring на Java 21,
PostgreSQL 18.6 и Redis 8.10.0. Frontend требует Node 24; CI и серверный
импортёр используют Python 3.13. Новая БД создаётся напрямую из единой схемы
`storage-publisher-final-2026-09-08-r4`; version-chain не используется.

Серверный переход начат 6 сентября 2026 года: PostgreSQL установлен, идёт
перенос проверенного снимка SQLite. На главной странице временно показывается
прогресс; старые сборщики продолжают записывать новые данные в SQLite.
Завершение переноса, догрузка новых записей и переключение приложения
проверяются отдельно; Writer Gate W остаётся закрытым. Подробности:

Статус маршрутов и проверок:
[запуск обязательных локальных проверок](migration/integration/README.md),
[эксплуатация](operations/README.md). Локальные результаты не разрешают
production-переключение или удаление установленной там legacy-версии.

### Изменения этой версии

- Аккаунты и публикации всех площадок открываются по общим UUID-адресам;
  старые числовые ссылки перенаправляются с сохранением параметров просмотра.
- История использует общие компоненты графиков и таблицы метрик; выбранный
  на графике замер можно найти в таблице истории.
- Финальная схема сохраняет исходный baseline даже у импортированной публикации с
  принудительно неполной историей. Обновление сборщиком сохраняет её UUID
  и исходное решение о baseline; новая полная история задним числом не создаётся.
- Баллы официального рейтинга переносятся через Decimal без потери последних
  десятичных разрядов. Импорт возобновляется с зафиксированной контрольной точки.
- Партиции и права подготавливаются один раз на месяц публикации в каждом
  пакете импорта. Таймер прогресса исключает паузы и перезапуски.
- Исправлены обе проверки GitHub Actions: окружение Python, временные
  каталоги, права инспектора тестовой БД и проверки текущего интерфейса.

## Развёртывание на Debian 12/13

Текущий Next.js/Spring-стек устанавливается по
[runbook развёртывания](operations/runbooks/DEPLOY.md).
Для сервера с 2 GiB RAM добавлен
[production-small overlay](infra/compose.production-small.yaml) к
`infra/compose.yaml`: он ограничивает PostgreSQL по памяти, CPU, соединениям
и WAL. Во время начального переноса запускается только PostgreSQL;
параметры overlay не заменяют проверку ресурсов и восстановления.

Том на 30 ГБ не расширяется, поэтому объём базы отслеживается отдельно:
[runbook ёмкости](operations/runbooks/CAPACITY.md) описывает словарь
`metric_evidence`, ограниченный по месяцам backfill с побайтовой сверкой и
разбор индексов, которые ни разу не сканировались.

### Python-сборщики SQLite в переходный период

Следующие команды относятся к сохранённым сборщикам `app`, а не к установке
Next.js/Spring. Этот путь нужен, пока сервер завершает перенос данных.

```bash
apt-get update
apt-get install -y python3 python3-venv ca-certificates
useradd --system --home /opt/telegram-reaction-monitor --shell /usr/sbin/nologin telegram-monitor || true
mkdir -p /opt/telegram-reaction-monitor/{data,logs}
cd /opt/telegram-reaction-monitor
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
chown -R telegram-monitor:telegram-monitor /opt/telegram-reaction-monitor
```

Для публичных каналов используется `DATA_SOURCE=public_web`; Telegram-сессия
не нужна. Режим `DATA_SOURCE=telegram_web` добавляет точные комментарии после
входа по номеру командой `python -m app auth-web` и не требует приложения на
`my.telegram.org`. Ему нужен Chromium для Playwright; установка и безопасное
хранение профиля описаны в [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md). MTProto-режим
требует `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` и команды `python -m app auth`.

## Команды сборщиков

Сборщики нового стека пишут непосредственно в PostgreSQL. Каждый процесс
обслуживает одну площадку; DSN задаётся через `COLLECTOR_DATABASE_URL`.
Контракт запуска, сессии, роли и systemd описаны в
[collector_target/README.md](collector_target/README.md).

```bash
rtk .venv/bin/python -m collector_target --platform telegram
rtk .venv/bin/python -m collector_target --platform vk
rtk .venv/bin/python -m collector_target --platform max
rtk .venv/bin/python -m collector_target --platform rutube
```

Сохранённые команды для SQLite и настройки сессий:

```bash
.venv/bin/python -m app add-channel https://t.me/s/example
.venv/bin/python -m app list-channels
.venv/bin/python -m app list-institutions
.venv/bin/python -m app add-institution "Название вуза" --short-name "Короткое имя"
.venv/bin/python -m app add-platform-account 1 vk university --url https://vk.com/university
.venv/bin/python -m app sync-official-accounts
.venv/bin/python -m app refresh-m-rating
.venv/bin/python -m app auth-web
.venv/bin/python -m app poll-now
.venv/bin/python -m app collect
.venv/bin/pytest -q
```

Python-команда `collect` запускает только сбор данных. Для интерфейса alpha
используйте Next.js и Spring; старые команды `web` и `run` больше недоступны.
Сохранившийся unit сборщика можно установить отдельно:

```bash
cp operations/systemd/m-ranked-collector.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now m-ranked-collector.service
```

Конфигурация целевого интерфейса находится в `operations/systemd/` и
`infra/compose.local.yaml`. Удаление старого кода из ветки не меняет
запущенный production и не заменяет его сохранённый артефакт отката.

Публичный production-вход `m.funpin.org` использует конфигурацию сохранённого
production-релиза. Конфигурации запуска старого веб-интерфейса больше не входят
в alpha. Маршрутизация перехода на целевой стек описана в `operations/nginx/`.

### Резервное копирование SQLite

В сборку входит ежедневный online-backup живой SQLite-базы. Копия создаётся
штатным SQLite Backup API, проверяется через `PRAGMA quick_check`, атомарно
публикуется с правами `600`; timer хранит одну последнюю плановую копию и не
удаляет созданные вручную файлы.

```bash
cp operations/systemd/m-ranked-backup.service operations/systemd/m-ranked-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now m-ranked-backup.timer
systemctl list-timers m-ranked-backup.timer
```

Timer запускается ежедневно в 03:15 по Europe/Moscow с небольшим случайным
сдвигом. Проверить разовый запуск можно командой
`systemctl start m-ranked-backup.service`; результат хранится только в
`data/backups/scheduled/`. Профили Telegram Web, MAX-сессия и `.env` этим
заданием не копируются.

## Конфигурация

Настройки API, интерфейса и сервисов нового стека находятся в
[`operations/env/`](operations/env/) и [`operations/systemd/`](operations/systemd/).
Роли БД и разделение доступа описаны в [operations/README.md](operations/README.md).

Общие настройки интеграций и SQLite-сборщиков перечислены в `.env.example`:

- `TRACK_POST_FOR_HOURS=960` — опрос до 40 суток;
- `RETENTION_DAYS=70` — хранение истории и очистка; глубина опроса остаётся
  отдельной и ограничена `TRACK_POST_FOR_HOURS`;
- `DELETION_CONFIRMATION_CHECKS=2` — подтверждения удаления;
- `SUBSCRIBER_REFRESH_HOURS=24` — обновление подписчиков;
- `TELEGRAM_CONCURRENCY=6` — одновременно опрашиваемые TG-каналы в WEB- и
  MTProto-режимах;
- `TELEGRAM_WEB_CONCURRENCY=3` — число параллельных пакетных запросов точных
  комментариев через авторизованный официальный Telegram Web;
- `VK_CONCURRENCY=3` и `VK_REQUESTS_PER_SECOND=3` — параллелизм и общий
  rate limit VK API;
- `RUTUBE_ACCOUNT_CONCURRENCY=4` и `RUTUBE_REQUEST_CONCURRENCY=8` — лимиты
  параллельного опроса каналов и метрик RUTUBE;
- `VK_ACCESS_TOKEN` — включает сбор настроенных VK-сообществ;
- `MAX_USER_PHONE` — включает сбор публичных MAX-каналов через отдельную
  пользовательскую сессию; `MAX_SESSION_PATH` задаёт путь к её файлу;
- `RUTUBE_PUBLIC_API_ENABLED=true` — включает официальные публичные API
  видео, просмотров, лайков и комментариев; токен для этого режима не требуется;
- `DISPLAY_TIMEZONE=Europe/Moscow` — часовой пояс интерфейса.

Сохранённые файлы legacy-релиза на сервере в период переноса:

- база: `/opt/telegram-reaction-monitor/data/reactions.db`;
- пользовательская MAX-сессия: `/opt/telegram-reaction-monitor/data/max.session.db`;
- профиль Telegram Web: `/opt/telegram-reaction-monitor/data/telegram-web-profile/`;
- архивы: `/opt/telegram-reaction-monitor/data/archives/`;
- проверенные копии SQLite: `/opt/telegram-reaction-monitor/data/backups/scheduled/`;
- логи: `/opt/telegram-reaction-monitor/logs/collector.log` и `web.log`;
- collectors: `journalctl -u m-ranked-collector`;
- веб: `journalctl -u m-ranked-web`.

## Частота сбора

| Возраст публикации | TG / VK / MAX | Rutube |
|---|---:|---:|
| первые 24 часа | 5 минут | 1 час |
| 2–3-и сутки | 15 минут | 1 час |
| 4–6-е сутки | 30 минут | 3 часа |
| 7–13-е сутки | 1 час | 6 часов |
| с 14-х суток | 1 час | 12 часов |

Метаданные канала и подписчики обновляются не чаще раза в сутки.

Интервал выбирается по возрасту каждой публикации, поэтому один цикл может
опрашивать разные посты с разной частотой. Для Rutube оставлен отдельный
щадящий график. Планировщик отсчитывает следующий запуск от начала прошлого
цикла и не накапливает задержку из-за времени выполнения опроса.
Готовность публикаций привязана к единому временному слоту начала цикла, а не
к плавающему времени обработки отдельного канала. Поэтому переход канала на
несколько секунд раньше внутри следующего прохода не откладывает замер ещё на
один полный цикл; фактическое время получения метрик при этом сохраняется.
