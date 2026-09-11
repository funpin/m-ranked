-- 0020 — инкрементальное обслуживание analytics.publication_latest
-- Написана вручную; заменяет часть удалённой пересборки проекций.

-- publication_latest — единственная проекция, которую стоило сохранить: 28 782
-- строки и 32 МБ против 4.8 млн снапшотов, которые иначе пришлось бы читать
-- каждому списку и обзору. Раньше её строил publisher целиком раз в час, и
-- потому она отставала: на срезе прода её observed_at на девять часов старше
-- самих данных.
--
-- Семантика сохранена дословно от rebuild_core_projections_v2:
--   * observed_at, quality, interval_uncertain, synthetic берутся из последнего
--     несинтетического наблюдения приемлемого качества;
--   * каждая метрика берётся из последнего наблюдения, где она НЕ NULL, со
--     своим временем и качеством. Метрика, которую платформа не отдала в этот
--     раз, не пропадает с экрана.
-- Обновление монотонно по observed_at, поэтому пересборка не нужна: значение
-- обновляется тогда и только тогда, когда пришло более свежее.
CREATE FUNCTION analytics.track_publication_latest() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ingest', 'catalog'
    AS $$
DECLARE
    account catalog.platform_account%ROWTYPE;
    owner_id uuid;
    completeness ingest.history_completeness;
BEGIN
    -- Синтетические и негодные наблюдения в витрину не попадают — ровно как в
    -- прежней пересборке.
    IF NEW.synthetic OR NEW.quality = 'invalid' THEN
        RETURN NULL;
    END IF;

    SELECT publication.primary_account_id, publication.history_completeness
      INTO owner_id, completeness
      FROM ingest.publication publication
     WHERE publication.id = NEW.publication_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT * INTO account FROM catalog.platform_account WHERE id = owner_id;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    INSERT INTO analytics.publication_latest AS current (
        publication_id, institution_id, platform_account_id, platform, observed_at,
        views_count, views_observed_at, views_quality,
        reactions_count, reactions_observed_at, reactions_quality,
        comments_count, comments_observed_at, comments_quality,
        shares_count, shares_observed_at, shares_quality,
        quality, interval_uncertain, synthetic, history_completeness,
        source_snapshot_refs, dataset_revision_id, refreshed_at
    ) VALUES (
        -- Тройка (count, observed_at, quality) по ограничению таблицы либо
        -- заполнена целиком, либо NULL целиком.
        NEW.publication_id, account.institution_id, account.id, account.platform, NEW.observed_at,
        NEW.views_count, CASE WHEN NEW.views_count IS NOT NULL THEN NEW.observed_at END,
        CASE WHEN NEW.views_count IS NOT NULL THEN NEW.views_quality END,
        NEW.reactions_count, CASE WHEN NEW.reactions_count IS NOT NULL THEN NEW.observed_at END,
        CASE WHEN NEW.reactions_count IS NOT NULL THEN NEW.reactions_quality END,
        NEW.comments_count, CASE WHEN NEW.comments_count IS NOT NULL THEN NEW.observed_at END,
        CASE WHEN NEW.comments_count IS NOT NULL THEN NEW.comments_quality END,
        NEW.shares_count, CASE WHEN NEW.shares_count IS NOT NULL THEN NEW.observed_at END,
        CASE WHEN NEW.shares_count IS NOT NULL THEN NEW.shares_quality END,
        NEW.quality, NEW.interval_uncertain, NEW.synthetic, completeness,
        jsonb_strip_nulls(jsonb_build_object(
            'latest', NEW.id,
            'views', CASE WHEN NEW.views_count IS NOT NULL THEN NEW.id END,
            'reactions', CASE WHEN NEW.reactions_count IS NOT NULL THEN NEW.id END,
            'comments', CASE WHEN NEW.comments_count IS NOT NULL THEN NEW.id END,
            'shares', CASE WHEN NEW.shares_count IS NOT NULL THEN NEW.id END)),
        (SELECT max(id) FROM analytics.dataset_revision), transaction_timestamp()
    )
    ON CONFLICT (publication_id) DO UPDATE SET
        observed_at = greatest(current.observed_at, EXCLUDED.observed_at),
        quality = CASE WHEN EXCLUDED.observed_at >= current.observed_at THEN EXCLUDED.quality ELSE current.quality END,
        interval_uncertain = CASE WHEN EXCLUDED.observed_at >= current.observed_at THEN EXCLUDED.interval_uncertain ELSE current.interval_uncertain END,
        synthetic = CASE WHEN EXCLUDED.observed_at >= current.observed_at THEN EXCLUDED.synthetic ELSE current.synthetic END,
        history_completeness = EXCLUDED.history_completeness,

        views_count = CASE WHEN EXCLUDED.views_observed_at IS NOT NULL
                            AND EXCLUDED.views_observed_at >= coalesce(current.views_observed_at, '-infinity')
                           THEN EXCLUDED.views_count ELSE current.views_count END,
        views_observed_at = greatest(current.views_observed_at, EXCLUDED.views_observed_at),
        views_quality = CASE WHEN EXCLUDED.views_observed_at IS NOT NULL
                              AND EXCLUDED.views_observed_at >= coalesce(current.views_observed_at, '-infinity')
                             THEN EXCLUDED.views_quality ELSE current.views_quality END,

        reactions_count = CASE WHEN EXCLUDED.reactions_observed_at IS NOT NULL
                                AND EXCLUDED.reactions_observed_at >= coalesce(current.reactions_observed_at, '-infinity')
                               THEN EXCLUDED.reactions_count ELSE current.reactions_count END,
        reactions_observed_at = greatest(current.reactions_observed_at, EXCLUDED.reactions_observed_at),
        reactions_quality = CASE WHEN EXCLUDED.reactions_observed_at IS NOT NULL
                                  AND EXCLUDED.reactions_observed_at >= coalesce(current.reactions_observed_at, '-infinity')
                                 THEN EXCLUDED.reactions_quality ELSE current.reactions_quality END,

        comments_count = CASE WHEN EXCLUDED.comments_observed_at IS NOT NULL
                               AND EXCLUDED.comments_observed_at >= coalesce(current.comments_observed_at, '-infinity')
                              THEN EXCLUDED.comments_count ELSE current.comments_count END,
        comments_observed_at = greatest(current.comments_observed_at, EXCLUDED.comments_observed_at),
        comments_quality = CASE WHEN EXCLUDED.comments_observed_at IS NOT NULL
                                 AND EXCLUDED.comments_observed_at >= coalesce(current.comments_observed_at, '-infinity')
                                THEN EXCLUDED.comments_quality ELSE current.comments_quality END,

        shares_count = CASE WHEN EXCLUDED.shares_observed_at IS NOT NULL
                             AND EXCLUDED.shares_observed_at >= coalesce(current.shares_observed_at, '-infinity')
                            THEN EXCLUDED.shares_count ELSE current.shares_count END,
        shares_observed_at = greatest(current.shares_observed_at, EXCLUDED.shares_observed_at),
        shares_quality = CASE WHEN EXCLUDED.shares_observed_at IS NOT NULL
                               AND EXCLUDED.shares_observed_at >= coalesce(current.shares_observed_at, '-infinity')
                              THEN EXCLUDED.shares_quality ELSE current.shares_quality END,

        source_snapshot_refs = jsonb_strip_nulls(current.source_snapshot_refs || EXCLUDED.source_snapshot_refs),
        dataset_revision_id = EXCLUDED.dataset_revision_id,
        refreshed_at = EXCLUDED.refreshed_at;

    RETURN NULL;
END
$$;

COMMENT ON FUNCTION analytics.track_publication_latest() IS
  'Поддерживает analytics.publication_latest при вставке наблюдения: последний снапшот задаёт время и качество, каждая метрика обновляется только более свежим не-NULL значением.';

CREATE TRIGGER publication_latest_track
    AFTER INSERT ON ingest.publication_metric_snapshot
    FOR EACH ROW EXECUTE FUNCTION analytics.track_publication_latest();

REVOKE ALL ON FUNCTION analytics.track_publication_latest() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.track_publication_latest() TO collector_ingest, maintenance;
