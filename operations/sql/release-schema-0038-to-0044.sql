-- One in-place transaction for the known 0038, 0043, site-summary-only or 0044–0046 schemas.
-- Run with psql -v ON_ERROR_STOP=1 -f this-file. No old table is copied.
-- Check the actual production schema and disk/backup state before running.
-- The 0044 script closes this transaction when its objects are absent.
\set ON_ERROR_STOP 1
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '2min';

-- Refuse unknown partial states rather than guessing which DDL is safe.
DO $$
DECLARE
    new_tables integer;
BEGIN
    SELECT (to_regclass('analytics.site_summary') IS NOT NULL)::integer
         + (to_regclass('ingest.publication_poll_receipt') IS NOT NULL)::integer
         + (to_regclass('analytics.post_anomaly_context_recheck') IS NOT NULL)::integer
         + (to_regclass('analytics.bounded_poll_growth_daily') IS NOT NULL)::integer
      INTO new_tables;
    IF new_tables = 3 AND NOT (
        to_regclass('analytics.site_summary') IS NOT NULL
        AND to_regclass('ingest.publication_poll_receipt') IS NOT NULL
        AND to_regclass('analytics.post_anomaly_context_recheck') IS NOT NULL
        AND to_regclass('analytics.bounded_poll_growth_daily') IS NULL
    ) THEN
        RAISE EXCEPTION 'unexpected partial 0044 schema: inspect it before release';
    END IF;
    IF new_tables = 1 AND NOT (
        to_regclass('analytics.site_summary') IS NOT NULL
        AND to_regclass('ingest.publication_poll_receipt') IS NULL
        AND to_regclass('analytics.post_anomaly_context_recheck') IS NULL
        AND to_regclass('analytics.bounded_poll_growth_daily') IS NULL
        AND (SELECT count(*) FROM pg_attribute
             WHERE attrelid = to_regclass('analytics.site_summary')
               AND attnum > 0 AND NOT attisdropped) = 7
        AND (SELECT count(*) FROM pg_constraint
             WHERE conrelid = to_regclass('analytics.site_summary')
               AND conname IN ('site_summary_pkey', 'site_summary_single_row',
                               'site_summary_counts_check')) = 3
        AND has_table_privilege('api_read', to_regclass('analytics.site_summary'), 'SELECT')
        AND has_table_privilege('maintenance', to_regclass('analytics.site_summary'), 'SELECT')
        AND has_table_privilege('maintenance', to_regclass('analytics.site_summary'), 'INSERT')
        AND has_table_privilege('maintenance', to_regclass('analytics.site_summary'), 'UPDATE')
    ) THEN
        RAISE EXCEPTION 'unknown site-summary-only schema: inspect it before release';
    END IF;
    IF new_tables NOT IN (0, 1, 3, 4) THEN
        RAISE EXCEPTION 'partial 0044 schema: inspect it before release';
    END IF;
    IF to_regclass('analytics.publication_history_page') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_index WHERE indexrelid =
               to_regclass('analytics.publication_history_page_computed_idx') AND indisvalid
       ) THEN
        RAISE EXCEPTION 'partial 0043 schema: history-page index is missing or invalid';
    END IF;
    IF new_tables IN (3, 4) AND NOT EXISTS (
        SELECT 1 FROM pg_index WHERE indexrelid =
            to_regclass('ingest.publication_poll_receipt_observed_idx') AND indisvalid
    ) THEN
        RAISE EXCEPTION 'partial 0044 schema: receipt index is missing or invalid';
    END IF;
    IF new_tables = 4 AND NOT EXISTS (
        SELECT 1 FROM pg_attribute
         WHERE attrelid = to_regclass('ingest.publication_poll_receipt')
           AND attname = 'views_display_unit' AND NOT attisdropped
    ) THEN
        RAISE EXCEPTION 'partial 0044 schema: receipt display precision is missing';
    END IF;
    IF new_tables = 4 AND (
        NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conrelid =
                to_regclass('ingest.publication_poll_receipt')
              AND conname = 'publication_poll_receipt_views_display_unit_ck'
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_index WHERE indexrelid =
                to_regclass('analytics.bounded_poll_growth_daily_reference_idx') AND indisvalid
        ) OR NOT EXISTS (
            SELECT 1 FROM pg_index WHERE indexrelid =
                to_regclass('analytics.bounded_poll_growth_daily_retention_idx') AND indisvalid
        )
    ) THEN
        RAISE EXCEPTION 'partial 0044 schema: bounded growth constraints or indexes are missing';
    END IF;
END $$;

-- The two bounded purge functions are safe to replace. Both stay disabled
-- until their separately measured indexes and operating budget are approved.
\ir ../../db/migrations/0040_bounded_cache_outbox_purge.sql
\ir ../../db/migrations/0042_dataset_revision_retention.sql

SELECT to_regclass('analytics.publication_history_page') IS NULL AS install_history \gset
\if :install_history
\ir ../../db/migrations/0043_publication_history_page.sql
\endif

SELECT to_regclass('ingest.publication_poll_receipt') IS NULL AS install_0044 \gset
\if :install_0044
-- 0044 contains BEGIN (harmless nested-BEGIN warning) and the final COMMIT.
\ir ../../db/migrations/0044_in_place_release.sql
\else
SELECT to_regclass('analytics.bounded_poll_growth_daily') IS NULL AS complete_0044 \gset
\if :complete_0044
-- Complete the previously shipped 0044–0046 state. Adding a nullable column
-- to the small receipt table is metadata-only; there is no data backfill.
ALTER TABLE ingest.publication_poll_receipt ADD COLUMN IF NOT EXISTS views_display_unit integer;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'ingest.publication_poll_receipt'::regclass
          AND conname = 'publication_poll_receipt_views_display_unit_ck'
    ) THEN
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
    END IF;
END $$;
COMMENT ON COLUMN ingest.publication_poll_receipt.views_display_unit IS
    'Unit of the last visible digit; NULL when the rounded display precision was not retained';

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
\endif
COMMIT;
\endif
