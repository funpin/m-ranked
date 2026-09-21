-- 0031 — витрина публикаций обслуживается только там, где её читают
-- Причина: в профиле B Сервер 1 не отдаёт чтение, поэтому analytics.publication_latest
-- на нём мёртвый груз. Триггер срабатывает на каждой вставке снимка, и в профиле B
-- это чистые накладные расходы на хосте, у которого их и так нет.
-- Профиль передаётся transaction-local GUC, как и ревизия батча из 0028: одна цепочка
-- миграций обслуживает оба профиля, расходящихся схем не заводим.
-- Пустой или отсутствующий GUC означает профиль A, поэтому старый сборщик против новой
-- схемы продолжает наполнять витрину, а откат не требует отката DDL.
-- Откат: вернуть определение track_publication_latest из 0028.

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
    -- Профиль B не обслуживает чтение, поэтому витрина ему не нужна.
    IF coalesce(nullif(current_setting('mranked.deployment_profile', true), ''), 'a') = 'b' THEN
        RETURN NULL;
    END IF;

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
