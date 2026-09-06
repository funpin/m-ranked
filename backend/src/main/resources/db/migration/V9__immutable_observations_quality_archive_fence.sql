-- Published V1--V8 remain unchanged. Corrections are immutable events, and
-- export fencing is enforced for every SQL writer, including direct backfill.
SET ROLE migration_owner;
SET lock_timeout = '10s';
SET statement_timeout = '15min';

ALTER TABLE ingest.publication_metric_snapshot
    DROP CONSTRAINT publication_metric_snapshot_published_month_publication_id__key;
ALTER TABLE ingest.publication_metric_snapshot
    ADD COLUMN ingested_xid xid8,
    ADD COLUMN correction_sequence bigint NOT NULL DEFAULT 0 CHECK (correction_sequence >= 0),
    ADD COLUMN supersedes_snapshot_id bigint,
    ADD COLUMN correction_reason text,
    ADD COLUMN views_quality ingest.observation_quality,
    ADD COLUMN reactions_quality ingest.observation_quality,
    ADD COLUMN comments_quality ingest.observation_quality,
    ADD COLUMN shares_quality ingest.observation_quality,
    ADD COLUMN metric_evidence jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metric_evidence) = 'object');
UPDATE ingest.publication_metric_snapshot SET
    views_quality=quality, reactions_quality=quality, comments_quality=quality, shares_quality=quality;
ALTER TABLE ingest.publication_metric_snapshot
    ALTER COLUMN views_quality SET NOT NULL,
    ALTER COLUMN reactions_quality SET NOT NULL,
    ALTER COLUMN comments_quality SET NOT NULL,
    ALTER COLUMN shares_quality SET NOT NULL,
    ADD CONSTRAINT publication_snapshot_exact_replay UNIQUE
        (published_month, publication_id, sampling_bucket, source_fingerprint),
    ADD CONSTRAINT publication_snapshot_correction_sequence UNIQUE
        (published_month, publication_id, sampling_bucket, correction_sequence),
    ADD CONSTRAINT publication_snapshot_correction_lineage CHECK
        ((correction_sequence=0 AND supersedes_snapshot_id IS NULL AND correction_reason IS NULL)
         OR (correction_sequence>0 AND supersedes_snapshot_id IS NOT NULL AND btrim(correction_reason) <> ''));
-- A trigger verifies predecessor ownership under the same bucket lock. A self
-- FK across the partitioned parent would prevent legitimate paired partition DROP.
ALTER TABLE ingest.account_metric_snapshot
    ADD COLUMN correction_sequence bigint NOT NULL DEFAULT 0 CHECK (correction_sequence >= 0),
    ADD COLUMN supersedes_snapshot_id bigint,
    ADD COLUMN correction_reason text,
    ADD COLUMN subscriber_quality ingest.observation_quality,
    ADD COLUMN subscriber_source_field text NOT NULL DEFAULT 'subscriber_count',
    ADD COLUMN subscriber_semantic_flags jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(subscriber_semantic_flags)='object');
UPDATE ingest.account_metric_snapshot SET subscriber_quality=quality;
-- V1 already allowed several account events at an instant. Preserve their
-- immutable values and backfill deterministic insertion-order lineage once.
WITH ranked AS (
 SELECT id, row_number() OVER w - 1 AS seq, lag(id) OVER w AS previous
 FROM ingest.account_metric_snapshot
 WINDOW w AS (PARTITION BY platform_account_id,observed_at ORDER BY id)
)
UPDATE ingest.account_metric_snapshot s SET correction_sequence=r.seq,
 supersedes_snapshot_id=r.previous,
 correction_reason=CASE WHEN r.seq>0 THEN 'v9_legacy_backfill' END
FROM ranked r WHERE r.id=s.id;
ALTER TABLE ingest.account_metric_snapshot
    ALTER COLUMN subscriber_quality SET NOT NULL,
    ADD CONSTRAINT account_snapshot_correction_sequence UNIQUE(platform_account_id,observed_at,correction_sequence),
    ADD CONSTRAINT account_snapshot_correction_lineage CHECK
        ((correction_sequence=0 AND supersedes_snapshot_id IS NULL AND correction_reason IS NULL)
         OR (correction_sequence>0 AND supersedes_snapshot_id IS NOT NULL AND btrim(correction_reason) <> ''));

CREATE TABLE ops_and_admin.publication_partition_fence (
 published_month date PRIMARY KEY CHECK(published_month=date_trunc('month',published_month)::date),
 state text NOT NULL DEFAULT 'active' CHECK(state IN ('active','archiving','archived')),
 changed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
 manifest_id uuid REFERENCES ops_and_admin.archive_manifest(id)
);
CREATE FUNCTION ops_and_admin.assert_publication_partition_writable(p_month date)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ops_and_admin AS $f$
DECLARE current_state text;
BEGIN
 -- Shared transaction lock drains *all* existing snapshot/reaction writers
 -- before an archiver obtains its exclusive lock and publishes the fence.
 PERFORM pg_advisory_xact_lock_shared(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT state INTO current_state FROM ops_and_admin.publication_partition_fence WHERE published_month=p_month;
 IF current_state IS NOT NULL AND current_state<>'active' THEN
   RAISE EXCEPTION 'publication partition % is fenced (%)',p_month,current_state USING ERRCODE='55000';
 END IF;
END $f$;
CREATE FUNCTION ingest.prepare_immutable_publication_snapshot()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ingest,ops_and_admin AS $f$
DECLARE previous ingest.publication_metric_snapshot%ROWTYPE;
BEGIN
 NEW.ingested_xid:=pg_current_xact_id();
 PERFORM ops_and_admin.assert_publication_partition_writable(NEW.published_month);
 PERFORM pg_advisory_xact_lock(hashtextextended('observation:'||NEW.published_month::text||':'||NEW.publication_id::text||':'||NEW.sampling_bucket::text,0));
 NEW.views_quality:=coalesce(NEW.views_quality,NEW.quality);
 NEW.reactions_quality:=coalesce(NEW.reactions_quality,NEW.quality);
 NEW.comments_quality:=coalesce(NEW.comments_quality,NEW.quality);
 NEW.shares_quality:=coalesce(NEW.shares_quality,NEW.quality);
 SELECT * INTO previous FROM ingest.publication_metric_snapshot
  WHERE published_month=NEW.published_month AND publication_id=NEW.publication_id
   AND sampling_bucket=NEW.sampling_bucket AND source_fingerprint=NEW.source_fingerprint;
 IF FOUND THEN
   IF (to_jsonb(previous)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid'])
    IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid']) THEN
     RAISE EXCEPTION 'fingerprint reused for different observation' USING ERRCODE='23505';
   END IF;
   RETURN NULL;
 END IF;
 SELECT * INTO previous FROM ingest.publication_metric_snapshot
  WHERE published_month=NEW.published_month AND publication_id=NEW.publication_id
   AND sampling_bucket=NEW.sampling_bucket ORDER BY correction_sequence DESC LIMIT 1;
 NEW.correction_sequence:=CASE WHEN FOUND THEN previous.correction_sequence+1 ELSE 0 END;
 NEW.supersedes_snapshot_id:=previous.id;
 NEW.correction_reason:=CASE WHEN previous.id IS NOT NULL THEN coalesce(nullif(btrim(NEW.correction_reason),''),'provider_payload_changed') END;
 RETURN NEW;
END $f$;
CREATE FUNCTION ingest.prepare_immutable_account_snapshot()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ingest AS $f$
DECLARE previous ingest.account_metric_snapshot%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('account-observation:'||NEW.platform_account_id::text||':'||NEW.observed_at::text,0));
 NEW.subscriber_quality:=coalesce(NEW.subscriber_quality,NEW.quality);
 SELECT * INTO previous FROM ingest.account_metric_snapshot
  WHERE platform_account_id=NEW.platform_account_id AND observed_at=NEW.observed_at AND source_fingerprint=NEW.source_fingerprint;
 IF FOUND THEN
   IF (to_jsonb(previous)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid'])
    IS DISTINCT FROM (to_jsonb(NEW)-ARRAY['id','created_at','collection_run_id','correction_sequence','supersedes_snapshot_id','correction_reason','ingested_xid']) THEN
     RAISE EXCEPTION 'fingerprint reused for different observation' USING ERRCODE='23505';
   END IF;
   RETURN NULL;
 END IF;
 SELECT * INTO previous FROM ingest.account_metric_snapshot
  WHERE platform_account_id=NEW.platform_account_id AND observed_at=NEW.observed_at ORDER BY correction_sequence DESC LIMIT 1;
 NEW.correction_sequence:=CASE WHEN FOUND THEN previous.correction_sequence+1 ELSE 0 END;
 NEW.supersedes_snapshot_id:=previous.id;
 NEW.correction_reason:=CASE WHEN previous.id IS NOT NULL THEN coalesce(nullif(btrim(NEW.correction_reason),''),'provider_payload_changed') END;
 RETURN NEW;
END $f$;
CREATE FUNCTION ingest.reject_observation_mutation() RETURNS trigger
LANGUAGE plpgsql AS $f$ BEGIN
 RAISE EXCEPTION 'observations are append-only; insert a correction' USING ERRCODE='55000';
END $f$;
CREATE FUNCTION ingest.fence_reaction_insert() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ingest,ops_and_admin AS $f$
DECLARE snapshot_xid xid8; previous_count bigint;
BEGIN
 PERFORM ops_and_admin.assert_publication_partition_writable(NEW.snapshot_published_month);
 SELECT reaction_count INTO previous_count FROM ingest.reaction_breakdown
 WHERE snapshot_published_month=NEW.snapshot_published_month AND snapshot_id=NEW.snapshot_id AND reaction_key=NEW.reaction_key;
 IF FOUND THEN
   IF previous_count=NEW.reaction_count THEN RETURN NULL; END IF;
   RAISE EXCEPTION 'reaction replay differs from immutable observation' USING ERRCODE='55000';
 END IF;
 SELECT ingested_xid INTO snapshot_xid FROM ingest.publication_metric_snapshot
 WHERE published_month=NEW.snapshot_published_month AND id=NEW.snapshot_id;
 -- Breakdown must be committed with its parent. Later additions change the
 -- event fingerprint and therefore must belong to a new correction snapshot.
 IF snapshot_xid IS DISTINCT FROM pg_current_xact_id() THEN
   RAISE EXCEPTION 'reaction breakdown must be inserted with its observation' USING ERRCODE='55000';
 END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER observation_prepare BEFORE INSERT ON ingest.publication_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.prepare_immutable_publication_snapshot();
CREATE TRIGGER observation_prepare BEFORE INSERT ON ingest.account_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.prepare_immutable_account_snapshot();
CREATE TRIGGER observation_immutable BEFORE UPDATE OR DELETE ON ingest.publication_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE TRIGGER observation_immutable BEFORE UPDATE OR DELETE ON ingest.account_metric_snapshot FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE TRIGGER observation_immutable BEFORE UPDATE OR DELETE ON ingest.reaction_breakdown FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE TRIGGER reaction_fence BEFORE INSERT ON ingest.reaction_breakdown FOR EACH ROW EXECUTE FUNCTION ingest.fence_reaction_insert();

CREATE VIEW ingest.publication_metric_snapshot_active AS
 SELECT s.* FROM ingest.publication_metric_snapshot s
 WHERE NOT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot successor
 WHERE successor.published_month=s.published_month AND successor.publication_id=s.publication_id
 AND successor.sampling_bucket=s.sampling_bucket AND successor.correction_sequence>s.correction_sequence);
CREATE VIEW ingest.account_metric_snapshot_active AS
 SELECT s.* FROM ingest.account_metric_snapshot s
 WHERE NOT EXISTS (SELECT 1 FROM ingest.account_metric_snapshot successor
 WHERE successor.platform_account_id=s.platform_account_id AND successor.observed_at=s.observed_at
 AND successor.correction_sequence>s.correction_sequence);

CREATE VIEW analytics.usable_publication_snapshot AS SELECT
 s.published_month,
 s.id,
 s.publication_id,
 s.collection_run_id,
 s.observed_at,
 s.age_seconds,
 s.sampling_bucket,
 CASE WHEN s.views_quality IN ('invalid','suspected_reset') THEN NULL ELSE s.views_count END AS views_count,
 CASE WHEN s.reactions_quality IN ('invalid','suspected_reset') THEN NULL ELSE s.reactions_count END AS reactions_count,
 CASE WHEN s.comments_quality IN ('invalid','suspected_reset') THEN NULL ELSE s.comments_count END AS comments_count,
 CASE WHEN s.shares_quality IN ('invalid','suspected_reset') THEN NULL ELSE s.shares_count END AS shares_count,
 analytics.observation_quality_from_rank(coalesce((SELECT max(analytics.observation_quality_rank(v.quality)) FROM (VALUES (s.views_count,s.views_quality),(s.reactions_count,s.reactions_quality),(s.comments_count,s.comments_quality),(s.shares_count,s.shares_quality)) v(value,quality) WHERE v.value IS NOT NULL AND v.quality NOT IN ('invalid','suspected_reset')),analytics.observation_quality_rank(s.quality))) AS quality,
 s.interval_uncertain,
 s.synthetic,
 s.metric_semantics_version,
 s.capability_version,
 s.source_fingerprint,
 s.created_at,
 s.collected_at,
 s.correction_sequence,
 s.supersedes_snapshot_id,
 s.correction_reason,
 s.views_quality,
 s.reactions_quality,
 s.comments_quality,
 s.shares_quality,
 s.metric_evidence
FROM ingest.publication_metric_snapshot_active s;

GRANT SELECT ON ingest.publication_metric_snapshot_active, ingest.account_metric_snapshot_active
 TO collector_ingest, migration_bridge, maintenance;
REVOKE UPDATE,DELETE ON ingest.publication_metric_snapshot,ingest.account_metric_snapshot,ingest.reaction_breakdown FROM collector_ingest,migration_bridge,maintenance;
REVOKE ALL ON FUNCTION ops_and_admin.assert_publication_partition_writable(date),
 ingest.prepare_immutable_publication_snapshot(),ingest.prepare_immutable_account_snapshot(),
 ingest.reject_observation_mutation(),ingest.fence_reaction_insert() FROM PUBLIC;

ALTER TABLE analytics.publication_hourly ADD COLUMN views_quality ingest.observation_quality, ADD COLUMN reactions_quality ingest.observation_quality, ADD COLUMN comments_quality ingest.observation_quality, ADD COLUMN shares_quality ingest.observation_quality;

CREATE OR REPLACE FUNCTION analytics.rebuild_core_projections_v2(p_dataset_revision_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest, analytics
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    revision_as_of timestamptz;
    newest_revision_id bigint;
    publication_latest_rows bigint;
    publication_hourly_rows bigint;
    institution_daily_rows bigint;
    institution_monthly_rows bigint;
    institution_period_rows bigint;
    comparison_rows bigint;
    publication_hot_days integer;
    publication_hot_hours integer;
BEGIN
    IF p_dataset_revision_id IS NULL THEN
        RAISE EXCEPTION 'dataset revision must not be NULL';
    END IF;

    -- One writer publishes these tables at a time.  The SHARE table lock also
    -- prevents a newer revision from being inserted between the max(id) check
    -- and the final ready-state publication.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('analytics.rebuild_core_projections', 0)
    );
    LOCK TABLE analytics.dataset_revision IN SHARE MODE;

    SELECT committed_at
      INTO revision_as_of
      FROM analytics.dataset_revision
     WHERE id = p_dataset_revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'dataset revision % does not exist', p_dataset_revision_id;
    END IF;

    SELECT max(id) INTO newest_revision_id FROM analytics.dataset_revision;
    IF newest_revision_id IS DISTINCT FROM p_dataset_revision_id THEN
        RAISE EXCEPTION 'refusing to publish stale revision %; newest revision is %',
            p_dataset_revision_id, newest_revision_id;
    END IF;

    SELECT hot_days
      INTO publication_hot_days
      FROM ops_and_admin.retention_policy
     WHERE data_class = 'publication_metric_snapshot';
    IF publication_hot_days IS NULL OR publication_hot_days < 70 THEN
        RAISE EXCEPTION 'publication hot retention must be at least 70 days during parity';
    END IF;
    publication_hot_hours := publication_hot_days * 24;

    -- Resolve immutable correction tips and independent metric eligibility
    -- once per rebuild transaction. Re-evaluating the partitioned anti-join
    -- inside five LATERAL probes per publication/hour is needlessly quadratic.
    -- The fixed private temp name is recreated by this definer and never read
    -- from a caller-supplied relation. It cannot outlive the transaction.
    DROP TABLE IF EXISTS pg_temp.mranked_projection_snapshot;
    CREATE TEMP TABLE pg_temp.mranked_projection_snapshot ON COMMIT DROP AS
        SELECT * FROM analytics.usable_publication_snapshot;
    CREATE INDEX mranked_projection_snapshot_age_idx
        ON pg_temp.mranked_projection_snapshot
        (publication_id,age_seconds DESC,observed_at DESC,published_month DESC,id DESC);
    CREATE INDEX mranked_projection_snapshot_observed_idx
        ON pg_temp.mranked_projection_snapshot
        (publication_id,observed_at DESC,published_month DESC,id DESC);
    ANALYZE pg_temp.mranked_projection_snapshot;


    INSERT INTO analytics.projection_state AS state (
        projection_name, dataset_revision_id, status, refreshed_at, row_count, error_code
    )
    SELECT projection_name, p_dataset_revision_id, 'rebuilding',
           transaction_timestamp(), 0, NULL
      FROM unnest(ARRAY[
          'publication_latest',
          'publication_hourly',
          'institution_daily_metrics',
          'institution_monthly_metrics',
          'institution_period_metrics',
          'comparison'
      ]::text[]) AS requested(projection_name)
    ON CONFLICT (projection_name) DO UPDATE SET
        dataset_revision_id = excluded.dataset_revision_id,
        status = excluded.status,
        refreshed_at = excluded.refreshed_at,
        row_count = excluded.row_count,
        error_code = NULL;

    -- publication_latest deliberately ignores synthetic and invalid rows.
    -- Each metric is selected independently, so a newer unsupported/NULL MAX
    -- comments observation cannot erase the last usable comments observation.
    DELETE FROM analytics.publication_latest;

    INSERT INTO analytics.publication_latest (
        publication_id, institution_id, platform_account_id, platform, observed_at,
        views_count, views_observed_at, views_quality,
        reactions_count, reactions_observed_at, reactions_quality,
        comments_count, comments_observed_at, comments_quality,
        shares_count, shares_observed_at, shares_quality,
        quality, interval_uncertain, synthetic, history_completeness,
        source_snapshot_refs, dataset_revision_id, refreshed_at
    )
    SELECT
        publication.id,
        account.institution_id,
        publication.primary_account_id,
        account.platform,
        latest_snapshot.observed_at,
        latest_views.metric_value,
        latest_views.observed_at,
        latest_views.quality,
        latest_reactions.metric_value,
        latest_reactions.observed_at,
        latest_reactions.quality,
        latest_comments.metric_value,
        latest_comments.observed_at,
        latest_comments.quality,
        latest_shares.metric_value,
        latest_shares.observed_at,
        latest_shares.quality,
        latest_snapshot.quality,
        latest_snapshot.interval_uncertain,
        latest_snapshot.synthetic,
        publication.history_completeness,
        jsonb_strip_nulls(jsonb_build_object(
            'latest', latest_snapshot.id,
            'views', latest_views.snapshot_id,
            'reactions', latest_reactions.snapshot_id,
            'comments', latest_comments.snapshot_id,
            'shares', latest_shares.snapshot_id
        )),
        p_dataset_revision_id,
        transaction_timestamp()
    FROM ingest.publication AS publication
    JOIN catalog.platform_account AS account
      ON account.id = publication.primary_account_id
    JOIN LATERAL (
        SELECT snapshot.id, snapshot.observed_at, snapshot.quality,
               snapshot.interval_uncertain, snapshot.synthetic
          FROM pg_temp.mranked_projection_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_snapshot ON true
    LEFT JOIN LATERAL (
        SELECT snapshot.id AS snapshot_id, snapshot.views_count AS metric_value,
               snapshot.observed_at, snapshot.views_quality AS quality
          FROM pg_temp.mranked_projection_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND snapshot.views_count IS NOT NULL
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_views ON true
    LEFT JOIN LATERAL (
        SELECT snapshot.id AS snapshot_id, snapshot.reactions_count AS metric_value,
               snapshot.observed_at, snapshot.reactions_quality AS quality
          FROM pg_temp.mranked_projection_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND snapshot.reactions_count IS NOT NULL
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_reactions ON true
    LEFT JOIN LATERAL (
        SELECT snapshot.id AS snapshot_id, snapshot.comments_count AS metric_value,
               snapshot.observed_at, snapshot.comments_quality AS quality
          FROM pg_temp.mranked_projection_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND snapshot.comments_count IS NOT NULL
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_comments ON true
    LEFT JOIN LATERAL (
        SELECT snapshot.id AS snapshot_id, snapshot.shares_count AS metric_value,
               snapshot.observed_at, snapshot.shares_quality AS quality
          FROM pg_temp.mranked_projection_snapshot AS snapshot
         WHERE snapshot.publication_id = publication.id
           AND snapshot.observed_at <= revision_as_of
           AND snapshot.shares_count IS NOT NULL
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.observed_at DESC, snapshot.published_month DESC, snapshot.id DESC
         LIMIT 1
    ) AS latest_shares ON true
    WHERE publication.published_at <= revision_as_of;

    GET DIAGNOSTICS publication_latest_rows = ROW_COUNT;

    DELETE FROM analytics.publication_hourly;

    -- Hour offsets are relative to the publication timestamp, matching the
    -- legacy calculation exactly.  A point only sees observations at or
    -- before that target hour. Complete histories may carry the latest known
    -- value forward only through the last real observation and within the
    -- 70-day hot window; no history is extrapolated past collected coverage.
    WITH publication_limits AS (
        SELECT publication.id AS publication_id,
               publication.primary_account_id AS platform_account_id,
               account.institution_id,
               account.platform,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed,
               least(
                   publication_hot_hours,
                   floor(extract(epoch FROM (revision_as_of - publication.published_at)) / 3600)::integer,
                   coalesce(
                       floor(last_real.max_age_seconds::numeric / 3600)::integer,
                       -1
                   )
               ) AS max_hour
          FROM ingest.publication AS publication
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
          LEFT JOIN LATERAL (
              SELECT max(snapshot.age_seconds) AS max_age_seconds
                FROM pg_temp.mranked_projection_snapshot AS snapshot
               WHERE snapshot.publication_id = publication.id
                 AND snapshot.observed_at <= revision_as_of
                 AND NOT snapshot.synthetic
                 AND snapshot.quality <> 'invalid'
          ) AS last_real ON true
         WHERE publication.published_at <= revision_as_of
           AND publication.published_at >
               revision_as_of - make_interval(days => publication_hot_days)
    )
    INSERT INTO analytics.publication_hourly (
        publication_id, hour_offset, hour, institution_id, platform_account_id,
        platform, observed_at, views_count, reactions_count, comments_count,
        shares_count, views_quality,reactions_quality,comments_quality,shares_quality, quality, synthetic, history_completeness,
        interval_uncertain, dataset_revision_id
    )
    SELECT limits.publication_id,
           series.hour_offset,
           limits.published_at + series.hour_offset * interval '1 hour',
           limits.institution_id,
           limits.platform_account_id,
           limits.platform,
           point.observed_at,
           point.views_count,
           point.reactions_count,
           point.comments_count,
           point.shares_count,
           point.views_quality,point.reactions_quality,point.comments_quality,point.shares_quality,
           point.quality,
           point.synthetic,
           limits.history_completeness,
           point.interval_uncertain,
           p_dataset_revision_id
      FROM publication_limits AS limits
     CROSS JOIN LATERAL generate_series(0, limits.max_hour) AS series(hour_offset)
      JOIN LATERAL (
          SELECT snapshot.observed_at,
                 snapshot.views_count,
                 snapshot.reactions_count,
                 snapshot.comments_count,
                 snapshot.shares_count,
                 snapshot.views_quality,snapshot.reactions_quality,snapshot.comments_quality,snapshot.shares_quality,
                 snapshot.quality,
                 snapshot.synthetic,
                 snapshot.interval_uncertain
            FROM pg_temp.mranked_projection_snapshot AS snapshot
           WHERE snapshot.publication_id = limits.publication_id
             AND snapshot.age_seconds <= series.hour_offset * 3600
             AND snapshot.observed_at <=
                 limits.published_at + series.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND (NOT snapshot.synthetic OR limits.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS point ON true;

    GET DIAGNOSTICS publication_hourly_rows = ROW_COUNT;

    DELETE FROM analytics.institution_daily_metrics;

    WITH metric_facts AS (
        SELECT latest.institution_id,
               latest.platform::text::analytics.platform_scope AS platform,
               (publication.published_at AT TIME ZONE 'UTC')::date AS metric_day,
               metric.metric_key,
               metric.metric_value,
               metric.metric_quality
          FROM analytics.publication_latest AS latest
          JOIN ingest.publication AS publication ON publication.id = latest.publication_id
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, latest.views_count, latest.views_quality),
             ('reactions'::analytics.metric_key, latest.reactions_count, latest.reactions_quality),
             ('comments'::analytics.metric_key, latest.comments_count, latest.comments_quality),
             ('shares'::analytics.metric_key, latest.shares_count, latest.shares_quality)
         ) AS metric(metric_key, metric_value, metric_quality)
         WHERE latest.dataset_revision_id = p_dataset_revision_id
           AND publication.published_at <= revision_as_of
    ), scoped_facts AS (
        SELECT institution_id, platform, metric_day, metric_key, metric_value, metric_quality
          FROM metric_facts
        UNION ALL
        SELECT institution_id, 'all'::analytics.platform_scope, metric_day,
               metric_key, metric_value, metric_quality
          FROM metric_facts
    ), grouped AS (
        SELECT institution_id, platform, metric_day, metric_key,
               count(*) AS publication_count,
               count(metric_value) AS sample_size,
               sum(metric_value) AS sum_value,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY metric_value)
                   FILTER (WHERE metric_value IS NOT NULL)::numeric AS median_value,
               max(analytics.observation_quality_rank(metric_quality))
                   FILTER (WHERE metric_value IS NOT NULL) AS worst_quality_rank
          FROM scoped_facts
         GROUP BY institution_id, platform, metric_day, metric_key
    )
    INSERT INTO analytics.institution_daily_metrics (
        institution_id, platform, metric_key, aggregation, metric_day,
        window_start, window_end, value, sample_size, coverage, quality,
        as_of, dataset_revision_id
    )
    SELECT grouped.institution_id,
           grouped.platform,
           grouped.metric_key,
           aggregate_value.aggregation,
           grouped.metric_day,
           grouped.metric_day::timestamp AT TIME ZONE 'UTC',
           least(
               (grouped.metric_day + 1)::timestamp AT TIME ZONE 'UTC',
               revision_as_of
           ),
           aggregate_value.value,
           grouped.sample_size::integer,
           round(grouped.sample_size::numeric / grouped.publication_count, 6),
           analytics.observation_quality_from_rank(grouped.worst_quality_rank),
           revision_as_of,
           p_dataset_revision_id
      FROM grouped
     CROSS JOIN LATERAL (VALUES
         ('sum'::analytics.aggregation_code, grouped.sum_value),
         ('median'::analytics.aggregation_code, round(grouped.median_value, 0))
     ) AS aggregate_value(aggregation, value);

    GET DIAGNOSTICS institution_daily_rows = ROW_COUNT;

    DELETE FROM analytics.institution_monthly_metrics;

    WITH metric_facts AS (
        SELECT latest.institution_id,
               latest.platform::text::analytics.platform_scope AS platform,
               date_trunc('month', publication.published_at AT TIME ZONE 'UTC')::date
                   AS metric_month,
               metric.metric_key,
               metric.metric_value,
               metric.metric_quality
          FROM analytics.publication_latest AS latest
          JOIN ingest.publication AS publication ON publication.id = latest.publication_id
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, latest.views_count, latest.views_quality),
             ('reactions'::analytics.metric_key, latest.reactions_count, latest.reactions_quality),
             ('comments'::analytics.metric_key, latest.comments_count, latest.comments_quality),
             ('shares'::analytics.metric_key, latest.shares_count, latest.shares_quality)
         ) AS metric(metric_key, metric_value, metric_quality)
         WHERE latest.dataset_revision_id = p_dataset_revision_id
           AND publication.published_at <= revision_as_of
    ), scoped_facts AS (
        SELECT institution_id, platform, metric_month, metric_key,
               metric_value, metric_quality
          FROM metric_facts
        UNION ALL
        SELECT institution_id, 'all'::analytics.platform_scope, metric_month,
               metric_key, metric_value, metric_quality
          FROM metric_facts
    ), grouped AS (
        SELECT institution_id, platform, metric_month, metric_key,
               count(*) AS publication_count,
               count(metric_value) AS sample_size,
               sum(metric_value) AS sum_value,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY metric_value)
                   FILTER (WHERE metric_value IS NOT NULL)::numeric AS median_value,
               max(analytics.observation_quality_rank(metric_quality))
                   FILTER (WHERE metric_value IS NOT NULL) AS worst_quality_rank
          FROM scoped_facts
         GROUP BY institution_id, platform, metric_month, metric_key
    )
    INSERT INTO analytics.institution_monthly_metrics (
        institution_id, platform, metric_key, aggregation, metric_month,
        window_start, window_end, value, sample_size, coverage, quality,
        as_of, dataset_revision_id
    )
    SELECT grouped.institution_id,
           grouped.platform,
           grouped.metric_key,
           aggregate_value.aggregation,
           grouped.metric_month,
           grouped.metric_month::timestamp AT TIME ZONE 'UTC',
           least(
               (grouped.metric_month + interval '1 month')::timestamp AT TIME ZONE 'UTC',
               revision_as_of
           ),
           aggregate_value.value,
           grouped.sample_size::integer,
           round(grouped.sample_size::numeric / grouped.publication_count, 6),
           analytics.observation_quality_from_rank(grouped.worst_quality_rank),
           revision_as_of,
           p_dataset_revision_id
      FROM grouped
     CROSS JOIN LATERAL (VALUES
         ('sum'::analytics.aggregation_code, grouped.sum_value),
         ('median'::analytics.aggregation_code, round(grouped.median_value, 0))
     ) AS aggregate_value(aggregation, value);

    GET DIAGNOSTICS institution_monthly_rows = ROW_COUNT;

    DELETE FROM analytics.institution_period_metrics;

    WITH periods(period_key, duration) AS (VALUES
        ('3h'::text, interval '3 hours'),
        ('1d'::text, interval '1 day'),
        ('7d'::text, interval '7 days'),
        ('30d'::text, interval '30 days')
    ), dimensions AS (
        SELECT DISTINCT account.institution_id, account.platform
          FROM catalog.platform_account AS account
         WHERE account.enabled
        UNION
        SELECT DISTINCT account.institution_id, NULL::catalog.platform_code
          FROM catalog.platform_account AS account
         WHERE account.enabled
    ), metric_keys(metric_key) AS (VALUES
        ('views'::analytics.metric_key),
        ('reactions'::analytics.metric_key),
        ('comments'::analytics.metric_key),
        ('shares'::analytics.metric_key)
    ), aggregations(aggregation) AS (VALUES
        ('sum'::analytics.aggregation_code),
        ('median'::analytics.aggregation_code)
    ), metric_facts AS (
        SELECT latest.institution_id,
               latest.platform,
               publication.published_at,
               metric.metric_key,
               metric.metric_value,
               metric.metric_quality
          FROM analytics.publication_latest AS latest
          JOIN ingest.publication AS publication ON publication.id = latest.publication_id
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, latest.views_count, latest.views_quality),
             ('reactions'::analytics.metric_key, latest.reactions_count, latest.reactions_quality),
             ('comments'::analytics.metric_key, latest.comments_count, latest.comments_quality),
             ('shares'::analytics.metric_key, latest.shares_count, latest.shares_quality)
         ) AS metric(metric_key, metric_value, metric_quality)
         WHERE latest.dataset_revision_id = p_dataset_revision_id
           AND publication.published_at <= revision_as_of
    ), scoped_facts AS (
        SELECT institution_id, platform, published_at,
               metric_key, metric_value, metric_quality
          FROM metric_facts
        UNION ALL
        SELECT institution_id, NULL::catalog.platform_code, published_at,
               metric_key, metric_value, metric_quality
          FROM metric_facts
    ), grouped AS (
        SELECT fact.institution_id,
               fact.platform,
               period.period_key,
               fact.metric_key,
               count(*) AS publication_count,
               count(fact.metric_value) AS sample_size,
               sum(fact.metric_value) AS sum_value,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY fact.metric_value)
                   FILTER (WHERE fact.metric_value IS NOT NULL)::numeric AS median_value,
               max(analytics.observation_quality_rank(fact.metric_quality))
                   FILTER (WHERE fact.metric_value IS NOT NULL) AS worst_quality_rank
          FROM periods AS period
          JOIN scoped_facts AS fact
            ON fact.published_at > revision_as_of - period.duration
           AND fact.published_at <= revision_as_of
         GROUP BY fact.institution_id, fact.platform, period.period_key, fact.metric_key
    )
    INSERT INTO analytics.institution_period_metrics (
        institution_id, platform, period_key, metric_key, aggregation,
        window_start, window_end, value, sample_size, coverage, quality,
        as_of, dataset_revision_id, refreshed_at
    )
    SELECT dimension.institution_id,
           dimension.platform,
           period.period_key,
           metric_key.metric_key,
           aggregation.aggregation,
           revision_as_of - period.duration,
           revision_as_of,
           CASE
               WHEN coalesce(grouped.publication_count, 0) = 0
                    AND aggregation.aggregation = 'sum' THEN 0::numeric
               WHEN coalesce(grouped.sample_size, 0) = 0 THEN NULL
               WHEN aggregation.aggregation = 'sum' THEN grouped.sum_value
               ELSE round(grouped.median_value, 0)
           END,
           coalesce(grouped.sample_size, 0)::integer,
           CASE
               WHEN coalesce(grouped.publication_count, 0) = 0 THEN 0::numeric
               ELSE round(grouped.sample_size::numeric / grouped.publication_count, 6)
           END,
           analytics.observation_quality_from_rank(grouped.worst_quality_rank),
           revision_as_of,
           p_dataset_revision_id,
           transaction_timestamp()
      FROM dimensions AS dimension
     CROSS JOIN periods AS period
     CROSS JOIN metric_keys AS metric_key
     CROSS JOIN aggregations AS aggregation
      LEFT JOIN grouped
        ON grouped.institution_id = dimension.institution_id
       AND grouped.platform IS NOT DISTINCT FROM dimension.platform
       AND grouped.period_key = period.period_key
       AND grouped.metric_key = metric_key.metric_key;

    GET DIAGNOSTICS institution_period_rows = ROW_COUNT;

    DELETE FROM analytics.comparison_cohort;

    -- The five legacy UI horizons get immutable fixed cohorts. Cohort UUIDs
    -- are stable for a revision/platform/horizon, which makes rebuild output
    -- deterministic and keeps retries free of duplicate logical cohorts.
    WITH horizons(horizon_hours) AS (VALUES (24), (48), (72), (168), (336)),
    variants(include_partial, required_start_hour) AS (
        VALUES (false, 0), (true, 1)
    ),
    platforms(platform) AS (
        SELECT DISTINCT account.platform
          FROM catalog.platform_account AS account
         WHERE account.enabled
    )
    INSERT INTO analytics.comparison_cohort (
        id, platform, horizon_seconds, as_of, filter_definition,
        sample_size, dataset_revision_id, created_at
    )
    SELECT md5(
               'comparison|' || p_dataset_revision_id::text || '|' ||
               platform.platform::text || '|' || horizon.horizon_hours::text || '|' ||
               variant.include_partial::text
           )::uuid,
           platform.platform,
           horizon.horizon_hours * 3600,
           revision_as_of,
           jsonb_build_object(
               'fixed_cohort', true,
               'include_partial', variant.include_partial,
               'required_start_hour', variant.required_start_hour,
               'required_end_hour', horizon.horizon_hours,
               'hourly_hot_days', publication_hot_days
           ),
           0,
           p_dataset_revision_id,
           transaction_timestamp()
      FROM platforms AS platform
     CROSS JOIN horizons AS horizon
     CROSS JOIN variants AS variant;

    INSERT INTO analytics.comparison_cohort_member (
        cohort_id, publication_id, institution_id
    )
    SELECT cohort.id,
           start_point.publication_id,
           start_point.institution_id
      FROM analytics.comparison_cohort AS cohort
      JOIN analytics.publication_hourly AS start_point
        ON start_point.platform = cohort.platform
       AND start_point.dataset_revision_id = cohort.dataset_revision_id
       AND start_point.hour_offset =
           (cohort.filter_definition->>'required_start_hour')::integer
       AND (
           (cohort.filter_definition->>'include_partial')::boolean
           OR start_point.history_completeness = 'complete'
       )
      JOIN analytics.publication_hourly AS end_point
        ON end_point.publication_id = start_point.publication_id
       AND end_point.dataset_revision_id = start_point.dataset_revision_id
       AND end_point.hour_offset = cohort.horizon_seconds / 3600
     WHERE cohort.dataset_revision_id = p_dataset_revision_id;

    UPDATE analytics.comparison_cohort AS cohort
       SET sample_size = member_count.sample_size
      FROM (
          SELECT member.cohort_id, count(*)::integer AS sample_size
            FROM analytics.comparison_cohort_member AS member
            JOIN analytics.comparison_cohort AS selected
              ON selected.id = member.cohort_id
             AND selected.dataset_revision_id = p_dataset_revision_id
           GROUP BY member.cohort_id
      ) AS member_count
     WHERE cohort.id = member_count.cohort_id;

    WITH metric_facts AS (
        SELECT member.cohort_id,
               member.institution_id,
               hourly.hour_offset,
               metric.metric_key,
               metric.metric_value,
               metric.metric_quality
          FROM analytics.comparison_cohort_member AS member
          JOIN analytics.comparison_cohort AS cohort ON cohort.id = member.cohort_id
          JOIN analytics.publication_hourly AS hourly
           ON hourly.publication_id = member.publication_id
           AND hourly.dataset_revision_id = cohort.dataset_revision_id
           AND hourly.hour_offset >=
               (cohort.filter_definition->>'required_start_hour')::integer
           AND hourly.hour_offset <= cohort.horizon_seconds / 3600
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, hourly.views_count, hourly.views_quality),
             ('reactions'::analytics.metric_key, hourly.reactions_count, hourly.reactions_quality),
             ('comments'::analytics.metric_key, hourly.comments_count, hourly.comments_quality),
             ('shares'::analytics.metric_key, hourly.shares_count, hourly.shares_quality)
         ) AS metric(metric_key, metric_value, metric_quality)
         WHERE cohort.dataset_revision_id = p_dataset_revision_id
    ), grouped AS (
        SELECT cohort_id, institution_id, hour_offset, metric_key,
               count(*) AS publication_count,
               count(metric_value) AS sample_size,
               sum(metric_value) AS sum_value,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY metric_value)
                   FILTER (WHERE metric_value IS NOT NULL)::numeric AS median_value,
               max(analytics.observation_quality_rank(metric_quality))
                   FILTER (WHERE metric_value IS NOT NULL) AS worst_quality_rank
          FROM metric_facts
         GROUP BY cohort_id, institution_id, hour_offset, metric_key
    )
    INSERT INTO analytics.comparison_metric_point (
        cohort_id, institution_id, metric_key, aggregation, hour_offset,
        value, sample_size, coverage, quality
    )
    SELECT grouped.cohort_id,
           grouped.institution_id,
           grouped.metric_key,
           aggregate_value.aggregation,
           grouped.hour_offset,
           aggregate_value.value,
           grouped.sample_size::integer,
           round(grouped.sample_size::numeric / grouped.publication_count, 6),
           analytics.observation_quality_from_rank(grouped.worst_quality_rank)
      FROM grouped
     CROSS JOIN LATERAL (VALUES
         ('sum'::analytics.aggregation_code, grouped.sum_value),
         ('median'::analytics.aggregation_code, round(grouped.median_value, 0))
     ) AS aggregate_value(aggregation, value);

    GET DIAGNOSTICS comparison_rows = ROW_COUNT;

    INSERT INTO analytics.projection_state AS state (
        projection_name, dataset_revision_id, status, refreshed_at, row_count, error_code
    ) VALUES
        ('publication_latest', p_dataset_revision_id, 'ready', transaction_timestamp(),
            publication_latest_rows, NULL),
        ('publication_hourly', p_dataset_revision_id, 'ready', transaction_timestamp(),
            publication_hourly_rows, NULL),
        ('institution_daily_metrics', p_dataset_revision_id, 'ready', transaction_timestamp(),
            institution_daily_rows, NULL),
        ('institution_monthly_metrics', p_dataset_revision_id, 'ready', transaction_timestamp(),
            institution_monthly_rows, NULL),
        ('institution_period_metrics', p_dataset_revision_id, 'ready', transaction_timestamp(),
            institution_period_rows, NULL),
        ('comparison', p_dataset_revision_id, 'ready', transaction_timestamp(),
            comparison_rows, NULL)
    ON CONFLICT (projection_name) DO UPDATE SET
        dataset_revision_id = excluded.dataset_revision_id,
        status = excluded.status,
        refreshed_at = excluded.refreshed_at,
        row_count = excluded.row_count,
        error_code = NULL;

    RETURN jsonb_build_object(
        'dataset_revision_id', p_dataset_revision_id,
        'publication_latest', publication_latest_rows,
        'publication_hourly', publication_hourly_rows,
        'institution_daily_metrics', institution_daily_rows,
        'institution_monthly_metrics', institution_monthly_rows,
        'institution_period_metrics', institution_period_rows,
        'comparison', comparison_rows
    );
END
$function$;

CREATE OR REPLACE FUNCTION analytics.rebuild_core_projections_v5(p_dataset_revision_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest, analytics
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    base_result jsonb;
    revision_as_of timestamptz;
    institution_period_rows bigint;
BEGIN
    -- V2 validates the newest revision, takes the transaction-scoped publisher
    -- lock, and rebuilds the other five projections. Its lock remains held
    -- while this wrapper replaces the obsolete period projection.
    base_result := analytics.rebuild_core_projections_v2(p_dataset_revision_id);

    SELECT committed_at
      INTO STRICT revision_as_of
      FROM analytics.dataset_revision
     WHERE id = p_dataset_revision_id;

    DELETE FROM analytics.institution_period_metrics;

    WITH periods(period_key, duration) AS (VALUES
        ('3h'::text, interval '3 hours'),
        ('1d'::text, interval '1 day'),
        ('7d'::text, interval '7 days'),
        ('30d'::text, interval '30 days')
    ), metric_keys(metric_key) AS (VALUES
        ('views'::analytics.metric_key),
        ('reactions'::analytics.metric_key),
        ('comments'::analytics.metric_key),
        ('shares'::analytics.metric_key)
    ), aggregations(aggregation) AS (VALUES
        ('sum'::analytics.aggregation_code),
        ('median'::analytics.aggregation_code)
    ), platform_dimensions AS (
        SELECT DISTINCT account.institution_id, account.platform
          FROM catalog.platform_account AS account
         WHERE account.enabled
    ), all_dimensions AS (
        -- platform IS NULL is catalog coverage only. Cross-platform counters
        -- are intentionally never summed or ranked as comparable quantities,
        -- and metric sample_size must not be overloaded with account count.
        SELECT institution.id AS institution_id,
               round(
                   count(DISTINCT account.platform)::numeric /
                   cardinality(enum_range(NULL::catalog.platform_code)),
                   6
               ) AS platform_coverage
          FROM catalog.institution AS institution
          LEFT JOIN catalog.platform_account AS account
            ON account.institution_id = institution.id
           AND account.enabled
         WHERE institution.status = 'active'
         GROUP BY institution.id
    ), window_observations AS (
        SELECT period.period_key,
               revision_as_of - period.duration AS window_start,
               revision_as_of AS window_end,
               account.institution_id,
               account.platform,
               publication.id AS publication_id,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed,
               snapshot.published_month AS snapshot_month,
               snapshot.id AS snapshot_id,
               snapshot.views_count,
               snapshot.reactions_count,
               snapshot.comments_count,
               snapshot.shares_count,
               analytics.observation_quality_rank(snapshot.views_quality) AS views_quality_rank,analytics.observation_quality_rank(snapshot.reactions_quality) AS reactions_quality_rank,analytics.observation_quality_rank(snapshot.comments_quality) AS comments_quality_rank,analytics.observation_quality_rank(snapshot.shares_quality) AS shares_quality_rank,
               row_number() OVER (
                   PARTITION BY period.period_key, publication.id
                   ORDER BY snapshot.observed_at, snapshot.published_month, snapshot.id
               ) AS first_position,
               row_number() OVER (
                   PARTITION BY period.period_key, publication.id
                   ORDER BY snapshot.observed_at DESC,
                            snapshot.published_month DESC, snapshot.id DESC
               ) AS latest_position,
               count(*) OVER (
                   PARTITION BY period.period_key, publication.id
               ) AS observation_count
          FROM periods AS period
          JOIN ingest.publication AS publication
            ON publication.published_at <= revision_as_of
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
           AND account.enabled
          JOIN pg_temp.mranked_projection_snapshot AS snapshot
            ON snapshot.publication_id = publication.id
           AND snapshot.observed_at > revision_as_of - period.duration
           AND snapshot.observed_at <= revision_as_of
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
    ), publication_bounds AS (
        SELECT observation.period_key,
               observation.window_start,
               observation.window_end,
               observation.institution_id,
               observation.platform,
               observation.publication_id,
               observation.published_at,
               observation.history_completeness,
               observation.synthetic_baseline_allowed,
               max(observation.observation_count) AS observation_count,
               max(observation.views_count)
                   FILTER (WHERE observation.first_position = 1) AS first_views,
               max(observation.views_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_views,
               max(observation.reactions_count)
                   FILTER (WHERE observation.first_position = 1) AS first_reactions,
               max(observation.reactions_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_reactions,
               max(observation.comments_count)
                   FILTER (WHERE observation.first_position = 1) AS first_comments,
               max(observation.comments_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_comments,
               max(observation.shares_count)
                   FILTER (WHERE observation.first_position = 1) AS first_shares,
               max(observation.shares_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_shares,
               max(observation.views_quality_rank) FILTER (WHERE observation.first_position=1) AS first_views_quality_rank,
               max(observation.views_quality_rank) FILTER (WHERE observation.latest_position=1) AS latest_views_quality_rank,
               max(observation.reactions_quality_rank) FILTER (WHERE observation.first_position=1) AS first_reactions_quality_rank,
               max(observation.reactions_quality_rank) FILTER (WHERE observation.latest_position=1) AS latest_reactions_quality_rank,
               max(observation.comments_quality_rank) FILTER (WHERE observation.first_position=1) AS first_comments_quality_rank,
               max(observation.comments_quality_rank) FILTER (WHERE observation.latest_position=1) AS latest_comments_quality_rank,
               max(observation.shares_quality_rank) FILTER (WHERE observation.first_position=1) AS first_shares_quality_rank,
               max(observation.shares_quality_rank) FILTER (WHERE observation.latest_position=1) AS latest_shares_quality_rank
          FROM window_observations AS observation
         GROUP BY observation.period_key, observation.window_start,
                  observation.window_end, observation.institution_id,
                  observation.platform, observation.publication_id,
                  observation.published_at, observation.history_completeness,
                  observation.synthetic_baseline_allowed
    ), publication_metric_delta AS (
        SELECT bounds.period_key,
               bounds.window_start,
               bounds.window_end,
               bounds.institution_id,
               bounds.platform,
               bounds.publication_id,
               metric.metric_key,
               CASE
                   WHEN metric.latest_value IS NULL THEN NULL
                   -- Telegram carried an explicit legacy
                   -- baseline_from_publication decision. The other legacy
                   -- collectors represented the same age/completeness gate in
                   -- history_completeness instead of a baseline column.
                   WHEN bounds.published_at >= bounds.window_start
                        AND (
                            (bounds.platform = 'telegram'
                             AND bounds.synthetic_baseline_allowed)
                            OR
                            (bounds.platform <> 'telegram'
                             AND bounds.history_completeness = 'complete')
                        )
                       THEN metric.latest_value::numeric
                   WHEN bounds.observation_count >= 2
                        AND metric.first_value IS NOT NULL
                       THEN metric.latest_value::numeric - metric.first_value::numeric
                   ELSE NULL
               END AS delta_value,
               greatest(metric.first_quality_rank, metric.latest_quality_rank)
                   AS delta_quality_rank
          FROM publication_bounds AS bounds
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key,
                 bounds.first_views, bounds.latest_views, bounds.first_views_quality_rank, bounds.latest_views_quality_rank),
             ('reactions'::analytics.metric_key,
                 bounds.first_reactions, bounds.latest_reactions, bounds.first_reactions_quality_rank, bounds.latest_reactions_quality_rank),
             ('comments'::analytics.metric_key,
                 bounds.first_comments, bounds.latest_comments, bounds.first_comments_quality_rank, bounds.latest_comments_quality_rank),
             ('shares'::analytics.metric_key,
                 bounds.first_shares, bounds.latest_shares, bounds.first_shares_quality_rank, bounds.latest_shares_quality_rank)
         ) AS metric(metric_key, first_value, latest_value, first_quality_rank, latest_quality_rank)
    ), candidates AS (
        SELECT bounds.institution_id,
               bounds.platform,
               bounds.period_key,
               count(*)::integer AS publication_count
          FROM publication_bounds AS bounds
         GROUP BY bounds.institution_id, bounds.platform, bounds.period_key
    ), ranked_delta AS (
        SELECT delta.*,
               row_number() OVER (
                   PARTITION BY delta.institution_id, delta.platform,
                                delta.period_key, delta.metric_key
                   ORDER BY delta.delta_value, delta.publication_id
               ) AS rank_position,
               count(*) OVER (
                   PARTITION BY delta.institution_id, delta.platform,
                                delta.period_key, delta.metric_key
               ) AS sample_size
          FROM publication_metric_delta AS delta
         WHERE delta.delta_value IS NOT NULL
    ), grouped AS (
        SELECT delta.institution_id,
               delta.platform,
               delta.period_key,
               delta.metric_key,
               max(delta.sample_size)::integer AS sample_size,
               sum(delta.delta_value) AS sum_value,
               floor(
                   avg(delta.delta_value) FILTER (
                       WHERE delta.rank_position IN (
                           (delta.sample_size + 1) / 2,
                           (delta.sample_size + 2) / 2
                       )
                   ) + 0.5
               ) AS median_value,
               max(delta.delta_quality_rank) AS worst_quality_rank
          FROM ranked_delta AS delta
         GROUP BY delta.institution_id, delta.platform,
                  delta.period_key, delta.metric_key
    ), replacement_rows AS (
        SELECT dimension.institution_id,
               dimension.platform,
               period.period_key,
               metric.metric_key,
               aggregation.aggregation,
               revision_as_of - period.duration AS window_start,
               revision_as_of AS window_end,
               CASE aggregation.aggregation
                   WHEN 'sum' THEN grouped.sum_value
                   ELSE grouped.median_value
               END AS value,
               coalesce(grouped.sample_size, 0) AS sample_size,
               CASE
                   WHEN coalesce(candidate.publication_count, 0) = 0 THEN 0::numeric
                   ELSE round(
                       coalesce(grouped.sample_size, 0)::numeric /
                       candidate.publication_count,
                       6
                   )
               END AS coverage,
               analytics.observation_quality_from_rank(grouped.worst_quality_rank)
                   AS quality
          FROM platform_dimensions AS dimension
         CROSS JOIN periods AS period
         CROSS JOIN metric_keys AS metric
         CROSS JOIN aggregations AS aggregation
          LEFT JOIN candidates AS candidate
            ON candidate.institution_id = dimension.institution_id
           AND candidate.platform = dimension.platform
           AND candidate.period_key = period.period_key
          LEFT JOIN grouped
            ON grouped.institution_id = dimension.institution_id
           AND grouped.platform = dimension.platform
           AND grouped.period_key = period.period_key
           AND grouped.metric_key = metric.metric_key

        UNION ALL

        SELECT dimension.institution_id,
               NULL::catalog.platform_code,
               period.period_key,
               metric.metric_key,
               aggregation.aggregation,
               revision_as_of - period.duration,
               revision_as_of,
               NULL::numeric,
               0,
               dimension.platform_coverage,
               'unknown'::ingest.observation_quality
          FROM all_dimensions AS dimension
         CROSS JOIN periods AS period
         CROSS JOIN metric_keys AS metric
         CROSS JOIN aggregations AS aggregation
    )
    INSERT INTO analytics.institution_period_metrics (
        institution_id, platform, period_key, metric_key, aggregation,
        window_start, window_end, value, sample_size, coverage, quality,
        as_of, dataset_revision_id, refreshed_at
    )
    SELECT row.institution_id,
           row.platform,
           row.period_key,
           row.metric_key,
           row.aggregation,
           row.window_start,
           row.window_end,
           row.value,
           row.sample_size,
           row.coverage,
           row.quality,
           revision_as_of,
           p_dataset_revision_id,
           transaction_timestamp()
      FROM replacement_rows AS row;

    GET DIAGNOSTICS institution_period_rows = ROW_COUNT;

    UPDATE analytics.projection_state
       SET dataset_revision_id = p_dataset_revision_id,
           status = 'ready',
           refreshed_at = transaction_timestamp(),
           row_count = institution_period_rows,
           error_code = NULL
     WHERE projection_name = 'institution_period_metrics';

    RETURN base_result || jsonb_build_object(
        'institution_period_metrics', institution_period_rows,
        'institution_period_semantics_version', 2
    );
END
$function$;

CREATE OR REPLACE FUNCTION analytics.rebuild_core_projections_v6(p_dataset_revision_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest, analytics
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    base_result jsonb;
    revision_as_of timestamptz;
    comparison_hourly_rows bigint;
BEGIN
    base_result := analytics.rebuild_core_projections_v5(p_dataset_revision_id);

    SELECT committed_at
      INTO STRICT revision_as_of
      FROM analytics.dataset_revision
     WHERE id = p_dataset_revision_id;

    DELETE FROM analytics.comparison_publication_hourly;

    WITH publication_limits AS (
        SELECT publication.id AS publication_id,
               publication.primary_account_id AS platform_account_id,
               account.institution_id,
               account.platform,
               publication.published_at,
               publication.synthetic_baseline_allowed,
               max(cohort.horizon_seconds / 3600)::integer AS max_hour
          FROM analytics.comparison_cohort_member AS member
          JOIN analytics.comparison_cohort AS cohort
            ON cohort.id = member.cohort_id
           AND cohort.dataset_revision_id = p_dataset_revision_id
          JOIN ingest.publication AS publication ON publication.id = member.publication_id
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
         GROUP BY publication.id, publication.primary_account_id,
                  account.institution_id, account.platform,
                  publication.published_at,
                  publication.synthetic_baseline_allowed
    ), target_hours AS (
        SELECT limits.*,
               series.hour_offset
          FROM publication_limits AS limits
         CROSS JOIN LATERAL generate_series(0, limits.max_hour) AS series(hour_offset)
    )
    INSERT INTO analytics.comparison_publication_hourly (
        publication_id, hour_offset, institution_id, platform_account_id, platform,
        views_count, views_quality, reactions_count, reactions_quality,
        comments_count, comments_quality, shares_count, shares_quality,
        engagement_percent, engagement_quality, dataset_revision_id
    )
    SELECT target.publication_id,
           target.hour_offset,
           target.institution_id,
           target.platform_account_id,
           target.platform,
           views.value,
           views.quality,
           reactions.value,
           reactions.quality,
           comments.value,
           comments.quality,
           shares.value,
           shares.quality,
           engagement.value,
           engagement.quality,
           p_dataset_revision_id
      FROM target_hours AS target
      LEFT JOIN LATERAL (
          SELECT snapshot.views_count AS value,
                 snapshot.views_quality AS quality
            FROM pg_temp.mranked_projection_snapshot AS snapshot
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND snapshot.views_count IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS views ON true
      LEFT JOIN LATERAL (
          SELECT snapshot.reactions_count AS value,
                 snapshot.reactions_quality AS quality
            FROM pg_temp.mranked_projection_snapshot AS snapshot
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND snapshot.reactions_count IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS reactions ON true
      LEFT JOIN LATERAL (
          SELECT snapshot.comments_count AS value,
                 snapshot.comments_quality AS quality
            FROM pg_temp.mranked_projection_snapshot AS snapshot
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND snapshot.comments_count IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS comments ON true
      LEFT JOIN LATERAL (
          SELECT snapshot.shares_count AS value,
                 snapshot.shares_quality AS quality
            FROM pg_temp.mranked_projection_snapshot AS snapshot
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND snapshot.shares_count IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS shares ON true
      LEFT JOIN LATERAL (
          SELECT ratio.value,
                 snapshot.quality
            FROM pg_temp.mranked_projection_snapshot AS snapshot
           CROSS JOIN LATERAL (
               SELECT CASE
                   WHEN snapshot.views_count IS NULL OR snapshot.views_count <= 0 THEN NULL
                   WHEN target.platform = 'telegram' THEN
                       CASE WHEN snapshot.reactions_count IS NULL THEN NULL
                            ELSE snapshot.reactions_count::numeric * 100::numeric
                                 / snapshot.views_count::numeric END
                   WHEN target.platform IN ('vk', 'rutube') THEN
                       CASE
                           WHEN snapshot.reactions_count IS NULL
                            AND snapshot.comments_count IS NULL
                            AND snapshot.shares_count IS NULL THEN NULL
                           ELSE (
                               coalesce(snapshot.reactions_count, 0)::numeric
                               + coalesce(snapshot.comments_count, 0)::numeric
                               + coalesce(snapshot.shares_count, 0)::numeric
                           ) * 100::numeric / snapshot.views_count::numeric
                       END
                   ELSE NULL
               END AS value
           ) AS ratio
           WHERE snapshot.publication_id = target.publication_id
             AND snapshot.age_seconds <= target.hour_offset * 3600
             AND snapshot.observed_at <=
                 target.published_at + target.hour_offset * interval '1 hour'
             AND snapshot.observed_at <= revision_as_of
             AND snapshot.collected_at <= revision_as_of
             AND (NOT snapshot.synthetic OR target.synthetic_baseline_allowed)
             AND snapshot.quality <> 'invalid'
             AND ratio.value IS NOT NULL
           ORDER BY snapshot.age_seconds DESC, snapshot.observed_at DESC,
                    snapshot.published_month DESC, snapshot.id DESC
           LIMIT 1
      ) AS engagement ON true;

    GET DIAGNOSTICS comparison_hourly_rows = ROW_COUNT;

    RETURN base_result || jsonb_build_object(
        'comparison_publication_hourly', comparison_hourly_rows,
        'comparison_semantics_version', 2
    );
END
$function$;

CREATE OR REPLACE FUNCTION analytics.rebuild_core_projections(p_dataset_revision_id bigint)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, catalog, ingest, analytics, rating, ops_and_admin, migration
SET lock_timeout = '10s'
SET statement_timeout = '15min'
AS $function$
DECLARE
    base_result jsonb;
    revision_as_of timestamptz;
    overview_account_rows bigint;
    overview_card_rows bigint;
BEGIN
    base_result := analytics.rebuild_core_projections_v6(p_dataset_revision_id);

    SELECT committed_at
      INTO STRICT revision_as_of
      FROM analytics.dataset_revision
     WHERE id = p_dataset_revision_id;

    DELETE FROM analytics.legacy_overview_card;
    DELETE FROM analytics.legacy_overview_account;

    WITH latest_account_metric AS (
        SELECT DISTINCT ON (snapshot.platform_account_id)
               snapshot.platform_account_id,
               snapshot.subscriber_count,
               snapshot.subscriber_display,
               snapshot.observed_at
          FROM ingest.account_metric_snapshot_active AS snapshot
         WHERE snapshot.observed_at <= revision_as_of
           AND snapshot.collected_at <= revision_as_of
           AND snapshot.quality <> 'invalid'
         ORDER BY snapshot.platform_account_id, snapshot.observed_at DESC, snapshot.id DESC
    ), latest_account_result AS (
        SELECT DISTINCT ON (result.platform_account_id)
               result.platform_account_id,
               result.started_at,
               CASE WHEN result.completed_at <= revision_as_of
                    THEN result.completed_at END AS completed_at,
               CASE WHEN result.completed_at IS NULL
                          OR result.completed_at > revision_as_of
                    THEN 'running'::ingest.run_status
                    ELSE result.status END AS status,
               CASE
                   WHEN result.completed_at <= revision_as_of
                    AND result.status IN ('failed', 'partial') THEN
                       coalesce(result.sanitized_error_code, 'collection_failed')
                   WHEN result.completed_at <= revision_as_of
                       THEN result.sanitized_error_code
                   ELSE NULL
               END AS error_code
          FROM ingest.collection_account_result AS result
         WHERE result.started_at <= revision_as_of
         ORDER BY result.platform_account_id, result.started_at DESC, result.id DESC
    ), legacy_error AS (
        SELECT identity.target_uuid AS platform_account_id,
               bool_or(identity.source_table = 'channels')
                   FILTER (WHERE evidence.id IS NOT NULL) AS channel_error,
               bool_or(identity.source_table = 'platform_accounts')
                   FILTER (WHERE evidence.id IS NOT NULL) AS platform_account_error
          FROM migration.legacy_identity_map AS identity
          LEFT JOIN migration.legacy_evidence AS evidence
            ON evidence.batch_id = identity.last_seen_batch_id
           AND evidence.source_table = identity.source_table
           AND evidence.source_pk = identity.source_pk
           AND evidence.source_row_hash = identity.source_row_hash
           AND evidence.evidence_kind = 'sanitized_last_error'
           AND evidence.evidence->>'present' = 'true'
         WHERE identity.target_type = 'platform_account'
           AND identity.source_table IN ('channels', 'platform_accounts')
         GROUP BY identity.target_uuid
    ), last_checked AS (
        SELECT DISTINCT ON (checkpoint.scope_id)
               checkpoint.scope_id AS platform_account_id,
               checkpoint.source_observed_at
          FROM ops_and_admin.operational_checkpoint AS checkpoint
         WHERE checkpoint.scope_type = 'account'
           AND checkpoint.checkpoint_key = 'last_checked_at'
           AND checkpoint.source_observed_at <= revision_as_of
         ORDER BY checkpoint.scope_id, checkpoint.source_observed_at DESC,
                  checkpoint.updated_at DESC, checkpoint.id DESC
    ), account_fact AS (
        SELECT account.id,
               account.institution_id,
               account.platform,
               account.canonical_external_id,
               account.current_username,
               account.current_title,
               account.current_url,
               account.access_mode,
               account.enabled,
               channel_alias.legacy_id AS channel_legacy_id,
               channel_alias.legacy_route AS channel_legacy_route,
               platform_alias.legacy_id AS platform_legacy_id,
               platform_alias.legacy_route AS platform_legacy_route,
               metric.subscriber_count,
               metric.subscriber_display,
               metric.observed_at AS subscriber_observed_at,
               result.started_at AS latest_poll_started_at,
               result.completed_at AS latest_poll_completed_at,
               result.status AS latest_poll_status,
               CASE
                   WHEN result.platform_account_id IS NOT NULL THEN result.error_code
                   WHEN coalesce(error.channel_error, false)
                     OR coalesce(error.platform_account_error, false)
                       THEN 'legacy_error_present'
                   ELSE NULL
               END AS latest_error_code,
               greatest(
                   checked.source_observed_at,
                   result.completed_at,
                   result.started_at,
                   metric.observed_at
               ) AS last_checked_at,
               coalesce(error.channel_error, false) AS channel_error,
               coalesce(error.platform_account_error, false) AS platform_account_error
          FROM catalog.platform_account AS account
          LEFT JOIN catalog.legacy_entity_alias AS channel_alias
            ON channel_alias.target_uuid = account.id
           AND channel_alias.entity_type = 'channels'
          LEFT JOIN catalog.legacy_entity_alias AS platform_alias
            ON platform_alias.target_uuid = account.id
           AND platform_alias.entity_type = 'platform_accounts'
          LEFT JOIN latest_account_metric AS metric
            ON metric.platform_account_id = account.id
          LEFT JOIN latest_account_result AS result
            ON result.platform_account_id = account.id
          LEFT JOIN legacy_error AS error
            ON error.platform_account_id = account.id
          LEFT JOIN last_checked AS checked
            ON checked.platform_account_id = account.id
    ), telegram_dimensions AS (
        SELECT 'telegram'::analytics.platform_scope AS platform,
               account.id AS entity_id,
               account.institution_id
          FROM account_fact AS account
         WHERE account.platform = 'telegram'
           AND account.enabled
           AND account.channel_legacy_id IS NOT NULL
    ), institution_dimensions AS (
        SELECT scope.platform,
               institution.id AS entity_id,
               institution.id AS institution_id
          FROM catalog.institution AS institution
         CROSS JOIN (VALUES
             ('all'::analytics.platform_scope),
             ('vk'::analytics.platform_scope),
             ('max'::analytics.platform_scope),
             ('rutube'::analytics.platform_scope)
         ) AS scope(platform)
    ), dimensions AS (
        SELECT * FROM telegram_dimensions
        UNION ALL
        SELECT * FROM institution_dimensions
    ), selected_accounts AS (
        SELECT dimension.platform AS scope_platform,
               dimension.entity_id,
               account.*,
               CASE
                   WHEN dimension.platform = 'telegram' THEN account.channel_legacy_id
                   ELSE coalesce(account.platform_legacy_id, account.channel_legacy_id)
               END AS selected_legacy_id,
               CASE
                   WHEN dimension.platform = 'telegram' THEN account.channel_legacy_route
                   ELSE coalesce(account.platform_legacy_route, account.channel_legacy_route)
               END AS selected_legacy_route,
               CASE
                   WHEN account.latest_poll_status IS NOT NULL THEN account.latest_error_code
                   WHEN dimension.platform = 'telegram' AND account.channel_error
                       THEN 'legacy_error_present'
                   WHEN dimension.platform <> 'telegram' AND account.platform_account_error
                       THEN 'legacy_error_present'
                   ELSE NULL
               END AS selected_error_code
          FROM dimensions AS dimension
          JOIN account_fact AS account
            ON account.institution_id = dimension.institution_id
           AND (
               (dimension.platform = 'telegram' AND account.id = dimension.entity_id)
               OR dimension.platform = 'all'
               OR account.platform::text = dimension.platform::text
           )
    )
    INSERT INTO analytics.legacy_overview_account (
        dataset_revision_id, platform, entity_id, position, account_id,
        legacy_id, legacy_route, account_platform, canonical_external_id,
        username, title, url, access_mode, enabled, subscriber_count,
        subscriber_display, subscriber_observed_at, latest_poll_started_at,
        latest_poll_completed_at, latest_poll_status, latest_error_code,
        last_checked_at
    )
    SELECT p_dataset_revision_id,
           account.scope_platform,
           account.entity_id,
           row_number() OVER (
               PARTITION BY account.scope_platform, account.entity_id
               ORDER BY account.platform, lower(coalesce(
                   nullif(account.current_title, ''),
                   nullif(account.current_username, ''),
                   account.canonical_external_id
               )), account.id
           )::integer,
           account.id,
           account.selected_legacy_id,
           account.selected_legacy_route,
           account.platform,
           account.canonical_external_id,
           account.current_username,
           account.current_title,
           account.current_url,
           account.access_mode,
           account.enabled,
           account.subscriber_count,
           account.subscriber_display,
           account.subscriber_observed_at,
           account.latest_poll_started_at,
           account.latest_poll_completed_at,
           account.latest_poll_status,
           account.selected_error_code,
           account.last_checked_at
      FROM selected_accounts AS account;

    GET DIAGNOSTICS overview_account_rows = ROW_COUNT;

    WITH periods(period_key, duration) AS (VALUES
        ('3h'::text, interval '3 hours'),
        ('1d'::text, interval '1 day'),
        ('7d'::text, interval '7 days'),
        ('30d'::text, interval '30 days')
    ), activity_windows AS (
        SELECT period.period_key,
               0 AS window_index,
               revision_as_of - period.duration AS window_start,
               revision_as_of AS window_end
          FROM periods AS period
        UNION ALL
        SELECT period.period_key,
               1,
               revision_as_of - period.duration * 2,
               revision_as_of - period.duration
          FROM periods AS period
    ), telegram_dimensions AS (
        SELECT 'telegram'::analytics.platform_scope AS platform,
               account.id AS entity_id,
               'channels'::text AS entity_type,
               channel_alias.legacy_id,
               channel_alias.legacy_route,
               account.institution_id
          FROM catalog.platform_account AS account
          JOIN catalog.legacy_entity_alias AS channel_alias
            ON channel_alias.target_uuid = account.id
           AND channel_alias.entity_type = 'channels'
         WHERE account.platform = 'telegram'
           AND account.enabled
    ), institution_dimensions AS (
        SELECT scope.platform,
               institution.id AS entity_id,
               'institutions'::text AS entity_type,
               institution_alias.legacy_id,
               institution_alias.legacy_route,
               institution.id AS institution_id
          FROM catalog.institution AS institution
          JOIN catalog.legacy_entity_alias AS institution_alias
            ON institution_alias.target_uuid = institution.id
           AND institution_alias.entity_type = 'institutions'
         CROSS JOIN (VALUES
             ('all'::analytics.platform_scope),
             ('vk'::analytics.platform_scope),
             ('max'::analytics.platform_scope),
             ('rutube'::analytics.platform_scope)
         ) AS scope(platform)
    ), dimensions AS (
        SELECT * FROM telegram_dimensions
        UNION ALL
        SELECT * FROM institution_dimensions
    ), activity_publications AS (
        SELECT 'telegram'::analytics.platform_scope AS platform,
               account.id AS entity_id,
               publication.id AS publication_id,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed
          FROM ingest.publication AS publication
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
          JOIN catalog.legacy_entity_alias AS channel_alias
            ON channel_alias.target_uuid = account.id
           AND channel_alias.entity_type = 'channels'
         WHERE account.platform = 'telegram'
           AND account.enabled
           AND publication.published_at <= revision_as_of
           AND publication.created_at <= revision_as_of
        UNION ALL
        SELECT account.platform::text::analytics.platform_scope,
               account.institution_id,
               publication.id,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed
          FROM ingest.publication AS publication
          JOIN catalog.platform_account AS account
            ON account.id = publication.primary_account_id
         WHERE account.platform <> 'telegram'
           AND publication.published_at <= revision_as_of
           AND publication.created_at <= revision_as_of
    ), window_observations AS (
        SELECT activity_window.period_key,
               activity_window.window_index,
               activity_window.window_start,
               activity_window.window_end,
               publication.platform,
               publication.entity_id,
               publication.publication_id,
               publication.published_at,
               publication.history_completeness,
               publication.synthetic_baseline_allowed,
               snapshot.views_count,
               snapshot.reactions_count,
               snapshot.comments_count,
               snapshot.shares_count,
               row_number() OVER (
                   PARTITION BY activity_window.period_key, activity_window.window_index,
                                publication.publication_id
                   ORDER BY snapshot.observed_at, snapshot.published_month, snapshot.id
               ) AS first_position,
               row_number() OVER (
                   PARTITION BY activity_window.period_key, activity_window.window_index,
                                publication.publication_id
                   ORDER BY snapshot.observed_at DESC,
                            snapshot.published_month DESC, snapshot.id DESC
               ) AS latest_position,
               count(*) OVER (
                   PARTITION BY activity_window.period_key, activity_window.window_index,
                                publication.publication_id
               ) AS observation_count
          FROM activity_windows AS activity_window
          JOIN activity_publications AS publication
            ON publication.published_at <= activity_window.window_end
          JOIN pg_temp.mranked_projection_snapshot AS snapshot
            ON snapshot.publication_id = publication.publication_id
           AND snapshot.observed_at > activity_window.window_start
           AND snapshot.observed_at <= activity_window.window_end
           AND snapshot.collected_at <= revision_as_of
           AND NOT snapshot.synthetic
           AND snapshot.quality <> 'invalid'
    ), publication_bounds AS (
        SELECT observation.period_key,
               observation.window_index,
               observation.window_start,
               observation.window_end,
               observation.platform,
               observation.entity_id,
               observation.publication_id,
               observation.published_at,
               observation.history_completeness,
               observation.synthetic_baseline_allowed,
               max(observation.observation_count) AS observation_count,
               max(observation.views_count)
                   FILTER (WHERE observation.first_position = 1) AS first_views,
               max(observation.views_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_views,
               max(observation.reactions_count)
                   FILTER (WHERE observation.first_position = 1) AS first_reactions,
               max(observation.reactions_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_reactions,
               max(observation.comments_count)
                   FILTER (WHERE observation.first_position = 1) AS first_comments,
               max(observation.comments_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_comments,
               max(observation.shares_count)
                   FILTER (WHERE observation.first_position = 1) AS first_shares,
               max(observation.shares_count)
                   FILTER (WHERE observation.latest_position = 1) AS latest_shares
          FROM window_observations AS observation
         GROUP BY observation.period_key, observation.window_index,
                  observation.window_start, observation.window_end,
                  observation.platform, observation.entity_id,
                  observation.publication_id, observation.published_at,
                  observation.history_completeness,
                  observation.synthetic_baseline_allowed
    ), publication_delta AS (
        SELECT bounds.*,
               CASE
                   WHEN bounds.latest_views IS NULL THEN NULL
                   WHEN bounds.published_at >= bounds.window_start
                    AND ((bounds.platform = 'telegram' AND bounds.synthetic_baseline_allowed)
                      OR (bounds.platform <> 'telegram'
                          AND bounds.history_completeness = 'complete'))
                       THEN bounds.latest_views::numeric
                   WHEN bounds.observation_count >= 2 AND bounds.first_views IS NOT NULL
                       THEN bounds.latest_views::numeric - bounds.first_views::numeric
                   ELSE NULL
               END AS views_delta,
               CASE
                   WHEN bounds.latest_reactions IS NULL THEN NULL
                   WHEN bounds.published_at >= bounds.window_start
                    AND ((bounds.platform = 'telegram' AND bounds.synthetic_baseline_allowed)
                      OR (bounds.platform <> 'telegram'
                          AND bounds.history_completeness = 'complete'))
                       THEN bounds.latest_reactions::numeric
                   WHEN bounds.observation_count >= 2 AND bounds.first_reactions IS NOT NULL
                       THEN bounds.latest_reactions::numeric - bounds.first_reactions::numeric
                   ELSE NULL
               END AS reactions_delta,
               CASE
                   WHEN bounds.latest_comments IS NULL THEN NULL
                   WHEN bounds.published_at >= bounds.window_start
                    AND ((bounds.platform = 'telegram' AND bounds.synthetic_baseline_allowed)
                      OR (bounds.platform <> 'telegram'
                          AND bounds.history_completeness = 'complete'))
                       THEN bounds.latest_comments::numeric
                   WHEN bounds.observation_count >= 2 AND bounds.first_comments IS NOT NULL
                       THEN bounds.latest_comments::numeric - bounds.first_comments::numeric
                   ELSE NULL
               END AS comments_delta,
               CASE
                   WHEN bounds.latest_shares IS NULL THEN NULL
                   WHEN bounds.published_at >= bounds.window_start
                    AND ((bounds.platform = 'telegram' AND bounds.synthetic_baseline_allowed)
                      OR (bounds.platform <> 'telegram'
                          AND bounds.history_completeness = 'complete'))
                       THEN bounds.latest_shares::numeric
                   WHEN bounds.observation_count >= 2 AND bounds.first_shares IS NOT NULL
                       THEN bounds.latest_shares::numeric - bounds.first_shares::numeric
                   ELSE NULL
               END AS shares_delta
          FROM publication_bounds AS bounds
    ), activity_count AS (
        SELECT delta.period_key,
               delta.window_index,
               delta.platform,
               delta.entity_id,
               count(*)::bigint AS publication_count
          FROM publication_delta AS delta
         WHERE delta.views_delta IS NOT NULL
            OR delta.reactions_delta IS NOT NULL
            OR delta.comments_delta IS NOT NULL
            OR delta.shares_delta IS NOT NULL
         GROUP BY delta.period_key, delta.window_index,
                  delta.platform, delta.entity_id
    ), metric_delta AS (
        SELECT delta.period_key,
               delta.window_index,
               delta.platform,
               delta.entity_id,
               delta.publication_id,
               metric.metric_key,
               metric.delta_value
          FROM publication_delta AS delta
         CROSS JOIN LATERAL (VALUES
             ('views'::analytics.metric_key, delta.views_delta),
             ('reactions'::analytics.metric_key, delta.reactions_delta),
             ('comments'::analytics.metric_key, delta.comments_delta),
             ('shares'::analytics.metric_key, delta.shares_delta)
         ) AS metric(metric_key, delta_value)
         WHERE metric.delta_value IS NOT NULL
    ), ranked_metric AS (
        SELECT metric.*,
               row_number() OVER (
                   PARTITION BY metric.period_key, metric.window_index,
                                metric.platform, metric.entity_id, metric.metric_key
                   ORDER BY metric.delta_value, metric.publication_id
               ) AS rank_position,
               count(*) OVER (
                   PARTITION BY metric.period_key, metric.window_index,
                                metric.platform, metric.entity_id, metric.metric_key
               ) AS sample_size
          FROM metric_delta AS metric
    ), metric_aggregate AS (
        SELECT metric.period_key,
               metric.window_index,
               metric.platform,
               metric.entity_id,
               metric.metric_key,
               sum(metric.delta_value) AS total_value,
               floor(avg(metric.delta_value) FILTER (
                   WHERE metric.rank_position IN (
                       (metric.sample_size + 1) / 2,
                       (metric.sample_size + 2) / 2
                   )
               ) + 0.5) AS median_value
          FROM ranked_metric AS metric
         GROUP BY metric.period_key, metric.window_index,
                  metric.platform, metric.entity_id, metric.metric_key
    ), metric_pivot AS (
        SELECT metric.period_key,
               metric.platform,
               metric.entity_id,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'views'
               ) AS total_views,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'views'
               ) AS median_views,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'views'
               ) AS previous_total_views,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'views'
               ) AS previous_median_views,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'reactions'
               ) AS total_reactions,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'reactions'
               ) AS median_reactions,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'reactions'
               ) AS previous_total_reactions,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'reactions'
               ) AS previous_median_reactions,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'comments'
               ) AS total_comments,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'comments'
               ) AS median_comments,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'comments'
               ) AS previous_total_comments,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'comments'
               ) AS previous_median_comments,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'shares'
               ) AS total_shares,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 0 AND metric.metric_key = 'shares'
               ) AS median_shares,
               max(metric.total_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'shares'
               ) AS previous_total_shares,
               max(metric.median_value) FILTER (
                   WHERE metric.window_index = 1 AND metric.metric_key = 'shares'
               ) AS previous_median_shares
          FROM metric_aggregate AS metric
         GROUP BY metric.period_key, metric.platform, metric.entity_id
    ), publication_count AS (
        SELECT period.period_key,
               publication.platform,
               publication.entity_id,
               count(*)::bigint AS total_count,
               count(*) FILTER (
                   WHERE publication.published_at >= revision_as_of - period.duration
                     AND publication.published_at <= revision_as_of
               )::bigint AS new_count
          FROM periods AS period
          JOIN activity_publications AS publication ON true
         GROUP BY period.period_key, publication.platform, publication.entity_id
    ), account_summary AS (
        SELECT account.platform,
               account.entity_id,
               count(*)::integer AS account_count,
               count(*) FILTER (WHERE account.enabled)::integer AS enabled_account_count,
               count(DISTINCT account.account_platform)
                   FILTER (WHERE account.enabled)::integer AS connected_platform_count,
               sum(account.subscriber_count) AS subscriber_count,
               max(account.last_checked_at) AS last_checked_at,
               min(account.latest_error_code)
                   FILTER (WHERE account.latest_error_code IS NOT NULL) AS last_error_code
          FROM analytics.legacy_overview_account AS account
         WHERE account.dataset_revision_id = p_dataset_revision_id
         GROUP BY account.platform, account.entity_id
    ), latest_rating AS (
        SELECT DISTINCT ON (observation.institution_id, observation.category)
               observation.institution_id,
               observation.category,
               observation.rank,
               observation.score,
               observation.period,
               observation.fetched_at
          FROM rating.official_rating_observation AS observation
         WHERE observation.fetched_at <= revision_as_of
           AND observation.category IN ('social', 'telegram', 'vk', 'max', 'rutube')
         ORDER BY observation.institution_id, observation.category,
                  observation.fetched_at DESC, observation.id DESC
    ), card_source AS (
        SELECT dimension.platform,
               period.period_key,
               dimension.entity_type,
               dimension.entity_id,
               dimension.legacy_id,
               dimension.legacy_route,
               institution.id AS institution_id,
               institution_alias.legacy_id AS institution_legacy_id,
               institution.canonical_name,
               institution.short_name,
               btrim(regexp_replace(replace(lower(coalesce(
                   nullif(institution.short_name, ''),
                   nullif(institution.canonical_name, ''),
                   telegram_account.current_title,
                   telegram_account.current_username,
                   ''
               )), 'ё', 'е'), '[[:space:]]+', ' ', 'g')) AS sort_name,
               btrim(regexp_replace(replace(lower(concat_ws(' ',
                   institution.short_name,
                   institution.canonical_name,
                   telegram_account.current_title
               )), 'ё', 'е'), '[[:space:]]+', ' ', 'g')) AS search_text,
               coalesce(account.account_count, 0) AS account_count,
               coalesce(account.enabled_account_count, 0) AS enabled_account_count,
               coalesce(account.connected_platform_count, 0) AS connected_platform_count,
               account.subscriber_count,
               account.last_checked_at,
               account.last_error_code,
               CASE
                   WHEN coalesce(account.account_count, 0) = 0 THEN 'no_account'
                   WHEN coalesce(account.enabled_account_count, 0) = 0
                       THEN 'all_accounts_disabled'
                   WHEN account.last_error_code IS NOT NULL THEN 'last_poll_failed'
                   WHEN dimension.platform = 'all' THEN 'connected'
                   WHEN account.last_checked_at IS NOT NULL THEN 'polling'
                   ELSE 'awaiting_first_poll'
               END AS status_code,
               rating.rank AS rating_rank,
               rating.score AS rating_score,
               rating.period AS rating_period,
               rating.fetched_at AS rating_fetched_at,
               CASE WHEN dimension.platform = 'all' THEN NULL
                    ELSE coalesce(publication.total_count, 0) END
                   AS total_publication_count,
               CASE WHEN dimension.platform = 'all' THEN NULL
                    ELSE coalesce(activity.publication_count, 0) END
                   AS activity_publication_count,
               CASE WHEN dimension.platform = 'all' THEN NULL
                    ELSE coalesce(publication.new_count, 0) END
                   AS new_publication_count,
               metric.total_views,
               metric.median_views,
               metric.previous_total_views,
               metric.previous_median_views,
               metric.total_reactions,
               metric.median_reactions,
               metric.previous_total_reactions,
               metric.previous_median_reactions,
               metric.total_comments,
               metric.median_comments,
               metric.previous_total_comments,
               metric.previous_median_comments,
               metric.total_shares,
               metric.median_shares,
               metric.previous_total_shares,
               metric.previous_median_shares,
               revision_as_of AS as_of
          FROM dimensions AS dimension
         CROSS JOIN periods AS period
          JOIN catalog.institution AS institution
            ON institution.id = dimension.institution_id
          JOIN catalog.legacy_entity_alias AS institution_alias
            ON institution_alias.target_uuid = institution.id
           AND institution_alias.entity_type = 'institutions'
          LEFT JOIN analytics.legacy_overview_account AS telegram_account_row
            ON dimension.platform = 'telegram'
           AND telegram_account_row.dataset_revision_id = p_dataset_revision_id
           AND telegram_account_row.platform = dimension.platform
           AND telegram_account_row.entity_id = dimension.entity_id
           AND telegram_account_row.position = 1
          LEFT JOIN catalog.platform_account AS telegram_account
            ON telegram_account.id = telegram_account_row.account_id
          LEFT JOIN account_summary AS account
            ON account.platform = dimension.platform
           AND account.entity_id = dimension.entity_id
          LEFT JOIN publication_count AS publication
            ON publication.period_key = period.period_key
           AND publication.platform = dimension.platform
           AND publication.entity_id = dimension.entity_id
          LEFT JOIN activity_count AS activity
            ON activity.period_key = period.period_key
           AND activity.window_index = 0
           AND activity.platform = dimension.platform
           AND activity.entity_id = dimension.entity_id
          LEFT JOIN metric_pivot AS metric
            ON metric.period_key = period.period_key
           AND metric.platform = dimension.platform
           AND metric.entity_id = dimension.entity_id
          LEFT JOIN latest_rating AS rating
            ON rating.institution_id = dimension.institution_id
           AND rating.category = CASE dimension.platform::text
               WHEN 'all' THEN 'social'
               ELSE dimension.platform::text
           END
    )
    INSERT INTO analytics.legacy_overview_card (
        dataset_revision_id, platform, period_key, entity_type, entity_id,
        legacy_id, legacy_route, institution_id, institution_legacy_id,
        canonical_name, short_name, sort_name, search_text,
        account_count, enabled_account_count, connected_platform_count,
        subscriber_count, last_checked_at, last_error_code, status_code,
        rating_rank, rating_score, rating_period, rating_fetched_at,
        total_publication_count, activity_publication_count, new_publication_count,
        total_views, median_views, previous_total_views, previous_median_views,
        delta_total_views, delta_median_views,
        total_reactions, median_reactions,
        previous_total_reactions, previous_median_reactions,
        delta_total_reactions, delta_median_reactions,
        total_comments, median_comments, previous_total_comments,
        previous_median_comments, delta_total_comments, delta_median_comments,
        total_shares, median_shares, previous_total_shares,
        previous_median_shares, delta_total_shares, delta_median_shares,
        as_of, refreshed_at
    )
    SELECT p_dataset_revision_id,
           card.platform,
           card.period_key,
           card.entity_type,
           card.entity_id,
           card.legacy_id,
           card.legacy_route,
           card.institution_id,
           card.institution_legacy_id,
           card.canonical_name,
           card.short_name,
           card.sort_name,
           card.search_text,
           card.account_count,
           card.enabled_account_count,
           card.connected_platform_count,
           card.subscriber_count,
           card.last_checked_at,
           card.last_error_code,
           card.status_code,
           card.rating_rank,
           card.rating_score,
           card.rating_period,
           card.rating_fetched_at,
           card.total_publication_count,
           card.activity_publication_count,
           card.new_publication_count,
           card.total_views,
           card.median_views,
           card.previous_total_views,
           card.previous_median_views,
           CASE WHEN card.total_views IS NOT NULL
                  AND card.previous_total_views IS NOT NULL
                THEN card.total_views - card.previous_total_views END,
           CASE WHEN card.median_views IS NOT NULL
                  AND card.previous_median_views IS NOT NULL
                THEN card.median_views - card.previous_median_views END,
           card.total_reactions,
           card.median_reactions,
           card.previous_total_reactions,
           card.previous_median_reactions,
           CASE WHEN card.total_reactions IS NOT NULL
                  AND card.previous_total_reactions IS NOT NULL
                THEN card.total_reactions - card.previous_total_reactions END,
           CASE WHEN card.median_reactions IS NOT NULL
                  AND card.previous_median_reactions IS NOT NULL
                THEN card.median_reactions - card.previous_median_reactions END,
           card.total_comments,
           card.median_comments,
           card.previous_total_comments,
           card.previous_median_comments,
           CASE WHEN card.total_comments IS NOT NULL
                  AND card.previous_total_comments IS NOT NULL
                THEN card.total_comments - card.previous_total_comments END,
           CASE WHEN card.median_comments IS NOT NULL
                  AND card.previous_median_comments IS NOT NULL
                THEN card.median_comments - card.previous_median_comments END,
           card.total_shares,
           card.median_shares,
           card.previous_total_shares,
           card.previous_median_shares,
           CASE WHEN card.total_shares IS NOT NULL
                  AND card.previous_total_shares IS NOT NULL
                THEN card.total_shares - card.previous_total_shares END,
           CASE WHEN card.median_shares IS NOT NULL
                  AND card.previous_median_shares IS NOT NULL
                THEN card.median_shares - card.previous_median_shares END,
           card.as_of,
           transaction_timestamp()
      FROM card_source AS card;

    GET DIAGNOSTICS overview_card_rows = ROW_COUNT;

    RETURN base_result || jsonb_build_object(
        'legacy_overview_accounts', overview_account_rows,
        'legacy_overview_cards', overview_card_rows,
        'legacy_overview_semantics_version', 1
    );
END
$function$;

-- The canonical record covers every immutable snapshot column, per-metric
-- evidence, reaction key/value, and the public catalog dimensions exported.
CREATE FUNCTION ops_and_admin.publication_archive_record(p_month date,p_id bigint)
RETURNS text LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,ingest,catalog SET TimeZone='UTC' AS $f$
 SELECT (to_jsonb(s) || jsonb_build_object(
   'primary_account_id',p.primary_account_id,'platform',a.platform,
   'published_at',p.published_at,
   'reaction_breakdown',coalesce((SELECT jsonb_object_agg(r.reaction_key,r.reaction_count ORDER BY r.reaction_key)
     FROM ingest.reaction_breakdown r WHERE r.snapshot_published_month=s.published_month AND r.snapshot_id=s.id),'{}'::jsonb)))::text
 FROM ingest.publication_metric_snapshot s
 JOIN ingest.publication p ON p.id=s.publication_id
 JOIN catalog.platform_account a ON a.id=p.primary_account_id
 WHERE s.published_month=p_month AND s.id=p_id
$f$;
CREATE FUNCTION ops_and_admin.publication_partition_digest(p_month date)
RETURNS TABLE(row_count bigint,min_observed_at timestamptz,max_observed_at timestamptz,canonical_sha256 text)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path=pg_catalog,ingest,ops_and_admin SET TimeZone='UTC' AS $f$
DECLARE item record; chain bytea:=sha256(''::bytea);
BEGIN
 row_count:=0;
 FOR item IN SELECT id,observed_at FROM ingest.publication_metric_snapshot WHERE published_month=p_month ORDER BY id LOOP
   chain:=sha256(chain||sha256(convert_to(ops_and_admin.publication_archive_record(p_month,item.id),'UTF8')));
   row_count:=row_count+1;
   min_observed_at:=least(min_observed_at,item.observed_at);
   max_observed_at:=greatest(max_observed_at,item.observed_at);
 END LOOP;
 canonical_sha256:=encode(chain,'hex');
 RETURN NEXT;
END $f$;
CREATE FUNCTION ops_and_admin.begin_publication_archive(p_month date)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ops_and_admin AS $f$
DECLARE current_state text;
BEGIN
 IF p_month IS NULL OR p_month<>date_trunc('month',p_month)::date THEN RAISE EXCEPTION 'canonical month required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT state INTO current_state FROM ops_and_admin.publication_partition_fence WHERE published_month=p_month;
 IF current_state='archived' THEN RAISE EXCEPTION 'partition already archived' USING ERRCODE='55000'; END IF;
 INSERT INTO ops_and_admin.publication_partition_fence(published_month,state)
 VALUES(p_month,'archiving') ON CONFLICT(published_month) DO UPDATE SET state='archiving',changed_at=transaction_timestamp();
END $f$;
-- Aborting/retrying is an explicit maintenance operation; an exported object
-- never authorizes deletion after the range has been reopened for writes.
CREATE FUNCTION ops_and_admin.abort_publication_archive(p_month date)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ops_and_admin AS $f$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 UPDATE ops_and_admin.publication_partition_fence SET state='active',manifest_id=NULL,changed_at=transaction_timestamp()
 WHERE published_month=p_month AND state='archiving';
END $f$;
ALTER TABLE ops_and_admin.archive_manifest ADD COLUMN canonical_sha256 text CHECK(canonical_sha256 ~ '^[0-9a-f]{64}$');
-- A different administrative trust boundary verifies remote object version,
-- retention lock and full readback. Maintenance cannot self-attest its spool.
CREATE TABLE ops_and_admin.archive_object_attestation (
 manifest_id uuid PRIMARY KEY REFERENCES ops_and_admin.archive_manifest(id),
 object_uri text NOT NULL CHECK(object_uri ~ '^(s3|gs|https)://'),
 object_version text NOT NULL CHECK(btrim(object_version)<>''),
 sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 canonical_sha256 text NOT NULL CHECK(canonical_sha256 ~ '^[0-9a-f]{64}$'),
 row_count bigint NOT NULL CHECK(row_count>=0),
 failure_domain text NOT NULL CHECK(btrim(failure_domain)<>'' AND failure_domain<>'primary'),
 immutable_until timestamptz NOT NULL,
 verified_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
 verifier_subject text NOT NULL CHECK(btrim(verifier_subject)<>''),
 CHECK(immutable_until>verified_at)
);
CREATE TRIGGER attestation_immutable BEFORE UPDATE OR DELETE ON ops_and_admin.archive_object_attestation
 FOR EACH ROW EXECUTE FUNCTION ingest.reject_observation_mutation();
CREATE OR REPLACE FUNCTION ops_and_admin.drop_publication_metric_partition(p_month date,p_manifest_id uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,ingest,ops_and_admin SET lock_timeout='10s' SET TimeZone='UTC' AS $f$
DECLARE month_end date:=(p_month+interval '1 month')::date;
 manifest ops_and_admin.archive_manifest%ROWTYPE; attestation ops_and_admin.archive_object_attestation%ROWTYPE;
 actual record; hot_days integer; fence text;
BEGIN
 IF p_month IS NULL OR p_month<>date_trunc('month',p_month)::date THEN RAISE EXCEPTION 'canonical month required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT state INTO fence FROM ops_and_admin.publication_partition_fence WHERE published_month=p_month FOR UPDATE;
 IF fence IS DISTINCT FROM 'archiving' THEN RAISE EXCEPTION 'archive fence required' USING ERRCODE='55000'; END IF;
 SELECT * INTO manifest FROM ops_and_admin.archive_manifest WHERE id=p_manifest_id FOR UPDATE;
 SELECT * INTO attestation FROM ops_and_admin.archive_object_attestation WHERE manifest_id=p_manifest_id;
 SELECT rp.hot_days INTO hot_days FROM ops_and_admin.retention_policy rp WHERE rp.data_class='publication_metric_snapshot';
 IF hot_days IS NULL OR hot_days<70 OR current_date<month_end+hot_days THEN RAISE EXCEPTION 'hot retention gate failed'; END IF;
 IF manifest.id IS NULL OR manifest.dataset_type<>'publication_metric_snapshot' OR manifest.schema_version<>3
 OR manifest.partition_start IS DISTINCT FROM p_month::timestamp AT TIME ZONE 'UTC'
 OR manifest.partition_end IS DISTINCT FROM month_end::timestamp AT TIME ZONE 'UTC'
 OR manifest.status<>'verified' OR manifest.verified_at IS NULL OR manifest.canonical_sha256 IS NULL THEN
 RAISE EXCEPTION 'exact verified v3 manifest required'; END IF;
 IF attestation.manifest_id IS NULL OR attestation.sha256<>manifest.sha256
 OR attestation.canonical_sha256<>manifest.canonical_sha256 OR attestation.row_count<>manifest.row_count
 OR attestation.immutable_until<=transaction_timestamp() THEN RAISE EXCEPTION 'off-primary immutable object attestation required'; END IF;
 -- Exclusive relation locks also drain elevated direct writers and hold the
 -- catalog dimensions fixed through digest and DROP in this same transaction.
 LOCK TABLE ingest.publication_metric_snapshot,ingest.reaction_breakdown IN ACCESS EXCLUSIVE MODE;
 LOCK TABLE ingest.publication,catalog.platform_account IN SHARE MODE;
 SELECT * INTO actual FROM ops_and_admin.publication_partition_digest(p_month);
 IF ROW(actual.row_count,actual.min_observed_at,actual.max_observed_at,actual.canonical_sha256)
 IS DISTINCT FROM ROW(manifest.row_count,manifest.min_observed_at,manifest.max_observed_at,manifest.canonical_sha256)
 THEN RAISE EXCEPTION 'partition content changed since verified export'; END IF;
 EXECUTE format('DROP TABLE ingest.%I','reaction_breakdown_'||to_char(p_month,'YYYY_MM'));
 EXECUTE format('ALTER TABLE ingest.publication_metric_snapshot DETACH PARTITION ingest.%I','publication_metric_snapshot_'||to_char(p_month,'YYYY_MM'));
 EXECUTE format('DROP TABLE ingest.%I','publication_metric_snapshot_'||to_char(p_month,'YYYY_MM'));
 UPDATE ops_and_admin.archive_manifest SET status='hot_dropped',hot_dropped_at=transaction_timestamp() WHERE id=p_manifest_id;
 UPDATE ops_and_admin.publication_partition_fence SET state='archived',manifest_id=p_manifest_id,changed_at=transaction_timestamp() WHERE published_month=p_month;
END $f$;
REVOKE ALL ON FUNCTION ops_and_admin.publication_archive_record(date,bigint),
 ops_and_admin.publication_partition_digest(date),ops_and_admin.begin_publication_archive(date),
 ops_and_admin.abort_publication_archive(date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.publication_archive_record(date,bigint),
 ops_and_admin.publication_partition_digest(date),ops_and_admin.begin_publication_archive(date),
 ops_and_admin.abort_publication_archive(date) TO maintenance;
GRANT SELECT ON ops_and_admin.publication_partition_fence,ops_and_admin.archive_object_attestation TO maintenance;
-- V1 hash-only placeholders remain visible as explicitly unavailable legacy
-- evidence; new payloads require a retrievable immutable object or encryption.
ALTER TABLE ingest.raw_payload ADD COLUMN legacy_evidence_unavailable boolean NOT NULL DEFAULT false;
UPDATE ingest.raw_payload SET legacy_evidence_unavailable=true WHERE payload IS NULL AND external_ref !~ '^(file|s3|gs|https)://';
ALTER TABLE ingest.raw_payload ADD CONSTRAINT raw_payload_retrievable
 CHECK(legacy_evidence_unavailable OR payload IS NOT NULL OR external_ref ~ '^(file|s3|gs|https)://');
CREATE FUNCTION ingest.reject_new_unavailable_evidence() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
 IF NEW.legacy_evidence_unavailable THEN RAISE EXCEPTION 'new evidence must be retrievable' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $f$;
CREATE TRIGGER raw_payload_available BEFORE INSERT ON ingest.raw_payload FOR EACH ROW EXECUTE FUNCTION ingest.reject_new_unavailable_evidence();
REVOKE ALL ON FUNCTION ingest.reject_new_unavailable_evidence() FROM PUBLIC;
CREATE TABLE ingest.evidence_quarantine (
 raw_payload_id uuid PRIMARY KEY REFERENCES ingest.raw_payload(id) ON DELETE CASCADE,
 reason_code text NOT NULL CHECK(reason_code ~ '^[A-Za-z][A-Za-z0-9_.:-]{0,159}$'),
 quarantined_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
GRANT SELECT,INSERT ON ingest.evidence_quarantine TO collector_ingest;
GRANT SELECT ON ingest.evidence_quarantine TO maintenance,migration_bridge;
GRANT SELECT ON ingest.raw_payload TO maintenance;
CREATE FUNCTION ops_and_admin.purge_raw_evidence_reference(p_uri text,p_now timestamptz)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,ingest AS $f$
DECLARE removed bigint;
BEGIN
 DELETE FROM ingest.raw_payload WHERE external_ref=p_uri AND purge_after<=p_now;
 GET DIAGNOSTICS removed=ROW_COUNT;
 RETURN removed;
END $f$;
REVOKE ALL ON FUNCTION ops_and_admin.purge_raw_evidence_reference(text,timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.purge_raw_evidence_reference(text,timestamptz) TO maintenance;
RESET ROLE;
