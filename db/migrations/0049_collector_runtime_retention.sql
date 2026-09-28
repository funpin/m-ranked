-- Compact collectors keep scheduling state, not an unlimited run ledger.
-- These small indexes also bound FK checks when an old run becomes eligible.
CREATE INDEX IF NOT EXISTS collector_result_expiry_idx
 ON ingest.collection_account_result(started_at,id) WHERE completed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS collector_run_expiry_idx
 ON ingest.collection_run(started_at,id) WHERE completed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS collector_availability_expiry_idx
 ON ingest.publication_availability_state(last_checked_at,publication_id);
CREATE INDEX IF NOT EXISTS collector_availability_run_ref_idx
 ON ingest.publication_availability_state(last_collection_run_id);
CREATE INDEX IF NOT EXISTS collector_revision_run_ref_idx
 ON analytics.dataset_revision(source_run_id) WHERE source_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS collector_revision_expiry_idx
 ON analytics.dataset_revision(committed_at,id);

CREATE OR REPLACE FUNCTION ops_and_admin.prune_compact_collector_runtime(p_limit integer DEFAULT 1000)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','ingest','ops_and_admin'
SET lock_timeout TO '1s'
AS $$
DECLARE results bigint; states bigint; runs bigint; revisions bigint:=0; ref record; guards text:='';
BEGIN
 IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
  RAISE EXCEPTION 'runtime expiry batch must be between 1 and 1000' USING ERRCODE='22023';
 END IF;
 IF current_setting('mranked.deployment_profile',true) IS DISTINCT FROM 'b'
    OR NOT EXISTS (SELECT 1 FROM ops_and_admin.collector_working_set_seed WHERE completed_at IS NOT NULL) THEN
  RAISE EXCEPTION 'seeded compact collector profile required' USING ERRCODE='55000';
 END IF;
 WITH expired AS (
  SELECT id FROM ingest.collection_account_result
   WHERE started_at<transaction_timestamp()-interval '31 days' AND completed_at IS NOT NULL
   ORDER BY started_at,id LIMIT p_limit FOR UPDATE SKIP LOCKED
 ) DELETE FROM ingest.collection_account_result r USING expired e WHERE r.id=e.id;
 GET DIAGNOSTICS results=ROW_COUNT;
 WITH expired AS (
  SELECT publication_id FROM ingest.publication_availability_state
   WHERE last_checked_at<transaction_timestamp()-interval '31 days'
   ORDER BY last_checked_at,publication_id LIMIT p_limit FOR UPDATE SKIP LOCKED
 ) DELETE FROM ingest.publication_availability_state s USING expired e WHERE s.publication_id=e.publication_id;
 GET DIAGNOSTICS states=ROW_COUNT;
 IF EXISTS (SELECT 1 FROM analytics.dataset_revision
             WHERE committed_at<transaction_timestamp()-interval '31 days' LIMIT 1) THEN
  revisions:=ops_and_admin.purge_old_dataset_revisions(interval '31 days',p_limit);
 END IF;
 -- Preserve any live FK anchor, including identity provenance, raw evidence,
 -- current state and schemas added later. Payloads contain their own run context;
 -- the transfer queue is never inspected or changed by runtime expiry.
 FOR ref IN
  SELECT conrelid::regclass AS relation,a.attname AS column_name
  FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
  WHERE c.contype='f' AND c.conparentid=0 AND c.confrelid='ingest.collection_run'::regclass
    AND c.conrelid<>'ingest.collection_account_result'::regclass
 LOOP
  guards:=guards||format(' AND NOT EXISTS (SELECT 1 FROM %s ref WHERE ref.%I=r.id)',ref.relation,ref.column_name);
 END LOOP;
 EXECUTE 'WITH expired AS (SELECT r.id FROM ingest.collection_run r
  WHERE r.started_at<transaction_timestamp()-interval ''31 days'' AND r.completed_at IS NOT NULL'
  ||guards||' ORDER BY r.started_at,r.id LIMIT $1 FOR UPDATE OF r SKIP LOCKED)
  DELETE FROM ingest.collection_run r USING expired e WHERE r.id=e.id' USING p_limit;
 GET DIAGNOSTICS runs=ROW_COUNT;
 RETURN jsonb_build_object('account_results',results,'stale_availability',states,
                          'unreferenced_runs',runs,'unreferenced_revisions',revisions);
END $$;
REVOKE ALL ON FUNCTION ops_and_admin.prune_compact_collector_runtime(integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.prune_compact_collector_runtime(integer) TO collector_ingest,maintenance;
