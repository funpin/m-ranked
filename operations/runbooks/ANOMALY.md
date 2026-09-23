# Выкатка анализа аномальной динамики v2

Порядок будущей выкатки, метрики, тревоги и откат. Адресов и доступов здесь
нет: они в локальных записях оператора (см. `AGENTS.md`). Анализ живёт там,
где база с полной историей: профиль A или Сервер 2 профиля B.

## Что меняется

- Миграция `0036` создаёт четыре таблицы в `analytics` и выдаёт
  `analytics_worker` чтение четырёх представлений `ingest`/`catalog`.
  Контракт схемы сборщиков не меняется, старые восемь таблиц анализа не
  трогаются.
- Юнит `m-ranked-target-anomaly-analysis.service` запускает работник v2
  (`CPUQuota=50%`, `MemoryMax=384M`, `Nice=10`); таймер
  `m-ranked-target-anomaly-norms.timer` — ночной пересчёт норм.
- `GET /api/v1/publications/{id}/anomaly-analysis` отдаёт новый ответ; старые
  админские команды пометок работают на старых таблицах как раньше.
- Страница поста показывает свёрнутую карточку анализа и отметки на
  графиках; флаг `ANOMALY_REPORT_VISIBLE` в `web.env` их скрывает.

## Порядок

1. **Резервная копия** — обычный дамп перед миграцией
   (`BACKUP_RESTORE.md`).
2. **Миграция 0036** от имени владельца миграций:
   ```bash
   psql -v ON_ERROR_STOP=1 -f db/migrations/0036_anomaly_analysis_v2.sql
   ```
   Миграция только создаёт объекты — ни блокировок горячих таблиц, ни
   перезаписи данных. Миграцию удаления старой модели (`0038`) **не
   применять**: она ждёт проверки v2 на реальных данных (шаг 8).
3. **Релиз с тихим режимом.** В `/etc/m-ranked/web.env`
   `ANOMALY_REPORT_VISIBLE=false`, в `/etc/m-ranked/anomaly-analysis.env` —
   новые переменные из `operations/env/anomaly-analysis.env.example`
   (`TRACK_POST_FOR_HOURS` — то же значение, что у сборщиков). Установщик
   ставит юниты и `anomaly-pgpass` роли `analytics_worker`.
4. **Работник и догонка.** `systemctl restart m-ranked-target-anomaly-analysis`.
   Работник сам ставит в очередь посты окна отслеживания и делает каждому
   один анализ «на сейчас» — пропущенные интервалы не проигрываются. Следите
   за `mranked_anomaly_due_backlog` и `mranked_anomaly_queue_lag_seconds`:
   очередь из ~29 000 постов при бюджете 0,5 ядра догоняется за минуты,
   отставание должно уйти ниже 15 минут. Пока его нет, интервалы 7–30 суток
   растянуты (`mranked_anomaly_interval_stretch`), свежие посты не страдают.
5. **Первая норма.** `systemctl start m-ranked-target-anomaly-norms.service`,
   затем `systemctl enable --now m-ranked-target-anomaly-norms.timer`. Первая
   версия строится только из постов, прошедших абсолютные детекторы, с низкой
   уверенностью: признаки 2, 4, 5 и 10 до роста уверенности не сильнее
   слабого сигнала. Статус версии — в `mranked_anomaly_norm_latest_status` и в
   `analytics.anomaly_norm_version`. Работник подхватывает принятую версию
   сам и растягивает перепроверку постов по шести часам.
6. **Эталон на реальных данных.** Выгрузить посты, которые владелец считает
   эталонными, скриптом только для чтения:
   ```bash
   ANOMALY_REFERENCE_DATABASE_URL=... .venv/bin/python -m anomaly_analysis.tools.export_reference \
     --out /var/lib/m-ranked/anomaly-reference <id> [<id> ...]
   ```
   Каталог вне репозитория: это данные вузов, а репозиторий публичный.
   Проставить в выгруженных файлах `expected_min_level`, `expected_max_level`
   и `expected_patterns`, прогнать
   `ANOMALY_REFERENCE_DIRS=<каталог> pytest tests/test_anomaly_reference.py`.
   Каталог указан в `ANOMALY_REFERENCE_DIRS`, так что размеченные файлы
   попадают в эталон ночной проверки норм вместе с синтетикой.
7. **Показ.** `ANOMALY_REPORT_VISIBLE=true` (или удалить строку) и
   `systemctl restart m-ranked-target-web`. Прогрев уже запрашивает анализ
   свежих постов тем же ключом кэша, что и страница.
8. **Удаление старой модели** — не раньше, чем v2 проработает на реальных
   данных и эталон из шага 6 будет зелёным: миграция
   `db/migrations/pending/0038_remove_anomaly_analysis_v1.sql` удаляет восемь
   таблиц, функции и триггер старой очереди. Она лежит в `pending/`, чтобы её
   не применил обычный прогон `db/migrations/*.sql`; тем же релизом, что
   переносит её в `db/migrations/`, убираются админские маршруты ручных
   пометок v1 — они вызывают удаляемые функции. Пока она не применена, триггер
   `anomaly_candidate_after_effective_snapshot` продолжает обновлять старую
   очередь кандидатов — она ограничена строкой на публикацию.

## Метрики и тревоги

| Метрика | Что значит | Тревога |
|---|---|---|
| `mranked_anomaly_due_backlog` | постов с наступившим сроком | `MRankedAnomalyWorkerMetricsStale`, если при непустой очереди файл не обновлялся 15 минут |
| `mranked_anomaly_queue_lag_seconds` | насколько просрочен самый старый срок | `MRankedAnomalyQueueLag` — больше часа 15 минут подряд |
| `mranked_anomaly_analyses_total{outcome}` | analyzed / postponed / failed / frozen | `MRankedAnomalyWorkerFailures` — больше 20 ошибок за час |
| `mranked_anomaly_interval_stretch` | во сколько раз растянуты интервалы 7–30 суток | — |
| `mranked_anomaly_norm_latest_status{status}` | статус последней версии нормы | `MRankedAnomalyNormNeedsReview` — версия на разборе дрейфа дольше часа |
| `mranked_anomaly_norm_last_run_unixtime` | последний пересчёт норм | `MRankedAnomalyNormJobStale` — пересчёта не было двое суток |

Версия на разборе дрейфа (`drift_review`) не применяется: анализ остаётся на
прежней принятой. Принять её после разбора — `UPDATE analytics.anomaly_norm_version
SET status='accepted', decided_at=now() WHERE id=…` от имени владельца миграций.

## Откат

- **Показ.** `ANOMALY_REPORT_VISIBLE=false` и перезапуск web — карточка и
  отметки исчезают, данные анализа не трогаются.
- **Работник и нормы.** `systemctl disable --now m-ranked-target-anomaly-norms.timer`
  и `systemctl stop m-ranked-target-anomaly-analysis`. API продолжит отдавать
  последний записанный вывод.
- **Релиз.** Откат на предыдущий релиз (`ROLLBACK.md`) возвращает старый
  работник; его таблицы не удалялись, он продолжит с того места, где встал.
- **Миграция 0036.** Нужна редко: `DROP TABLE` четырёх таблиц в обратном
  порядке создания и `REVOKE SELECT` на представления у `analytics_worker`.
  Выводы v2 пересчитываются заново за одну догонку.
