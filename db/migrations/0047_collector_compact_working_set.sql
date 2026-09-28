-- Collector-only scheduling state. Full canonical batches still travel in the
-- transactional transfer outbox; the serving database keeps immutable history.
-- This migration creates empty tables and never removes existing observations.
CREATE TABLE ingest.collector_publication_working_set (
    id bigint GENERATED ALWAYS AS IDENTITY,
    publication_id uuid NOT NULL REFERENCES ingest.publication(id),
    published_month date NOT NULL,
    sampling_bucket bigint NOT NULL,
    observed_at timestamptz NOT NULL,
    collected_at timestamptz NOT NULL,
    synthetic boolean NOT NULL,
    views_count bigint,
    reactions_count bigint,
    comments_count bigint,
    shares_count bigint,
    source_fingerprint text NOT NULL,
    semantic_fingerprint bytea,
    PRIMARY KEY (publication_id, sampling_bucket),
    CHECK (collected_at >= observed_at),
    CHECK (semantic_fingerprint IS NULL OR octet_length(semantic_fingerprint)=32),
    CHECK (views_count IS NULL OR views_count>=0),
    CHECK (reactions_count IS NULL OR reactions_count>=0),
    CHECK (comments_count IS NULL OR comments_count>=0),
    CHECK (shares_count IS NULL OR shares_count>=0)
);
CREATE INDEX collector_publication_working_recent_idx
    ON ingest.collector_publication_working_set (publication_id, observed_at DESC, id DESC);
CREATE INDEX collector_publication_working_expiry_idx
    ON ingest.collector_publication_working_set (observed_at);

CREATE TABLE ingest.collector_account_working_set (
    id bigint GENERATED ALWAYS AS IDENTITY,
    platform_account_id uuid PRIMARY KEY REFERENCES catalog.platform_account(id),
    observed_at timestamptz NOT NULL,
    source_fingerprint text NOT NULL,
    semantic_fingerprint bytea,
    CHECK (semantic_fingerprint IS NULL OR octet_length(semantic_fingerprint)=32)
);
CREATE INDEX collector_account_working_expiry_idx
    ON ingest.collector_account_working_set (observed_at);

GRANT SELECT, INSERT, UPDATE, DELETE ON ingest.collector_publication_working_set,
    ingest.collector_account_working_set TO collector_ingest;
GRANT USAGE, SELECT ON SEQUENCE ingest.collector_publication_working_set_id_seq,
    ingest.collector_account_working_set_id_seq TO collector_ingest;
GRANT SELECT ON ingest.collector_publication_working_set,
    ingest.collector_account_working_set TO maintenance, storage_observer;

-- A seeded row is necessary even when a publication's latest fingerprint is
-- NULL. The durable marker prevents enabling an empty buffer by mistake.
CREATE TABLE ops_and_admin.collector_working_set_seed (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    started_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    completed_at timestamptz,
    publication_rows bigint NOT NULL DEFAULT 0 CHECK (publication_rows>=0),
    account_rows bigint NOT NULL DEFAULT 0 CHECK (account_rows>=0)
);
GRANT SELECT ON ops_and_admin.collector_working_set_seed TO collector_ingest, maintenance;

-- While the bounded seed runs, the old writer mirrors new state. This closes
-- the gap between copying a publication and restarting its collector.
CREATE FUNCTION ingest.capture_collector_working_state() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','ingest','ops_and_admin' AS $$
BEGIN
    IF current_setting('mranked.deployment_profile',true) IS DISTINCT FROM 'b'
       OR NOT EXISTS (SELECT 1 FROM ops_and_admin.collector_working_set_seed)
       OR NEW.observed_at < transaction_timestamp()-interval '31 days' THEN
        RETURN NULL;
    END IF;
    IF TG_TABLE_NAME='account_metric_snapshot' THEN
        INSERT INTO ingest.collector_account_working_set AS current
            (platform_account_id,observed_at,source_fingerprint,semantic_fingerprint)
        VALUES (NEW.platform_account_id,NEW.observed_at,NEW.source_fingerprint,NEW.semantic_fingerprint)
        ON CONFLICT (platform_account_id) DO UPDATE SET
            observed_at=excluded.observed_at,source_fingerprint=excluded.source_fingerprint,
            semantic_fingerprint=excluded.semantic_fingerprint
        WHERE excluded.observed_at>=current.observed_at;
    ELSE
        INSERT INTO ingest.collector_publication_working_set AS current
            (publication_id,published_month,sampling_bucket,observed_at,collected_at,
             synthetic,views_count,reactions_count,comments_count,shares_count,
             source_fingerprint,semantic_fingerprint)
        VALUES (NEW.publication_id,NEW.published_month,NEW.sampling_bucket,
                NEW.observed_at,NEW.collected_at,NEW.synthetic,NEW.views_count,
                NEW.reactions_count,NEW.comments_count,NEW.shares_count,
                NEW.source_fingerprint,NEW.semantic_fingerprint)
        ON CONFLICT (publication_id,sampling_bucket) DO UPDATE SET
            id=DEFAULT,published_month=excluded.published_month,
            observed_at=excluded.observed_at,collected_at=excluded.collected_at,
            synthetic=excluded.synthetic,views_count=excluded.views_count,
            reactions_count=excluded.reactions_count,comments_count=excluded.comments_count,
            shares_count=excluded.shares_count,source_fingerprint=excluded.source_fingerprint,
            semantic_fingerprint=excluded.semantic_fingerprint
        WHERE (excluded.observed_at,excluded.collected_at)>=(current.observed_at,current.collected_at)
          AND excluded.source_fingerprint IS DISTINCT FROM current.source_fingerprint;
        DELETE FROM ingest.collector_publication_working_set
         WHERE publication_id=NEW.publication_id
           AND id IN (SELECT id FROM ingest.collector_publication_working_set
                       WHERE publication_id=NEW.publication_id
                       ORDER BY observed_at DESC,id DESC OFFSET 24);
    END IF;
    RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION ingest.capture_collector_working_state() FROM PUBLIC;
CREATE TRIGGER capture_collector_working_state AFTER INSERT ON ingest.publication_metric_snapshot
    FOR EACH ROW EXECUTE FUNCTION ingest.capture_collector_working_state();
CREATE TRIGGER capture_collector_working_state AFTER INSERT ON ingest.account_metric_snapshot
    FOR EACH ROW EXECUTE FUNCTION ingest.capture_collector_working_state();
