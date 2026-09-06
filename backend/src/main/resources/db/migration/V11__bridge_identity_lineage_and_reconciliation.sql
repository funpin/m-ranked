-- Business aliases are permanent. Observation/rating mappings point to the
-- accepted fact for the current source row; every preceding pointer is retained.
CREATE TABLE migration.identity_map_history (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_namespace uuid NOT NULL,
    source_table text NOT NULL,
    source_pk text NOT NULL,
    target_type text NOT NULL,
    target_uuid uuid,
    target_bigint bigint,
    source_row_hash text NOT NULL,
    batch_id uuid NOT NULL REFERENCES migration.import_batch(id),
    recorded_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    UNIQUE NULLS NOT DISTINCT
      (source_namespace,source_table,source_pk,target_type,target_uuid,target_bigint,source_row_hash)
);

INSERT INTO migration.identity_map_history(
    source_namespace,source_table,source_pk,target_type,target_uuid,target_bigint,source_row_hash,batch_id)
SELECT source_namespace,source_table,source_pk,target_type,target_uuid,target_bigint,source_row_hash,last_seen_batch_id
FROM migration.legacy_identity_map;

CREATE FUNCTION migration.guard_identity_map_tip() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,migration,ingest,rating AS $$
BEGIN
    IF TG_OP='UPDATE' AND
       (NEW.target_uuid IS DISTINCT FROM OLD.target_uuid OR NEW.target_bigint IS DISTINCT FROM OLD.target_bigint) THEN
        IF NEW.target_type='publication_metric_snapshot' THEN
            IF NOT EXISTS (
                SELECT 1 FROM ingest.publication_metric_snapshot a
                JOIN ingest.publication_metric_snapshot b ON b.id=NEW.target_bigint
                WHERE a.id=OLD.target_bigint AND a.publication_id=b.publication_id
                  AND a.published_month=b.published_month AND a.sampling_bucket=b.sampling_bucket
            ) THEN RAISE EXCEPTION 'observation identity remap rejected' USING ERRCODE='23514'; END IF;
        ELSIF NEW.target_type='account_metric_snapshot' THEN
            IF NOT EXISTS (
                SELECT 1 FROM ingest.account_metric_snapshot a
                JOIN ingest.account_metric_snapshot b ON b.id=NEW.target_bigint
                WHERE a.id=OLD.target_bigint AND a.platform_account_id=b.platform_account_id
            ) THEN RAISE EXCEPTION 'account observation identity remap rejected' USING ERRCODE='23514'; END IF;
        ELSIF NEW.target_type LIKE 'official_rating_observation:%' THEN
            IF NOT EXISTS (
                SELECT 1 FROM rating.official_rating_observation a
                JOIN rating.official_rating_observation b ON b.id=NEW.target_uuid
                WHERE a.id=OLD.target_uuid AND a.institution_id=b.institution_id AND a.category=b.category
            ) THEN RAISE EXCEPTION 'rating identity remap rejected' USING ERRCODE='23514'; END IF;
        ELSE
            RAISE EXCEPTION 'business identity remap rejected' USING ERRCODE='23514';
        END IF;
    END IF;
    INSERT INTO migration.identity_map_history(
        source_namespace,source_table,source_pk,target_type,target_uuid,target_bigint,source_row_hash,batch_id)
    VALUES (NEW.source_namespace,NEW.source_table,NEW.source_pk,NEW.target_type,
            NEW.target_uuid,NEW.target_bigint,NEW.source_row_hash,NEW.last_seen_batch_id)
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END $$;
CREATE TRIGGER identity_map_tip BEFORE INSERT OR UPDATE ON migration.legacy_identity_map
FOR EACH ROW EXECUTE FUNCTION migration.guard_identity_map_tip();
REVOKE ALL ON FUNCTION migration.guard_identity_map_tip() FROM PUBLIC;

CREATE TABLE migration.source_disappearance (
    source_namespace uuid NOT NULL,
    source_table text NOT NULL,
    source_pk text NOT NULL,
    target_type text NOT NULL,
    source_row_hash text NOT NULL,
    first_missing_batch_id uuid NOT NULL REFERENCES migration.import_batch(id),
    detected_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    PRIMARY KEY(source_namespace,source_table,source_pk,target_type,source_row_hash)
);
CREATE TABLE migration.source_disappearance_decision (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_namespace uuid NOT NULL,
    source_table text NOT NULL,
    source_pk text NOT NULL,
    target_type text NOT NULL,
    source_row_hash text NOT NULL,
    decision text NOT NULL CHECK(decision IN ('preserved_history','tombstone','confirmed_admin_delete')),
    operator text NOT NULL CHECK(btrim(operator)<>''),
    ticket text NOT NULL CHECK(btrim(ticket)<>''),
    reason text NOT NULL CHECK(btrim(reason)<>''),
    decided_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
    FOREIGN KEY(source_namespace,source_table,source_pk,target_type,source_row_hash)
      REFERENCES migration.source_disappearance(source_namespace,source_table,source_pk,target_type,source_row_hash)
);
-- Decisions require the migration owner; the bridge only records missing rows.
GRANT SELECT,INSERT ON migration.source_disappearance TO migration_bridge;
GRANT SELECT ON migration.source_disappearance_decision,migration.identity_map_history TO migration_bridge,maintenance;
CREATE FUNCTION migration.reject_history_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'migration history is append-only' USING ERRCODE='55000'; END $$;
CREATE TRIGGER identity_history_immutable BEFORE UPDATE OR DELETE ON migration.identity_map_history
FOR EACH ROW EXECUTE FUNCTION migration.reject_history_mutation();
CREATE TRIGGER disappearance_immutable BEFORE UPDATE OR DELETE ON migration.source_disappearance
FOR EACH ROW EXECUTE FUNCTION migration.reject_history_mutation();
CREATE TRIGGER disappearance_decision_immutable BEFORE UPDATE OR DELETE ON migration.source_disappearance_decision
FOR EACH ROW EXECUTE FUNCTION migration.reject_history_mutation();
REVOKE ALL ON FUNCTION migration.reject_history_mutation() FROM PUBLIC;
GRANT USAGE ON SCHEMA flyway TO migration_bridge;
GRANT SELECT ON ALL TABLES IN SCHEMA flyway TO migration_bridge;
