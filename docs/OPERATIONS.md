# Эксплуатация

M-Ranked работает как единый Python/PostgreSQL/Next.js release. Переходного
SQLite-контура, Spring и reverse-sync в текущем релизе нет. Профиль B использует Redis как ограниченный непостоянный cache.

## Процессы

- `m-ranked-target-api.service` — FastAPI и встроенный outbox marker;
- `m-ranked-target-web.service` — Next.js;
- `m-ranked-target-collector@{telegram,vk,max,rutube}.service` — независимые сборщики;
- `m-ranked-target-anomaly-analysis.service` — анализ аномалий;
- maintenance, backup и restore timers из `operations/systemd/`.
- `m-ranked-target-rating-forecast.timer` — ночной снимок прогноза М-Рейтинга по соцсетям (см. ниже).

API использует отдельные роли `api_read`, `api_write_admin` и
`outbox_worker`. Сборщики используют только `collector_ingest`.
Пароли передаются через systemd credentials или libpq passfile, не через
аргументы процессов.

## Сборщики

```bash
.venv/bin/python -m collector_target --platform telegram
.venv/bin/python -m collector_target --platform vk
.venv/bin/python -m collector_target --platform max
.venv/bin/python -m collector_target --platform rutube
```

Каждый процесс имеет отдельный lease, лимит памяти и platform-scoped credential.
Telegram поддерживает public web, Web K и MTProto; MAX и Telegram сохраняют
свои session-файлы как отдельные зашифрованные runtime-секреты.

В `phased` mode поверх platform lease действует один общий PostgreSQL advisory
lease полного цикла. Durable request checkpoints задают fairness, а пропущенные
UTC-слоты схлопываются в один запуск. `legacy` сохраняет прежние offsets как
оперативный rollback, `shadow` проверяет решения scheduler без provider calls.
Архитектура, capacity gate и rollout описаны в
[ADR-009](architecture/adr/ADR-009-collector-phase-arbiter.md).

## База и кэш

Схема создаётся из `db/migrations/*.sql`; текущий contract id —
`live-read-2026-09-13`. Public reads выполняются непосредственно по bounded
SQL. FastAPI держит небольшой LRU-кэш в памяти и сбрасывает его по PostgreSQL
`LISTEN/NOTIFY`. Потеря уведомления не влияет на корректность: ключ включает
ревизию набора, TTL ограничен.

## CSV-экспорт

CSV-экспорт удалён из рабочего контура. FastAPI не публикует public, legacy или
admin export endpoints, Next.js не содержит совместимых `/export/*.csv`
маршрутов, а collectors не создают `analytics.legacy_native_export_lexeme`.
Миграция `0033_remove_csv_exports.sql` удаляет оставшуюся таблицу с production.
Служебный cold archive Parquet относится к retention/DR; наличие кода не означает включённую архивацию. На проверке 24.09.2026 архивы и работающая archive job отсутствовали.

Подробные процедуры: [deploy](../operations/runbooks/DEPLOY.md),
[backup/restore](../operations/runbooks/BACKUP_RESTORE.md),
[аварийный откат приложения](../operations/runbooks/ROLLBACK.md).

## Прогноз М-Рейтинга

Вкладка `/rating` читает готовые снимки из `rating.rating_run` и
`rating.rating_result`; считает их `m-ranked-target-rating-forecast.service`
(`python -m api.tools.rating_forecast`) раз в сутки в 01:47 по Москве — после
проверки официального рейтинга и до ночного дампа. Задание берёт текущий месяц
(бегущая оценка) и прошлый, пока за него нет официального списка (итоговый
прогноз); когда официальный месяц появился, последний снимок до публикации
помечается итоговым, промежуточные снимки этого месяца удаляются. На копии прода
прогон занимает меньше секунды и около 50 МБ памяти. До первого снимка
вкладка показывает «Снимков прогноза ещё нет».

Ретроспектива (август–сентябрь 2026, пометка «ретроспективный расчёт»)
запускается разово после миграции 0084 тем же юнитом с аргументом, с низким
приоритетом:

```bash
systemd-run --wait --pipe --unit=m-ranked-rating-retro --property=Nice=10 \
  --property=CPUQuota=50% --property=User=m-ranked-api --property=Group=m-ranked-api \
  --property=WorkingDirectory=/opt/m-ranked/current \
  --property=EnvironmentFile=/etc/m-ranked/api.env \
  --property=LoadCredential=api-read-db-password:/etc/m-ranked/credentials/api-read-db-password \
  --property=LoadCredential=api-write-admin-db-password:/etc/m-ranked/credentials/api-write-admin-db-password \
  /bin/sh -c 'API_READ_DB_PASSWORD_FILE=$CREDENTIALS_DIRECTORY/api-read-db-password \
    API_WRITE_ADMIN_DB_PASSWORD_FILE=$CREDENTIALS_DIRECTORY/api-write-admin-db-password \
    exec /opt/m-ranked/current/.venv/bin/python -m api.tools.rating_forecast --retrospective 2026-08..2026-09'
```

Запись снимков — только функциями `ops_and_admin.record_rating_forecast` и
`ops_and_admin.finalize_rating_forecast` (`SECURITY DEFINER`, владелец
`migration_owner`, `EXECUTE` у `api_write_admin`). Откат — раздел «Откат» в
`db/migrations/0084_rating_forecast.sql`; формулу v1 как опубликованную удаляет
только владелец. Точность прогноза проверяет
`research/m-rating-forecast/backtest.py`.
