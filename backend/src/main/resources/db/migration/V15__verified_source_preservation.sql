-- A missing legacy row is accepted only with a source-derived immutable ledger.
-- Operational roles cannot approve their own reconciliation exceptions.
CREATE TABLE migration.source_preservation (
    id uuid PRIMARY KEY,
    source_namespace uuid NOT NULL,
    current_batch_id uuid NOT NULL REFERENCES migration.import_batch(id),
    prior_source_sha256 text NOT NULL CHECK(prior_source_sha256 ~ '^[0-9a-f]{64}$'),
    facts_sha256 text NOT NULL CHECK(facts_sha256 ~ '^[0-9a-f]{64}$'),
    operator text NOT NULL CHECK(btrim(operator)<>''),
    ticket text NOT NULL CHECK(btrim(ticket)<>''),
    reason text NOT NULL CHECK(btrim(reason)<>''),
    verified_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE(source_namespace,current_batch_id,prior_source_sha256)
);
CREATE TABLE migration.preserved_source_decision (
    preservation_id uuid NOT NULL REFERENCES migration.source_preservation(id),
    decision_id bigint NOT NULL UNIQUE REFERENCES migration.source_disappearance_decision(id),
    PRIMARY KEY(preservation_id,decision_id)
);
CREATE TABLE migration.preserved_canonical_fact (
    preservation_id uuid NOT NULL REFERENCES migration.source_preservation(id),
    fact_type text NOT NULL CHECK(fact_type IN ('institutions','accounts','subscribers',
        'publications','publication_identities','observations','reaction_keys','official_rating_values')),
    natural_key jsonb NOT NULL,
    body jsonb NOT NULL CHECK(jsonb_typeof(body)='object'),
    PRIMARY KEY(preservation_id,fact_type,natural_key)
);
CREATE INDEX preserved_scope ON migration.source_preservation(source_namespace);
CREATE TRIGGER preservation_immutable BEFORE UPDATE OR DELETE ON migration.source_preservation
    FOR EACH ROW EXECUTE FUNCTION migration.reject_history_mutation();
CREATE TRIGGER preserved_decision_immutable BEFORE UPDATE OR DELETE ON migration.preserved_source_decision
    FOR EACH ROW EXECUTE FUNCTION migration.reject_history_mutation();
CREATE TRIGGER preserved_fact_immutable BEFORE UPDATE OR DELETE ON migration.preserved_canonical_fact
    FOR EACH ROW EXECUTE FUNCTION migration.reject_history_mutation();
GRANT SELECT ON migration.source_preservation,migration.preserved_source_decision,
    migration.preserved_canonical_fact TO migration_bridge;
