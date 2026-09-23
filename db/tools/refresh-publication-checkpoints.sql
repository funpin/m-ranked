-- Дописывает значения публикаций на фиксированных часах после выхода.
--
-- Пишутся только часы, которые пост уже прошёл и которых ещё нет в таблице:
-- значение на прошедшем часе не меняется, поэтому обычный прогон считает
-- лишь посты, перешагнувшие очередной час с прошлого раза, — сотни поисков
-- вместо двухсот тысяч. Первый прогон заполняет окно целиком.
--
-- Значение часа — последний валидный снимок не позже него и не раньше, чем за
-- допуск до него: четверть часа отсчёта, но не меньше получаса. Снимки
-- реже допуска (пропуск сбора, пост найден поздно) дают строку без значений.
-- Двадцать минут после часа ждём перенос: снимок с Сервера 1 приходит пачкой.
BEGIN;

SET LOCAL statement_timeout = '10min';
SET LOCAL synchronous_commit = off;

-- Окно отслеживания — тридцать суток; старше сорока строки не читает никто.
DELETE FROM analytics.publication_checkpoint checkpoint
 USING ingest.publication publication
 WHERE publication.id = checkpoint.publication_id
   AND publication.published_at < now() - interval '40 days';

-- Сначала список недостающих часов, и только по нему — поиск снимков:
-- иначе планировщик ищет снимок для всех пар и лишь потом отбрасывает уже
-- посчитанные, и обычный прогон стоил столько же, сколько первый.
WITH pending AS MATERIALIZED (
    SELECT publication.id, publication.published_at, hour.hour_offset,
           publication.published_at + hour.hour_offset * interval '1 hour' AS due_at,
           date_trunc('month', publication.published_at AT TIME ZONE 'UTC')::date AS published_month
      FROM ingest.visible_publication publication
     CROSS JOIN (VALUES (1), (3), (6), (12), (24), (48), (72), (168)) AS hour(hour_offset)
     WHERE publication.published_at >= now() - interval '35 days'
       AND publication.published_at + hour.hour_offset * interval '1 hour' + interval '20 minutes' <= now()
       AND NOT EXISTS (
           SELECT 1 FROM analytics.publication_checkpoint existing
            WHERE existing.publication_id = publication.id AND existing.hour_offset = hour.hour_offset)
)
INSERT INTO analytics.publication_checkpoint (
    publication_id, hour_offset, observed_at,
    views_count, reactions_count, comments_count, shares_count)
SELECT pending.id, pending.hour_offset, snapshot.observed_at,
       CASE WHEN snapshot.views_quality IN ('invalid', 'suspected_reset') THEN NULL ELSE snapshot.views_count END,
       CASE WHEN snapshot.reactions_quality IN ('invalid', 'suspected_reset') THEN NULL ELSE snapshot.reactions_count END,
       CASE WHEN snapshot.comments_quality IN ('invalid', 'suspected_reset') THEN NULL ELSE snapshot.comments_count END,
       CASE WHEN snapshot.shares_quality IN ('invalid', 'suspected_reset') THEN NULL ELSE snapshot.shares_count END
  FROM pending
  LEFT JOIN LATERAL (
      SELECT candidate.observed_at, candidate.views_count, candidate.views_quality,
             candidate.reactions_count, candidate.reactions_quality,
             candidate.comments_count, candidate.comments_quality,
             candidate.shares_count, candidate.shares_quality
        FROM ingest.publication_metric_snapshot candidate
       WHERE candidate.published_month = pending.published_month
         AND candidate.publication_id = pending.id
         AND candidate.observed_at <= pending.due_at
         AND candidate.observed_at >= pending.due_at
             - greatest(interval '30 minutes', pending.hour_offset * interval '15 minutes')
         AND candidate.quality <> 'invalid'
         AND NOT candidate.synthetic
       ORDER BY candidate.observed_at DESC, candidate.id DESC
       LIMIT 1
  ) snapshot ON true
ON CONFLICT (publication_id, hour_offset) DO NOTHING;

COMMIT;
