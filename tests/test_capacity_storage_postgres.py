"""Lossless storage and source-read equivalence on disposable PostgreSQL 18+."""
from datetime import date
import json
import os
from uuid import uuid4

import psycopg
import pytest


@pytest.fixture
def db():
    dsn = os.getenv('MRANKED_CAPACITY_TEST_DSN')
    if not dsn:
        pytest.skip('MRANKED_CAPACITY_TEST_DSN is not configured')
    with psycopg.connect(dsn) as connection:
        connection.execute('SET ROLE migration_owner')
        yield connection
        connection.rollback()


def fixture(db):
    institution, account, publication, run = (uuid4() for _ in range(4))
    db.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES (%s,'Capacity test')", (institution,))
    db.execute("""INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                  VALUES (%s,%s,'telegram',%s,'public_web')""", (account, institution, str(account)))
    db.execute("""INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
                  VALUES (%s,%s,'2026-09-01 UTC','2026-09-01 UTC','post','complete')""", (publication, account))
    db.execute("""INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
                  VALUES (%s,'telegram',%s,'test','2026-09-01 UTC','succeeded',%s)""", (run, str(run), uuid4()))
    return publication, run


def insert(db, publication, run, fingerprint, evidence, *, bucket=1, views=10):
    return db.execute("""INSERT INTO ingest.publication_metric_snapshot(
           published_month,publication_id,collection_run_id,observed_at,collected_at,
           age_seconds,sampling_bucket,views_count,reactions_count,quality,source_fingerprint,metric_evidence)
           VALUES ('2026-09-01',%s,%s,'2026-09-02 UTC','2026-09-02 UTC',86400,%s,%s,2,'exact',%s,%s::jsonb)
           RETURNING id""", (publication, run, bucket, views, fingerprint, json.dumps(evidence))).fetchone()


def test_dictionary_replay_corrections_source_slice_and_archive(db):
    publication, run = fixture(db)
    evidence = {'views': {'source_field': 'views', 'quality': 'exact', 'description': 'я' * 300}}
    first = insert(db, publication, run, 'first', evidence)[0]
    physical = db.execute('SELECT metric_evidence,metric_evidence_id FROM ingest.publication_metric_snapshot WHERE published_month=%s AND id=%s', (date(2026, 9, 1), first)).fetchone()
    assert physical[0] is None and physical[1] is not None
    assert insert(db, publication, run, 'first', evidence) is None
    correction = insert(db, publication, run, 'corrected', evidence, views=12)[0]
    second = insert(db, publication, run, 'second-bucket', evidence, bucket=2)[0]
    assert db.execute('SELECT count(DISTINCT metric_evidence_id) FROM ingest.publication_metric_snapshot WHERE publication_id=%s', (publication,)).fetchone()[0] == 1
    canonical = json.loads(db.execute('SELECT ops_and_admin.publication_archive_record(%s,%s)', (date(2026, 9, 1), first)).fetchone()[0])
    assert canonical['metric_evidence'] == evidence
    assert 'metric_evidence_id' not in canonical
    expected = db.execute('SELECT to_jsonb(s) FROM analytics.usable_publication_snapshot s WHERE publication_id=%s ORDER BY id', (publication,)).fetchall()
    actual = db.execute('SELECT to_jsonb(s) FROM analytics.publication_snapshot_slice(%s,%s) s ORDER BY id', (publication, date(2026, 9, 1))).fetchall()
    assert actual == expected
    assert [r[0]['id'] for r in actual] == [correction, second]
    assert db.execute('SELECT count(*) FROM analytics.publication_snapshot_slice(%s,%s)', (publication, date(2026, 8, 1))).fetchone()[0] == 0
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        insert(db, publication, run, 'corrected', evidence, views=999)
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), db.transaction():
        db.execute('UPDATE ingest.publication_metric_snapshot SET views_count=99 WHERE published_month=%s AND id=%s', (date(2026, 9, 1), second))


def test_backfill_preserves_full_archive_digest_and_does_not_dictionary_encode_empty(db):
    publication, run = fixture(db)
    empty = insert(db, publication, run, 'empty', {}, bucket=0)[0]
    assert db.execute('SELECT metric_evidence,metric_evidence_id FROM ingest.publication_metric_snapshot WHERE published_month=%s AND id=%s', (date(2026, 9, 1), empty)).fetchone() == ({}, None)
    # Model a pre-expand row using the same old insert contract.
    db.execute('ALTER TABLE ingest.publication_metric_snapshot DISABLE TRIGGER zz_compact_metric_evidence')
    before_id = insert(db, publication, run, 'old-format', {'metric': 'x' * 700})[0]
    db.execute('ALTER TABLE ingest.publication_metric_snapshot ENABLE TRIGGER zz_compact_metric_evidence')
    before = db.execute('SELECT ops_and_admin.publication_archive_record(%s,%s)', (date(2026, 9, 1), before_id)).fetchone()[0]
    result = db.execute('SELECT * FROM ops_and_admin.compact_metric_evidence_batch(%s,%s,1)', (date(2026, 9, 1), before_id - 1)).fetchone()
    assert result == (before_id, 1, 1)
    assert db.execute('SELECT ops_and_admin.publication_archive_record(%s,%s)', (date(2026, 9, 1), before_id)).fetchone()[0] == before
    assert db.execute('SELECT * FROM ops_and_admin.compact_metric_evidence_batch(%s,%s,1)', (date(2026, 9, 1), before_id - 1)).fetchone() == (before_id, 1, 0)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute('SET LOCAL ROLE collector_ingest')
        db.execute('SELECT * FROM ops_and_admin.compact_metric_evidence_batch(%s,0,1)', (date(2026, 9, 1),))
