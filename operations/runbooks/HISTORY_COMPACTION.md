# Упакованная история замеров

Миграция 0059. Замер публикации живёт строкой `ingest.publication_metric_snapshot`
только первые двое суток после наблюдения (горячий слой: приём, исправления,
отсев повторов). Потом упаковщик переносит его в строку поста
`ingest.publication_metric_history` — массивы со сжатием lz4, ~27–30 байт на
замер вместо ~770 байт строки и индексов.

## Что читает какие данные

- `ingest.publication_metric_point` — все точки обоих слоёв, колонки
  `publication_metric_snapshot_resolved` + `visible`, `packed`, `reaction_breakdown`.
- `_resolved` и `_active` построены поверх него — прежние запросы верны без
  правок, но окно по многим постам через представление разворачивает каждую
  историю целиком. Для окон — функции:
  - `publication_points_between(ids, from, to)` — точки в окне;
  - `publication_point_at(ids, at)` — последняя видимая не позже `at`;
  - `publication_last_valid_at(ids, at)` — последняя валидная несинтетическая, все версии;
  - `publication_latest_point(id, month, synthetic)` — последняя видимая (приём);
  - `publication_point_by_id(id, month, snapshot_id)` — одна точка.
- Только в горячем слое: `source_fingerprint` (в API у упакованных точек нет
  `rawEvidence.sourceFingerprint`), `semantic_fingerprint` (кроме последней
  точки — она хранится в упаковке для сборщика), `ingested_xid`.

## Служба

`m-ranked-target-history-compaction.timer` — раз в полчаса. Переменные
(`/etc/m-ranked/history-compaction.env`):

| переменная | по умолчанию | смысл |
|---|---|---|
| `HISTORY_HOT_HOURS` | 48 | граница горячего слоя; пост берётся, когда его старые строки накопились ещё за сутки (0071), — горячий слой держит 48–72 часа |
| `HISTORY_COMPACTION_BATCH` | 100 | постов на запрос списка |
| `HISTORY_COMPACTION_MINUTES` | 20 | бюджет прогона |
| `HISTORY_COMPACTION_PACE` | 0.5 | пауза = доля времени работы |

Метрики: `mranked_history_compaction_*` (`remaining=1` — бюджета не хватило,
следующий прогон продолжит).

После упаковки пустые партиции месяцев раньше прошлого пересоздаются
(`ingest.release_empty_metric_partition`): удалённые строки держат место до
этого. Текущий и прошлый месяц ещё принимают замеры — их место
переиспользуется вставками; разовое уплотнение — `VACUUM FULL` партиции ночью.

## Поздние строки

Повтор доставки старше суток сверяется с упакованным бакетом: точный повтор
отбрасывается, иное — исправление поверх всех версий (флаг `late_rows`,
видимость упакованных точек сверяется с горячими). Следующий проход упаковщика
сливает их.

## Проверка и откат

- Без потерь: `tests/test_packed_history_postgres.py`, читатели —
  `tests/test_packed_readers_postgres.py` (одноразовая база,
  `MRANKED_TEST_PACKED_ADMIN_DSN`).
- Остановить: `systemctl disable --now m-ranked-target-history-compaction.timer`;
  упакованное продолжает читаться.
- Распаковать обратно — вставить точки `publication_metric_point WHERE packed`
  в горячую таблицу (под ролью владельца, триггеры отключены) и удалить строку
  упаковки; инструмента пока нет, сделать при необходимости.
