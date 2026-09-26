"""Pending coverage migration tested transactionally; never on production."""
import os
from pathlib import Path
import pytest


def test_global_ack_cannot_authorize_drop_and_coverage_survives_ack_purge():
    dsn=os.environ.get('MRANKED_TEST_POSTGRES_ADMIN_DSN')
    if not dsn:pytest.skip('isolated database not configured')
    import psycopg
    migration=Path(__file__).parents[1]/'db/migrations/pending/0041_collector_retention_coverage.sql'
    with psycopg.connect(dsn,autocommit=True) as c, c.transaction():
        c.execute(migration.read_text())
        c.execute("SELECT set_config('mranked.deployment_profile','b',true)")
        month='2020-01-01'
        c.execute('SELECT ops_and_admin.ensure_publication_metric_partition(%s::date)',(month,))
        # Even an empty month cannot be dropped without coverage.
        assert c.execute('SELECT ops_and_admin.collector_working_set_month_releasable(%s::date,720)',(month,)).fetchone()[0] is False
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), c.transaction():
            c.execute('SELECT ops_and_admin.drop_collector_working_set_month(%s::date,720)',(month,))
        stamp=c.execute('SELECT ops_and_admin.fence_collector_month(%s::date,720)',(month,)).fetchone()[0]
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), c.transaction():
            c.execute('SELECT ops_and_admin.assert_publication_partition_writable(%s::date)',(month,))
        # Synthetic equality evidence for the known-empty test partition.
        c.execute("INSERT INTO ops_and_admin.collector_month_coverage VALUES(%s,%s,clock_timestamp(),%s,%s,0,0,'test-target',1)",(month,stamp,'0'*64,'0'*64))
        c.execute("DELETE FROM ops_and_admin.transfer_outbox")
        assert c.execute('SELECT ops_and_admin.collector_working_set_month_releasable(%s::date,720)',(month,)).fetchone()[0] is True
        # Reopening invalidates certificate through the fence generation.
        c.execute("UPDATE ops_and_admin.publication_partition_fence SET changed_at=changed_at+interval '1 second' WHERE published_month=%s",(month,))
        assert c.execute('SELECT ops_and_admin.collector_working_set_month_releasable(%s::date,720)',(month,)).fetchone()[0] is False
        c.execute("UPDATE ops_and_admin.publication_partition_fence SET changed_at=%s WHERE published_month=%s",(stamp,month))
        assert c.execute('SELECT ops_and_admin.drop_collector_working_set_month(%s::date,720)',(month,)).fetchone()[0] is True
        assert c.execute("SELECT to_regclass('ingest.publication_metric_snapshot_2020_01')").fetchone()[0] is None
        raise psycopg.Rollback()


def test_comparison_query_covers_reactions_and_resolves_evidence_dictionary():
    dsn=os.environ.get('MRANKED_TEST_POSTGRES_ADMIN_DSN')
    if not dsn:pytest.skip('isolated database not configured')
    import importlib.util
    import psycopg
    path=Path(__file__).parents[1]/'operations/scripts/compare-retention-month.py'
    spec=importlib.util.spec_from_file_location('coverage_compare',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with psycopg.connect(dsn) as c:
        # Existing synthetic transfer fixtures exercise actual populated rows.
        month=c.execute('SELECT published_month FROM ingest.publication_metric_snapshot LIMIT 1').fetchone()
        assert month is not None
        result=module.digest(c,month[0])
        assert len(result[0])==64 and result[1]>0
