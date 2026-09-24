-- Indexes must first be built with operations/sql/storage-indexes.sql.
-- No product/transport history is removed by this migration.
CREATE OR REPLACE FUNCTION ops_and_admin.purge_delivered_outbox(
 p_older_than interval DEFAULT interval '1 day', p_batch_size integer DEFAULT 1000)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'pg_catalog','ops_and_admin'
SET lock_timeout TO '1s'
AS $$
DECLARE deleted bigint;
BEGIN
 IF p_batch_size IS NULL OR p_batch_size NOT BETWEEN 1 AND 10000
    OR p_older_than IS NULL OR p_older_than < interval '1 day' THEN
   RAISE EXCEPTION 'unsafe outbox purge bounds' USING ERRCODE='22023';
 END IF;
 WITH candidates AS MATERIALIZED (
   (SELECT id FROM ops_and_admin.outbox_event
    WHERE published_at < now()-p_older_than ORDER BY published_at,id LIMIT p_batch_size)
   UNION
   (SELECT id FROM ops_and_admin.outbox_event
    WHERE terminal_at < now()-p_older_than ORDER BY terminal_at,id LIMIT p_batch_size)
 ), doomed AS (
   SELECT e.id FROM ops_and_admin.outbox_event e JOIN candidates c USING(id)
   WHERE e.published_at < now()-p_older_than OR e.terminal_at < now()-p_older_than
   ORDER BY e.id LIMIT p_batch_size FOR UPDATE OF e SKIP LOCKED
 )
 DELETE FROM ops_and_admin.outbox_event e USING doomed d WHERE e.id=d.id;
 GET DIAGNOSTICS deleted=ROW_COUNT;
 RETURN deleted;
END $$;
REVOKE ALL ON FUNCTION ops_and_admin.purge_delivered_outbox(interval,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops_and_admin.purge_delivered_outbox(interval,integer) TO maintenance;
