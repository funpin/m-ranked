-- H68: точки для реестра позднего отклика одного аккаунта. Только чтение.
-- Возраст 18–30 ч (ранняя точка) и 60 ч–15 сут (позднее окно и суточная
-- раскладка) для оригинальных постов, вышедших за 4–42 суток до :'window_end'.
-- Запускать по одному аккаунту, последовательно:
--   psql -X -q -v account=<uuid> -v platform=max -v "window_end=2026-09-28 00:00:00+03" -f tail_ratio_points.sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '60s';
SET LOCAL lock_timeout = '2s';
COPY (
 WITH p AS (SELECT id, published_at, date_trunc('month', published_at AT TIME ZONE 'UTC')::date AS m
              FROM ingest.visible_publication
             WHERE primary_account_id = :'account'::uuid AND NOT is_repost AND deleted_at IS NULL
               AND published_at > :'window_end'::timestamptz - interval '42 days'
               AND published_at <= :'window_end'::timestamptz - interval '4 days')
 SELECT DISTINCT ON (p.id, s.observed_at) :'account', :'platform', p.id, p.published_at, s.observed_at,
        s.views_count, s.reactions_count, s.views_quality, s.reactions_quality, s.interval_uncertain
   FROM p JOIN ingest.publication_metric_snapshot_active s
     ON s.publication_id = p.id AND s.published_month = p.m
  WHERE s.published_month >= date_trunc('month', :'window_end'::timestamptz - interval '42 days')::date
    AND NOT s.synthetic AND s.observed_at < :'window_end'::timestamptz
    AND ((s.observed_at - p.published_at) BETWEEN interval '18 hours' AND interval '30 hours'
      OR (s.observed_at - p.published_at) BETWEEN interval '60 hours' AND interval '15 days')
  ORDER BY p.id, s.observed_at, s.correction_sequence DESC
) TO STDOUT WITH (FORMAT csv);
COMMIT;
