-- 0089 — очередь анализа выбирает просроченные посты, не читая строк состояния.
--
-- claim_due берёт «просроченные незамороженные, свежие первыми»:
-- WHERE NOT frozen AND next_due_at <= $1 ORDER BY published_at DESC LIMIT $2.
-- Индекс приоритета 0036 держал только published_at, и next_due_at
-- проверялся по строке таблицы. Просроченных обычно десятки из ~42 тыс.
-- незамороженных, а строка весит ~2 КБ: на проде 31.10 выборка 50 постов
-- проходила 3143 строки, читала с диска 2684 страницы и шла 484 мс — раз в
-- три секунды, около 22 МБ/с чтения при 256 МБ shared_buffers.
--
-- С next_due_at вторым ключом условие проверяется в самом индексе, в кучу
-- идут только 50 нужных строк: та же выборка в откатанной транзакции на
-- проде — 26 мс и 337 страниц, и те — холодный только что построенный индекс.
-- Порядок тот же (published_at DESC), так что выдача очереди не меняется.
--
-- Старый индекс читал только claim_due (pg_stat_user_indexes на проде), его
-- заменяет новый: число индексов и цена записи остаются прежними. Индекс
-- просроченных (post_anomaly_state_due_idx) нужен счётчику очереди и остаётся.
--
-- CONCURRENTLY и без транзакции, как 0085: обычное построение держало бы
-- запись анализа на всё время построения. Сначала новый, потом удаление
-- старого — очередь ни минуты не остаётся без индекса.
--
-- Если построение прервалось, остаётся нерабочий индекс, и IF NOT EXISTS его
-- не заменит: DROP INDEX CONCURRENTLY и запустить миграцию снова.
-- Откат:
--   CREATE INDEX CONCURRENTLY IF NOT EXISTS post_anomaly_state_priority_idx
--       ON analytics.post_anomaly_state (published_at DESC) WHERE NOT frozen;
--   DROP INDEX CONCURRENTLY IF EXISTS analytics.post_anomaly_state_due_by_published_idx;
CREATE INDEX CONCURRENTLY IF NOT EXISTS post_anomaly_state_due_by_published_idx
    ON analytics.post_anomaly_state (published_at DESC, next_due_at) WHERE NOT frozen;

DROP INDEX CONCURRENTLY IF EXISTS analytics.post_anomaly_state_priority_idx;
