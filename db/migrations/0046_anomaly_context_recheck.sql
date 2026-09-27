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
