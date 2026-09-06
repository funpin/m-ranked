SET ROLE migration_owner;
SET lock_timeout='10s';
SET statement_timeout='15min';

-- Disabling a generic platform account stops polling; the original Python
-- period formulas continue to read its retained publication observations.
-- Telegram's dedicated enabled-channel policy and catalog visibility stay as-is.
DO $migration$
DECLARE definition text;old text;replacement text;
BEGIN
    definition:=pg_get_functiondef('analytics.rebuild_core_projections_v5(bigint)'::regprocedure);
    old:='         WHERE account.enabled
    ), all_dimensions AS (';
    replacement:='         WHERE (account.enabled OR account.platform IN (''vk'',''max'',''rutube''))
    ), all_dimensions AS (';
    IF (length(definition)-length(replace(definition,old,'')))/length(old)<>1 THEN
        RAISE EXCEPTION 'V27 platform dimensions anchor changed';
    END IF;
    definition:=replace(definition,old,replacement);
    old:='            ON account.id = publication.primary_account_id
           AND account.enabled';
    replacement:='            ON account.id = publication.primary_account_id
           AND (account.enabled OR account.platform IN (''vk'',''max'',''rutube''))';
    IF (length(definition)-length(replace(definition,old,'')))/length(old)<>1 THEN
        RAISE EXCEPTION 'V27 retained publication observations anchor changed';
    END IF;
    definition:=replace(definition,old,replacement);
    EXECUTE definition;
END $migration$;

-- A published formula correction changes the revision/ETag, while preserving
-- the accepted source clock. Empty installations rebuild on their first import.
DO $backfill$
DECLARE anchor timestamptz;revision bigint;
BEGIN
    SELECT source.committed_at INTO anchor FROM analytics.dataset_revision source
    WHERE source.id=(SELECT max(dataset_revision_id) FROM analytics.projection_state WHERE status='ready');
    IF anchor IS NOT NULL THEN
        INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at,metadata)
            VALUES('configuration',gen_random_uuid(),anchor,
                '{"migration":"V27","formula":"retained-disabled-non-telegram-period-history"}')
            RETURNING id INTO revision;
        PERFORM analytics.rebuild_core_projections(revision);
    END IF;
END $backfill$;
RESET ROLE;
