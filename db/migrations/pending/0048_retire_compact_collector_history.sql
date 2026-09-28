-- S1 operator step after compact mode has been seeded and all writers switched.
-- Never run on the serving database. Neither schema nor fencing deletes facts.
ALTER TABLE ops_and_admin.publication_partition_fence
 DROP CONSTRAINT publication_partition_fence_state_check;
ALTER TABLE ops_and_admin.publication_partition_fence
 ADD CONSTRAINT publication_partition_fence_state_check
 CHECK(state IN ('active','archiving','archived','retiring'));

CREATE TABLE ops_and_admin.collector_full_history_coverage (
 published_month date PRIMARY KEY,
 fence_at timestamptz NOT NULL,
 verified_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
 target_sha256 text NOT NULL CHECK(target_sha256=source_sha256),
 snapshot_rows bigint NOT NULL CHECK(snapshot_rows>=0),
 reaction_rows bigint NOT NULL CHECK(reaction_rows>=0),
 source_last_snapshot_id bigint NOT NULL CHECK(source_last_snapshot_id>=0),
 destination_system_identifier text NOT NULL CHECK(destination_system_identifier ~ '^[0-9]{10,20}$'),
 comparison_version integer NOT NULL CHECK(comparison_version=2)
);
GRANT SELECT,INSERT ON ops_and_admin.collector_full_history_coverage TO maintenance;

CREATE FUNCTION ops_and_admin.fence_compact_collector_history(p_month date)
RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','ops_and_admin' SET lock_timeout TO '1s'
AS $$
DECLARE moment timestamptz; state_now text;
BEGIN
 IF current_setting('mranked.deployment_profile',true) IS DISTINCT FROM 'b'
    OR p_month IS NULL OR p_month<>date_trunc('month',p_month)::date
    OR NOT EXISTS (SELECT 1 FROM ops_and_admin.collector_working_set_seed WHERE completed_at IS NOT NULL) THEN
  RAISE EXCEPTION 'seeded compact collector profile required' USING ERRCODE='55000';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT state,changed_at INTO state_now,moment FROM ops_and_admin.publication_partition_fence
  WHERE published_month=p_month FOR UPDATE;
 IF state_now='retiring' THEN RETURN moment; END IF;
 IF state_now IS NOT NULL AND state_now<>'active' THEN
  RAISE EXCEPTION 'partition is already owned by another operation' USING ERRCODE='55000';
 END IF;
 moment:=clock_timestamp();
 INSERT INTO ops_and_admin.publication_partition_fence(published_month,state,changed_at)
 VALUES(p_month,'retiring',moment) ON CONFLICT(published_month)
 DO UPDATE SET state='retiring',changed_at=excluded.changed_at;
 RETURN moment;
END $$;

CREATE FUNCTION ops_and_admin.drop_compact_collector_history(p_month date)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','ingest','ops_and_admin'
SET lock_timeout TO '1s' SET statement_timeout TO '40s' SET TimeZone TO 'UTC'
AS $$
DECLARE proof ops_and_admin.collector_full_history_coverage%ROWTYPE;
        rows_now bigint; last_id bigint; suffix text:=to_char(p_month,'YYYY_MM');
BEGIN
 IF current_setting('mranked.deployment_profile',true) IS DISTINCT FROM 'b'
    OR p_month IS NULL OR p_month<>date_trunc('month',p_month)::date
    OR NOT EXISTS (SELECT 1 FROM ops_and_admin.collector_working_set_seed WHERE completed_at IS NOT NULL) THEN
  RAISE EXCEPTION 'seeded compact collector profile required' USING ERRCODE='55000';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT c.* INTO proof FROM ops_and_admin.collector_full_history_coverage c
 JOIN ops_and_admin.publication_partition_fence f USING(published_month)
 WHERE c.published_month=p_month AND f.state='retiring' AND c.fence_at=f.changed_at
   AND c.verified_at>=c.fence_at
   AND c.destination_system_identifier<>(SELECT system_identifier::text FROM pg_control_system());
 IF NOT FOUND THEN
  RAISE EXCEPTION 'frozen verified destination coverage required' USING ERRCODE='55000';
 END IF;
 IF to_regclass('ingest.publication_metric_snapshot_'||suffix) IS NULL THEN RETURN false; END IF;
 LOCK TABLE ingest.publication_metric_snapshot,ingest.reaction_breakdown IN ACCESS EXCLUSIVE MODE;
 SELECT count(*),coalesce(max(id),0) INTO rows_now,last_id
 FROM ingest.publication_metric_snapshot WHERE published_month=p_month;
 IF rows_now<>proof.snapshot_rows OR last_id<>proof.source_last_snapshot_id THEN
  RAISE EXCEPTION 'source changed or comparison excluded facts' USING ERRCODE='55000';
 END IF;
 SELECT count(*) INTO rows_now FROM ingest.reaction_breakdown WHERE snapshot_published_month=p_month;
 IF rows_now<>proof.reaction_rows THEN
  RAISE EXCEPTION 'reaction coverage changed' USING ERRCODE='55000';
 END IF;
 IF to_regclass('ingest.reaction_breakdown_'||suffix) IS NOT NULL THEN
  EXECUTE format('DROP TABLE ingest.%I','reaction_breakdown_'||suffix);
 END IF;
 EXECUTE format('ALTER TABLE ingest.publication_metric_snapshot DETACH PARTITION ingest.%I','publication_metric_snapshot_'||suffix);
 EXECUTE format('DROP TABLE ingest.%I','publication_metric_snapshot_'||suffix);
 UPDATE ops_and_admin.publication_partition_fence SET state='archived',changed_at=clock_timestamp()
 WHERE published_month=p_month;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION ops_and_admin.fence_compact_collector_history(date) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.drop_compact_collector_history(date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.fence_compact_collector_history(date),
 ops_and_admin.drop_compact_collector_history(date) TO maintenance;
