-- 0092 — просмотры поста, не входящие в сумму «без волн и всплесков» на /compare
--
-- Ночное задание anomaly_analysis.account_tail_job записывает сюда просмотры
-- часов волн по стене и расцепленного всплеска. У остальных постов значение
-- NULL и места в строке не занимает, поэтому отдельной таблицы нет. Индекс
-- частичный: в нём только посты с такими просмотрами (на копии 07.11 — 359 из
-- 43 тыс. за 30 дней), панель читает значение из него, не заходя в строки.
--
-- Откат: DROP INDEX analytics.post_anomaly_state_discounted_views_idx;
--        ALTER TABLE analytics.post_anomaly_state DROP COLUMN discounted_views;
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.post_anomaly_state ADD COLUMN IF NOT EXISTS discounted_views integer;

CREATE INDEX IF NOT EXISTS post_anomaly_state_discounted_views_idx
    ON analytics.post_anomaly_state (publication_id) INCLUDE (discounted_views)
    WHERE discounted_views IS NOT NULL;

COMMENT ON COLUMN analytics.post_anomaly_state.discounted_views IS
  'Просмотры в часах волн по стене и в всплеске без реакций; NULL — таких нет. Статистическая оценка, не доказательство искусственного происхождения (ADR-006).';

COMMIT;
