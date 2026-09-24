-- Fail closed: global ACK age is not proof of historical snapshot coverage.
-- Apply on S1 only after approval; schema itself is inert on S2/profile A.
ALTER TABLE ops_and_admin.publication_partition_fence
 DROP CONSTRAINT publication_partition_fence_state_check;
ALTER TABLE ops_and_admin.publication_partition_fence
 ADD CONSTRAINT publication_partition_fence_state_check
 CHECK(state IN ('active','archiving','archived','retiring'));
CREATE TABLE ops_and_admin.collector_month_coverage (
 published_month date PRIMARY KEY,
 fence_at timestamptz NOT NULL,
 verified_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
 target_sha256 text NOT NULL CHECK(target_sha256=source_sha256),
 snapshot_rows bigint NOT NULL CHECK(snapshot_rows>=0),
 reaction_rows bigint NOT NULL CHECK(reaction_rows>=0),
 destination_system_identifier text NOT NULL CHECK(length(destination_system_identifier)>0),
 comparison_version integer NOT NULL CHECK(comparison_version=1)
);
REVOKE ALL ON ops_and_admin.collector_month_coverage FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON ops_and_admin.collector_month_coverage TO maintenance;

CREATE FUNCTION ops_and_admin.fence_collector_month(p_month date,p_track_hours integer)
RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','ops_and_admin'
SET lock_timeout TO '1s' SET TimeZone TO 'UTC'
AS $$
DECLARE moment timestamptz; state_now text;
BEGIN
 IF current_setting('mranked.deployment_profile',true) IS DISTINCT FROM 'b'
    OR p_month IS NULL OR p_month<>date_trunc('month',p_month)::date
    OR p_track_hours IS NULL OR p_track_hours<720
    OR transaction_timestamp() < p_month + interval '1 month' + make_interval(hours=>p_track_hours) THEN
   RAISE EXCEPTION 'unsafe collector month fence' USING ERRCODE='55000';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 SELECT state INTO state_now FROM ops_and_admin.publication_partition_fence WHERE published_month=p_month FOR UPDATE;
 IF state_now IS NOT NULL AND state_now<>'active' THEN
   RAISE EXCEPTION 'partition already fenced' USING ERRCODE='55000';
 END IF;
 moment:=clock_timestamp();
 INSERT INTO ops_and_admin.publication_partition_fence(published_month,state,changed_at)
 VALUES(p_month,'retiring',moment)
 ON CONFLICT(published_month) DO UPDATE SET state='retiring',changed_at=moment;
 RETURN moment;
END $$;
REVOKE ALL ON FUNCTION ops_and_admin.fence_collector_month(date,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.fence_collector_month(date,integer) TO maintenance;

CREATE OR REPLACE FUNCTION ops_and_admin.collector_working_set_month_releasable(p_month date,p_track_hours integer)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'pg_catalog','ops_and_admin' SET TimeZone TO 'UTC'
AS $$
BEGIN
 IF p_month IS NULL OR p_month<>date_trunc('month',p_month)::date
    OR p_track_hours IS NULL OR p_track_hours<720
    OR transaction_timestamp() < p_month + interval '1 month' + make_interval(hours=>p_track_hours) THEN
   RETURN false;
 END IF;
 RETURN EXISTS (
   SELECT 1 FROM ops_and_admin.collector_month_coverage c
   JOIN ops_and_admin.publication_partition_fence f USING(published_month)
   WHERE c.published_month=p_month AND f.state='retiring' AND f.changed_at=c.fence_at
     AND c.verified_at>=c.fence_at
 ) AND NOT EXISTS (
   SELECT 1 FROM ops_and_admin.transfer_outbox
   WHERE state<>'acknowledged'
 );
END $$;

CREATE OR REPLACE FUNCTION ops_and_admin.drop_collector_working_set_month(p_month date,p_track_hours integer)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','ingest','ops_and_admin'
SET lock_timeout TO '1s' SET TimeZone TO 'UTC'
AS $$
DECLARE suffix text:=to_char(p_month,'YYYY_MM');
BEGIN
 IF current_setting('mranked.deployment_profile',true) IS DISTINCT FROM 'b' THEN
   RAISE EXCEPTION 'collector profile b required' USING ERRCODE='55000';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('observation-partition:'||p_month::text,0));
 IF NOT ops_and_admin.collector_working_set_month_releasable(p_month,p_track_hours) THEN
   RAISE EXCEPTION 'month lacks frozen, verified delivery coverage' USING ERRCODE='55000';
 END IF;
 IF to_regclass('ingest.publication_metric_snapshot_'||suffix) IS NULL THEN RETURN false; END IF;
 LOCK TABLE ingest.publication_metric_snapshot,ingest.reaction_breakdown IN ACCESS EXCLUSIVE MODE;
 -- Writers are drained before the fence and cannot append after it. The
 -- immutable coverage record survives deletion of transport ACK envelopes.
 IF to_regclass('ingest.reaction_breakdown_'||suffix) IS NOT NULL THEN
   EXECUTE format('DROP TABLE ingest.%I','reaction_breakdown_'||suffix);
 END IF;
 EXECUTE format('ALTER TABLE ingest.publication_metric_snapshot DETACH PARTITION ingest.%I','publication_metric_snapshot_'||suffix);
 EXECUTE format('DROP TABLE ingest.%I','publication_metric_snapshot_'||suffix);
 UPDATE ops_and_admin.publication_partition_fence SET state='archived',changed_at=clock_timestamp() WHERE published_month=p_month;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION ops_and_admin.collector_working_set_month_releasable(date,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.drop_collector_working_set_month(date,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.collector_working_set_month_releasable(date,integer) TO collector_ingest,maintenance;
GRANT EXECUTE ON FUNCTION ops_and_admin.drop_collector_working_set_month(date,integer) TO collector_ingest;
