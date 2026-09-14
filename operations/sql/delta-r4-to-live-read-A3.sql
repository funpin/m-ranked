-- Фаза A3: досев витрины публикациями, которых в ней нет.
--
-- Массовый пересчёт всей витрины на живом проде упирается во взаимную
-- блокировку: триггер из фазы A обновляет отдельные строки прямо во время
-- прогона, и по горячему месяцу столкновение почти неизбежно.
--
-- Обновлять существующие строки и не требуется. Витрина хранит последнее
-- известное значение метрики; у публикации, которую перестали наблюдать, оно
-- и должно оставаться прежним. Чинить надо только отсутствующие строки —
-- иначе новый код показал бы по ним пустые метрики.
--
-- Порции по 200 публикаций, упорядоченные по идентификатору, с повтором.
-- ON CONFLICT DO NOTHING: если триггер успел завести строку сам, порция её
-- не трогает.
\set ON_ERROR_STOP on

DO $seed$
DECLARE
    batch uuid[];
    touched bigint;
    total bigint := 0;
    attempt integer;
BEGIN
    LOOP
        SELECT array_agg(p.id) INTO batch FROM (
            SELECT p.id FROM ingest.visible_publication p
             WHERE NOT EXISTS (SELECT 1 FROM analytics.publication_latest l WHERE l.publication_id = p.id)
               AND EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot s
                            WHERE s.publication_id = p.id AND NOT s.synthetic AND s.quality <> 'invalid')
             ORDER BY p.id LIMIT 200) p;
        EXIT WHEN batch IS NULL;

        attempt := 0;
        LOOP
            BEGIN
            INSERT INTO analytics.publication_latest AS current (
                publication_id, institution_id, platform_account_id, platform, observed_at,
                views_count, views_observed_at, views_quality,
                reactions_count, reactions_observed_at, reactions_quality,
                comments_count, comments_observed_at, comments_quality,
                shares_count, shares_observed_at, shares_quality,
                quality, interval_uncertain, synthetic, history_completeness,
                source_snapshot_refs, dataset_revision_id, refreshed_at
            )
            WITH active AS (
                SELECT ranked.*
                  FROM (
                    SELECT s.publication_id, s.id, s.observed_at, s.quality, s.interval_uncertain, s.synthetic,
                           s.views_count, s.views_quality, s.reactions_count, s.reactions_quality,
                           s.comments_count, s.comments_quality, s.shares_count, s.shares_quality,
                           row_number() OVER (PARTITION BY s.publication_id, s.published_month, s.sampling_bucket
                                              ORDER BY s.correction_sequence DESC) AS correction_rank
                      FROM ingest.publication_metric_snapshot s
                             WHERE s.publication_id = ANY(batch)
                               AND NOT s.synthetic AND s.quality <> 'invalid'
                  ) ranked
                 WHERE ranked.correction_rank = 1
            ), folded AS (
                SELECT publication_id,
                       max(observed_at) AS observed_at,
                       (array_agg(id                 ORDER BY observed_at DESC, id DESC))[1] AS latest_id,
                       (array_agg(quality            ORDER BY observed_at DESC, id DESC))[1] AS quality,
                       (array_agg(interval_uncertain ORDER BY observed_at DESC, id DESC))[1] AS interval_uncertain,
                       (array_agg(synthetic          ORDER BY observed_at DESC, id DESC))[1] AS synthetic,
                       (array_agg(views_count    ORDER BY (views_count    IS NULL), observed_at DESC, id DESC))[1] AS views_count,
                       (array_agg(CASE WHEN views_count    IS NOT NULL THEN observed_at END ORDER BY (views_count    IS NULL), observed_at DESC, id DESC))[1] AS views_observed_at,
                       (array_agg(CASE WHEN views_count    IS NOT NULL THEN views_quality    END ORDER BY (views_count    IS NULL), observed_at DESC, id DESC))[1] AS views_quality,
                       (array_agg(CASE WHEN views_count    IS NOT NULL THEN id END ORDER BY (views_count    IS NULL), observed_at DESC, id DESC))[1] AS views_id,
                       (array_agg(reactions_count ORDER BY (reactions_count IS NULL), observed_at DESC, id DESC))[1] AS reactions_count,
                       (array_agg(CASE WHEN reactions_count IS NOT NULL THEN observed_at END ORDER BY (reactions_count IS NULL), observed_at DESC, id DESC))[1] AS reactions_observed_at,
                       (array_agg(CASE WHEN reactions_count IS NOT NULL THEN reactions_quality END ORDER BY (reactions_count IS NULL), observed_at DESC, id DESC))[1] AS reactions_quality,
                       (array_agg(CASE WHEN reactions_count IS NOT NULL THEN id END ORDER BY (reactions_count IS NULL), observed_at DESC, id DESC))[1] AS reactions_id,
                       (array_agg(comments_count  ORDER BY (comments_count  IS NULL), observed_at DESC, id DESC))[1] AS comments_count,
                       (array_agg(CASE WHEN comments_count  IS NOT NULL THEN observed_at END ORDER BY (comments_count  IS NULL), observed_at DESC, id DESC))[1] AS comments_observed_at,
                       (array_agg(CASE WHEN comments_count  IS NOT NULL THEN comments_quality  END ORDER BY (comments_count  IS NULL), observed_at DESC, id DESC))[1] AS comments_quality,
                       (array_agg(CASE WHEN comments_count  IS NOT NULL THEN id END ORDER BY (comments_count  IS NULL), observed_at DESC, id DESC))[1] AS comments_id,
                       (array_agg(shares_count    ORDER BY (shares_count    IS NULL), observed_at DESC, id DESC))[1] AS shares_count,
                       (array_agg(CASE WHEN shares_count    IS NOT NULL THEN observed_at END ORDER BY (shares_count    IS NULL), observed_at DESC, id DESC))[1] AS shares_observed_at,
                       (array_agg(CASE WHEN shares_count    IS NOT NULL THEN shares_quality    END ORDER BY (shares_count    IS NULL), observed_at DESC, id DESC))[1] AS shares_quality,
                       (array_agg(CASE WHEN shares_count    IS NOT NULL THEN id END ORDER BY (shares_count    IS NULL), observed_at DESC, id DESC))[1] AS shares_id
                  FROM active GROUP BY publication_id
            )
            SELECT folded.publication_id, account.institution_id, publication.primary_account_id, account.platform,
                   folded.observed_at,
                   folded.views_count, folded.views_observed_at, folded.views_quality,
                   folded.reactions_count, folded.reactions_observed_at, folded.reactions_quality,
                   folded.comments_count, folded.comments_observed_at, folded.comments_quality,
                   folded.shares_count, folded.shares_observed_at, folded.shares_quality,
                   folded.quality, folded.interval_uncertain, folded.synthetic, publication.history_completeness,
                   jsonb_strip_nulls(jsonb_build_object('latest', folded.latest_id, 'views', folded.views_id,
                       'reactions', folded.reactions_id, 'comments', folded.comments_id, 'shares', folded.shares_id)),
                   (SELECT max(id) FROM analytics.dataset_revision), transaction_timestamp()
              FROM folded
              JOIN ingest.visible_publication publication ON publication.id = folded.publication_id
              JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
            ON CONFLICT (publication_id) DO NOTHING;
                GET DIAGNOSTICS touched = ROW_COUNT;
                total := total + touched;
                EXIT;
            EXCEPTION WHEN deadlock_detected THEN
                attempt := attempt + 1;
                IF attempt > 10 THEN RAISE; END IF;
                PERFORM pg_sleep(attempt);
            END;
        END LOOP;
        RAISE NOTICE 'порция: добавлено %, всего %', touched, total;
        EXIT WHEN touched = 0;
    END LOOP;
    RAISE NOTICE 'досеяно строк витрины: %', total;
END
$seed$;
