"""Real SQL safety checks; use only an isolated test database."""
import os
from uuid import uuid4
import pytest


def test_delivered_outbox_cutoff_pending_and_rollback():
    dsn=os.environ.get('MRANKED_TEST_POSTGRES_ADMIN_DSN')
    if not dsn:pytest.skip('isolated database not configured')
    import psycopg
    with psycopg.connect(dsn,autocommit=True) as c:
        with c.transaction():
            # Roll back all synthetic data at end, including purge effects.
            revision=c.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id) VALUES ('retention',gen_random_uuid()) RETURNING id").fetchone()[0]
            ids=[]
            for state in ['pending','old','young','terminal']:
                ids.append(c.execute("""INSERT INTO ops_and_admin.outbox_event(dataset_revision_id,event_type,aggregate_type,aggregate_id,published_at,terminal_at,terminal_reason)
                    VALUES (%s,'cache.invalidated','test',%s,
                      CASE %s WHEN 'old' THEN now()-interval '2 days' WHEN 'young' THEN now() ELSE NULL END,
                      CASE WHEN %s='terminal' THEN now()-interval '2 days' ELSE NULL END,
                      CASE WHEN %s='terminal' THEN 'test' ELSE NULL END) RETURNING id""",(revision,str(uuid4()),state,state,state)).fetchone()[0])
            removed=c.execute("SELECT ops_and_admin.purge_delivered_outbox(interval '1 day',1)").fetchone()[0]
            assert removed == 1
            c.execute("SELECT ops_and_admin.purge_delivered_outbox(interval '1 day',1000)")
            remaining={row[0] for row in c.execute('SELECT id FROM ops_and_admin.outbox_event WHERE id=ANY(%s)',(ids,))}
            assert remaining == {ids[0],ids[2]}
            for interval,size in [('0 days',1),('1 day',0),('1 day',10001)]:
                with pytest.raises(psycopg.errors.InvalidParameterValue), c.transaction():
                    c.execute('SELECT ops_and_admin.purge_delivered_outbox(%s::interval,%s)',(interval,size))
            # Explicit transaction rollback models a crash before commit.
            raise psycopg.Rollback()
