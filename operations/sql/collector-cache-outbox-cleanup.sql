-- Operator-only cleanup on the collector host. Preserve domain/admin events
-- byte-for-byte; cache invalidations and old source update notifications have
-- no consumer on profile B S1. This is not the durable transfer outbox.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout='1s';
SET LOCAL statement_timeout='10s';
DO $$ BEGIN
 IF current_setting('mranked.deployment_profile',true) IS DISTINCT FROM 'b' THEN
  RAISE EXCEPTION 'collector profile b required';
 END IF;
 IF EXISTS (SELECT 1 FROM pg_stat_activity WHERE usename IN ('api_read','api_write_admin','analytics_worker') AND pid<>pg_backend_pid()) THEN
  RAISE EXCEPTION 'serving/analysis sessions present; collector-only cleanup refused';
 END IF;
END $$;
LOCK TABLE ops_and_admin.outbox_event IN ACCESS EXCLUSIVE MODE;
CREATE TEMP TABLE collector_retained_outbox ON COMMIT DROP AS
 SELECT * FROM ops_and_admin.outbox_event
 WHERE event_type NOT IN ('cache.invalidated','source.account.updated');
DO $$ BEGIN
 IF (SELECT count(*) FROM collector_retained_outbox)>2000 THEN
  RAISE EXCEPTION 'unexpected domain event volume; cleanup refused';
 END IF;
END $$;
TRUNCATE ops_and_admin.outbox_event;
INSERT INTO ops_and_admin.outbox_event OVERRIDING SYSTEM VALUE
 SELECT * FROM collector_retained_outbox;
DO $$ BEGIN
 IF EXISTS ((SELECT * FROM collector_retained_outbox EXCEPT SELECT * FROM ops_and_admin.outbox_event)
            UNION ALL
            (SELECT * FROM ops_and_admin.outbox_event EXCEPT SELECT * FROM collector_retained_outbox)) THEN
  RAISE EXCEPTION 'retained domain events changed';
 END IF;
END $$;
COMMIT;
