-- Compact account reference from complete opt-in poll receipts.
-- No change-only snapshots are eligible for this table.
BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE TABLE analytics.bounded_poll_growth_daily (
    publication_id uuid NOT NULL REFERENCES ingest.publication(id) ON DELETE CASCADE,
    account_id uuid NOT NULL REFERENCES catalog.platform_account(id),
    platform text NOT NULL CHECK (platform IN ('telegram', 'max', 'vk', 'rutube')),
    observed_day date NOT NULL,
    age_band text NOT NULL CHECK (age_band IN
        ('0-6h', '6-24h', '1-2d', '2-4d', '4-7d', '7d+')),
    exposure_band text NOT NULL CHECK (exposure_band IN
        ('<=30m', '30m-2h', '2-8h', '8h+')),
    upper_rate_per_hour numeric(30, 6) NOT NULL
        CHECK (upper_rate_per_hour >= 0),
    method_version text NOT NULL DEFAULT 'bounded-v1-10m'
        CHECK (method_version = 'bounded-v1-10m'),
    source text NOT NULL DEFAULT 'successful_poll_receipts'
        CHECK (source = 'successful_poll_receipts'),
    updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY (publication_id, observed_day, age_band, exposure_band)
);

CREATE INDEX bounded_poll_growth_daily_reference_idx
    ON analytics.bounded_poll_growth_daily
    (platform, account_id, age_band, exposure_band, observed_day);
CREATE INDEX bounded_poll_growth_daily_retention_idx
    ON analytics.bounded_poll_growth_daily (observed_day);

GRANT SELECT, INSERT, UPDATE, DELETE ON analytics.bounded_poll_growth_daily
    TO analytics_worker;

COMMENT ON TABLE analytics.bounded_poll_growth_daily IS
    '120-day bounded upper growth reference from actual successful opt-in poll receipts';

COMMIT;
