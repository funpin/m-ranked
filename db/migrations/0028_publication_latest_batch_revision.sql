-- 0028 — ревизия батча для инкрементальной витрины публикаций
-- Причина: прежний триггер брал max(dataset_revision.id), поэтому первый батч
-- на пустой базе падал, а последующие помечались предыдущей ревизией.
-- Откат: сначала вернуть код сборщика, затем повторно применить определение
-- track_publication_latest из 0020; helper финализации после отката не вызывается
-- и может быть удалён отдельно. Таблицы и данные эта миграция не меняет.
-- Fallback на max(id) сохраняет совместимость со старым сборщиком, который не
-- устанавливает transaction-local GUC.

CREATE OR REPLACE FUNCTION analytics.finalize_ingestion_dataset_revision(
    p_revision_id bigint,
    p_source_run_id uuid,
    p_metadata jsonb,
    p_changed boolean
) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics'
    AS $$
BEGIN
    -- Production uses per-platform login roles that are members of the
    -- non-login collector_ingest capability role. Checking membership keeps
    -- the function collector-only without rejecting those least-privilege
    -- logins.
    IF NOT pg_has_role(session_user, 'collector_ingest', 'member') THEN
        RAISE EXCEPTION 'finalize_ingestion_dataset_revision is collector-only';
    END IF;
    IF jsonb_typeof(p_metadata) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'dataset revision metadata must be an object';
    END IF;

    IF p_changed THEN
        UPDATE analytics.dataset_revision
           SET metadata=p_metadata
         WHERE id=p_revision_id
           AND source_run_id=p_source_run_id
           AND cause='ingestion';
    ELSE
        DELETE FROM analytics.dataset_revision
         WHERE id=p_revision_id
           AND source_run_id=p_source_run_id
           AND cause='ingestion';
    END IF;
    RETURN FOUND;
END
$$;

REVOKE ALL ON FUNCTION analytics.finalize_ingestion_dataset_revision(
    bigint, uuid, jsonb, boolean
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION analytics.finalize_ingestion_dataset_revision(
    bigint, uuid, jsonb, boolean
) TO collector_ingest;

CREATE OR REPLACE FUNCTION analytics.track_publication_latest() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'analytics', 'ingest', 'catalog'
    AS $$
DECLARE
    account catalog.platform_account%ROWTYPE;
    owner_id uuid;
    completeness ingest.history_completeness;
    revision_id bigint;
BEGIN
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

    revision_id := coalesce(
        nullif(current_setting('mranked.dataset_revision_id', true), '')::bigint,
        (SELECT max(id) FROM analytics.dataset_revision)
    );

    INSERT INTO analytics.publication_latest AS current (
        publication_id, institution_id, platform_account_id, platform, observed_at,
        views_count, views_observed_at, views_quality,
        reactions_count, reactions_observed_at, reactions_quality,
        comments_count, comments_observed_at, comments_quality,
        shares_count, shares_observed_at, shares_quality,
        quality, interval_uncertain, synthetic, history_completeness,
        source_snapshot_refs, dataset_revision_id, refreshed_at
    ) VALUES (
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
        revision_id, transaction_timestamp()
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
