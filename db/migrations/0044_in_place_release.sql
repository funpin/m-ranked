-- One in-place release migration from the current main schema.
-- Creates only empty tables, indexes on those new tables, grants and constraints.
-- No existing data is copied, rewritten or backfilled in this transaction.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

-- Former 0044_site_summary.sql
-- 0044 — сводка для главной страницы: вузы, аккаунты, публикации, замеры
--
-- Главная показывает живые, но не мгновенные цифры. Точный подсчёт замеров —
-- несколько секунд базы по миллионам строк, поэтому он делается раз в сутки
-- шагом планового обслуживания (db/tools/refresh-site-summary.sql), а API
-- читает одну готовую строку. Площадки считаются из данных: новая площадка
-- появится в сводке без правки схемы.
CREATE TABLE IF NOT EXISTS analytics.site_summary (
    id smallint DEFAULT 1 NOT NULL,
    institutions integer NOT NULL,
    accounts integer NOT NULL,
    accounts_by_platform jsonb NOT NULL,
    publications bigint NOT NULL,
    snapshots bigint NOT NULL,
    computed_at timestamp with time zone DEFAULT transaction_timestamp() NOT NULL,
    CONSTRAINT site_summary_pkey PRIMARY KEY (id),
    CONSTRAINT site_summary_single_row CHECK (id = 1),
    CONSTRAINT site_summary_counts_check CHECK (institutions >= 0 AND accounts >= 0 AND publications >= 0 AND snapshots >= 0)
);

COMMENT ON TABLE analytics.site_summary IS 'Одна строка: цифры главной страницы, пересчёт раз в сутки шагом обслуживания.';

GRANT SELECT ON TABLE analytics.site_summary TO api_read;
GRANT SELECT, INSERT, UPDATE ON TABLE analytics.site_summary TO maintenance;

-- Former 0045_bounded_publication_poll_receipts.sql
-- Successful per-post reads for a small opt-in cohort. Not a general log.
-- This table starts empty: change-only history cannot be backfilled into reads.

CREATE TABLE ingest.publication_poll_receipt (
    publication_id uuid NOT NULL REFERENCES ingest.publication(id) ON DELETE CASCADE,
    cadence_seconds integer NOT NULL,
    observed_bucket bigint NOT NULL,
    observed_at timestamptz NOT NULL,
    collection_run_id uuid NOT NULL REFERENCES ingest.collection_run(id) ON DELETE CASCADE,
    views_count bigint,
    reactions_count bigint,
    comments_count bigint,
    shares_count bigint,
    views_quality ingest.observation_quality NOT NULL,
    reactions_quality ingest.observation_quality NOT NULL,
    comments_quality ingest.observation_quality NOT NULL,
    shares_quality ingest.observation_quality NOT NULL,
    interval_uncertain boolean NOT NULL,
    snapshot_written boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CONSTRAINT publication_poll_receipt_pkey
        PRIMARY KEY (publication_id, cadence_seconds, observed_bucket),
    CONSTRAINT publication_poll_receipt_cadence_check
        CHECK (cadence_seconds BETWEEN 300 AND 3600),
    CONSTRAINT publication_poll_receipt_bucket_check
        CHECK (observed_bucket >= 0),
    CONSTRAINT publication_poll_receipt_views_check
        CHECK (views_count IS NULL OR views_count >= 0),
    CONSTRAINT publication_poll_receipt_reactions_check
        CHECK (reactions_count IS NULL OR reactions_count >= 0),
    CONSTRAINT publication_poll_receipt_comments_check
        CHECK (comments_count IS NULL OR comments_count >= 0),
    CONSTRAINT publication_poll_receipt_shares_check
        CHECK (shares_count IS NULL OR shares_count >= 0)
);

CREATE INDEX publication_poll_receipt_observed_idx
    ON ingest.publication_poll_receipt (observed_at);

GRANT SELECT, INSERT, DELETE ON ingest.publication_poll_receipt TO collector_ingest;
GRANT SELECT ON ingest.publication_poll_receipt TO analytics_worker;

COMMENT ON TABLE ingest.publication_poll_receipt IS
    'Short-lived successful post reads in a bounded opt-in cohort; absence outside the cohort is unknown, not zero';

-- Former 0046_anomaly_context_recheck.sql
-- A bounded, versioned recheck may cap an already saved v2 level. The raw
-- detector state remains untouched; an overlay applies only to the exact
-- analysis timestamp and raw level it reviewed. This prevents stale evidence
-- from surviving a later worker recalculation.
CREATE TABLE analytics.post_anomaly_context_recheck (
    publication_id uuid PRIMARY KEY REFERENCES ingest.publication(id) ON DELETE CASCADE,
    source_analyzed_at timestamptz NOT NULL,
    source_level smallint NOT NULL,
    effective_level smallint NOT NULL,
    method_version text NOT NULL,
    reason text NOT NULL,
    evidence jsonb NOT NULL,
    reviewed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    CONSTRAINT post_anomaly_context_recheck_levels CHECK (
        source_level BETWEEN 1 AND 3 AND effective_level BETWEEN 1 AND source_level
    ),
    CONSTRAINT post_anomaly_context_recheck_evidence CHECK (
        jsonb_typeof(evidence) = 'object' AND pg_column_size(evidence) <= 8192
    ),
    CONSTRAINT post_anomaly_context_recheck_method CHECK (
        btrim(method_version) <> '' AND btrim(reason) <> ''
    )
);

REVOKE ALL ON analytics.post_anomaly_context_recheck FROM PUBLIC;
GRANT SELECT ON analytics.post_anomaly_context_recheck TO api_read;
GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.post_anomaly_context_recheck TO analytics_worker;

COMMENT ON TABLE analytics.post_anomaly_context_recheck IS
  'Versioned conservative cap on a saved v2 level. Raw state remains available; stale rechecks are ignored.';

-- Former 0047_telegram_rounded_view_precision.sql
-- Preserve the display unit of rounded Telegram views on bounded poll receipts.
-- Existing receipts lack this information and remain unknown (NULL).

ALTER TABLE ingest.publication_poll_receipt
    ADD COLUMN views_display_unit integer;

ALTER TABLE ingest.publication_poll_receipt
    ADD CONSTRAINT publication_poll_receipt_views_display_unit_ck
    CHECK (views_display_unit IS NULL OR (
        views_quality = 'rounded'::ingest.observation_quality
        AND views_count IS NOT NULL
        AND views_display_unit IN (
            1, 10, 100, 1000, 10000, 100000, 1000000,
            10000000, 100000000, 1000000000
        )
    )) NOT VALID;

COMMENT ON COLUMN ingest.publication_poll_receipt.views_display_unit IS
    'Unit of the last visible digit; NULL when the rounded display precision was not retained';

-- Former 0048_bounded_poll_growth_daily.sql
-- Compact account reference from complete opt-in poll receipts.
-- No change-only snapshots are eligible for this table.

CREATE TABLE analytics.bounded_poll_growth_daily (
    publication_id uuid NOT NULL REFERENCES ingest.publication(id) ON DELETE CASCADE,
    account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    platform text NOT NULL CHECK (platform IN ('telegram', 'max', 'vk', 'rutube')),
    observed_day date NOT NULL,
    age_band text NOT NULL CHECK (age_band IN
        ('0-6h', '6-24h', '1-2d', '2-4d', '4-7d', '7d+')),
    exposure_band text NOT NULL CHECK (exposure_band IN
        ('<=30m', '30m-2h', '2-8h', '8h+')),
    max_gap_seconds integer NOT NULL
        CHECK (max_gap_seconds BETWEEN 300 AND 86400),
    upper_rate_per_hour numeric(30, 6) NOT NULL
        CHECK (upper_rate_per_hour >= 0),
    method_version text NOT NULL DEFAULT 'bounded-v1-10m'
        CHECK (method_version = 'bounded-v1-10m'),
    source text NOT NULL DEFAULT 'successful_poll_receipts'
        CHECK (source = 'successful_poll_receipts'),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (publication_id, observed_day, age_band, exposure_band,
                 max_gap_seconds)
);

CREATE INDEX bounded_poll_growth_daily_reference_idx
    ON analytics.bounded_poll_growth_daily
    (platform, account_id, max_gap_seconds, age_band, exposure_band, observed_day);
CREATE INDEX bounded_poll_growth_daily_retention_idx
    ON analytics.bounded_poll_growth_daily (observed_day);

GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.bounded_poll_growth_daily
    TO analytics_worker;
GRANT SELECT ON ingest.visible_publication, catalog.visible_platform_account
    TO analytics_worker;

COMMENT ON TABLE analytics.bounded_poll_growth_daily IS
    '120-day bounded upper growth reference from actual successful opt-in poll receipts';

COMMIT;
