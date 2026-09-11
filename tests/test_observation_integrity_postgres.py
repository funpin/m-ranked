"""Real PostgreSQL regressions, isolated in a self-created disposable database.

The CI integration runner provides a local bootstrap connection; no existing
application database is mutated. Every run installs the one final schema and
destroys only its randomly named fixture database.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import os
import subprocess
from pathlib import Path
from threading import Event
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
import pytest

from operations.cold_archive.model import MonthRange
from operations.cold_archive.service import ColdArchiveService

DSN = os.environ.get('MRANKED_TEST_POSTGRES_ADMIN_DSN')
pytestmark = pytest.mark.skipif(not DSN, reason='integration runner must provide local PostgreSQL bootstrap DSN')
UTC = timezone.utc


@pytest.fixture(scope='module')
def database(tmp_path_factory):
    options = conninfo_to_dict(str(DSN))
    if options.get('host') not in ('127.0.0.1', 'localhost', '::1'):
        pytest.fail('integrity fixture only permits loopback PostgreSQL')
    name = 'mranked_observations_it_' + uuid4().hex[:12] + '_it'
    build = tmp_path_factory.mktemp('observation-final-schema')
    def install_schema():
        command = [str(Path('backend/mvnw').resolve()), '-Dmranked.build.directory='+str(build),
                   '-Pschema-integration', '-Dtest=MigrationInstallationTest#migrateDisposableIntegrityDatabase', 'test']
        if os.getenv('MRANKED_MAVEN_REPOSITORY'):
            command.insert(1, '-Dmaven.repo.local='+os.environ['MRANKED_MAVEN_REPOSITORY'])
        environment = os.environ | {
            'MRANKED_INTEGRITY_INSTALL_URL': f'jdbc:postgresql://127.0.0.1:{options["port"]}/{name}',
            'MRANKED_MIGRATION_TEST_USER': options['user'],
            'MRANKED_MIGRATION_TEST_PASSWORD': options['password'],
        }
        result = subprocess.run(command, cwd='backend', env=environment, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout[-5000:].replace(options['password'], '[redacted]')
    with psycopg.connect(str(DSN), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {} OWNER migration_owner').format(sql.Identifier(name)))
        dsn = make_conninfo(str(DSN), dbname=name)
        try:
            install_schema()
            yield dsn
        finally:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def seed(connection, month='2025-01-01', platform='telegram'):
    institution, account, publication, run = [uuid4() for _ in range(4)]
    observed = datetime.fromisoformat(month).replace(tzinfo=UTC)+timedelta(days=1,hours=2)
    connection.execute('SELECT ops_and_admin.ensure_publication_metric_partition(%s::date)', (month,))
    connection.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES(%s,'Integrity fixture')",(institution,))
    connection.execute("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) VALUES(%s,%s,%s,%s,'public_web')",(account,institution,platform,str(account)))
    connection.execute("INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id) VALUES(%s,%s,'integrity','test',%s,'succeeded',%s)",(run,platform,observed,uuid4()))
    connection.execute("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness,created_at) VALUES(%s,%s,%s,%s,'post','incomplete',%s)",(publication,account,observed-timedelta(hours=2),observed,observed))
    return dict(institution=institution, account=account, publication=publication,run=run,observed=observed,month=date.fromisoformat(month))


def insert(connection, fixture, fingerprint='original', views=10, shares=1, shares_quality='exact', reactions_quality='exact', comments_quality='exact', bucket=1, age_seconds=7200, reactions=2):
    return connection.execute("""INSERT INTO ingest.publication_metric_snapshot(
      published_month,publication_id,collection_run_id,observed_at,collected_at,age_seconds,sampling_bucket,
      views_count,reactions_count,comments_count,shares_count,quality,source_fingerprint,
      views_quality,reactions_quality,comments_quality,shares_quality)
      VALUES(%(month)s,%(publication)s,%(run)s,%(observed)s,%(observed)s,%(age_seconds)s,%(bucket)s,
      %(views)s,%(reactions)s,3,%(shares)s,'invalid',%(fingerprint)s,'exact',%(reactions_quality)s,%(comments_quality)s,%(shares_quality)s)
      RETURNING *""",{**fixture,'views':views,'shares':shares,'shares_quality':shares_quality,'fingerprint':fingerprint,'reactions_quality':reactions_quality,'comments_quality':comments_quality,'bucket':bucket,'age_seconds':age_seconds,'reactions':reactions}).fetchone()


def test_exact_replay_corrections_immutable_and_independent_metric_projection(database):
    with psycopg.connect(database,row_factory=dict_row) as c:
        fixture=seed(c)
        original=insert(c,fixture,shares=None,shares_quality='invalid')
        assert insert(c,fixture,shares=None,shares_quality='invalid') is None
        correction=insert(c,fixture,'correction-1',views=11,shares=None,shares_quality='invalid')
        latest=insert(c,fixture,'correction-2',views=12,shares=None,shares_quality='invalid')
        assert correction['supersedes_snapshot_id']==original['id']
        assert latest['supersedes_snapshot_id']==correction['id']
        assert latest['correction_sequence']==2
        assert latest['correction_reason']=='provider_payload_changed'
        assert c.execute('SELECT * FROM ingest.publication_metric_snapshot WHERE published_month=%s AND id=%s',(fixture['month'],original['id'])).fetchone()==original
        assert c.execute('SELECT id FROM ingest.publication_metric_snapshot_active WHERE publication_id=%s',(fixture['publication'],)).fetchone()['id']==latest['id']
        for query in ['UPDATE ingest.publication_metric_snapshot SET views_count=100 WHERE id=%s','DELETE FROM ingest.publication_metric_snapshot WHERE id=%s']:
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState), c.transaction():
                c.execute(query,(original['id'],))
        with pytest.raises(psycopg.errors.UniqueViolation),c.transaction():
            insert(c,fixture,'correction-2',views=99,shares=None,shares_quality='invalid')
        revision=c.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES('ingestion',%s,%s) RETURNING id",(uuid4(),fixture['observed'])).fetchone()['id']
        c.execute('SELECT analytics.rebuild_core_projections(%s)',(revision,))
        point=c.execute('SELECT views_count,reactions_count,comments_count,shares_count,views_quality FROM analytics.publication_latest WHERE publication_id=%s',(fixture['publication'],)).fetchone()
        assert point==dict(views_count=12,reactions_count=2,comments_count=3,shares_count=None,views_quality='exact')
        for metric,expected in [('views',12),('reactions',2),('comments',3),('shares',None)]:
            aggregate=c.execute("SELECT value,quality,sample_size FROM analytics.institution_daily_metrics WHERE institution_id=%s AND platform='telegram' AND metric_key=%s AND aggregation='sum'",(fixture['institution'],metric)).fetchone()
            assert aggregate['value']==expected
            assert aggregate['sample_size']==(0 if expected is None else 1)
            if expected is not None: assert aggregate['quality']=='exact'
        c.rollback()


def test_account_corrections_preserve_lineage_and_active_tip(database):
    with psycopg.connect(database,row_factory=dict_row) as c:
        f=seed(c,'2025-02-01')
        query="""INSERT INTO ingest.account_metric_snapshot(platform_account_id,collection_run_id,observed_at,collected_at,subscriber_count,quality,source_fingerprint)
        VALUES(%s,%s,%s,%s,%s,'exact',%s) RETURNING *"""
        first=c.execute(query,(f['account'],f['run'],f['observed'],f['observed'],0,'zero')).fetchone()
        assert c.execute(query,(f['account'],f['run'],f['observed'],f['observed'],0,'zero')).fetchone() is None
        second=c.execute(query,(f['account'],f['run'],f['observed'],f['observed'],None,'unknown')).fetchone()
        assert second['supersedes_snapshot_id']==first['id']
        assert second['subscriber_quality']=='exact'
        assert c.execute('SELECT subscriber_count FROM ingest.account_metric_snapshot_active WHERE platform_account_id=%s',(f['account'],)).fetchone()['subscriber_count'] is None
        c.rollback()


def test_archive_fences_concurrent_correction_and_revalidates_digest(database,tmp_path):
    with psycopg.connect(database,row_factory=dict_row) as c:
        f=seed(c,'2025-03-01','vk')
        original=insert(c,f)
        c.execute('INSERT INTO ingest.reaction_breakdown VALUES(%s,%s,%s,%s)',(f['month'],original['id'],'like',2))
    exported, resume = Event(), Event()
    class PausedArchive(ColdArchiveService):
        def _export(self, connection, month):
            result=super()._export(connection,month)
            exported.set()
            assert resume.wait(20)
            return result
    service=PausedArchive(database,tmp_path,batch_size=1,min_free_bytes=0)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending=executor.submit(service.archive,MonthRange(f['month']))
        assert exported.wait(20)
        try:
            with psycopg.connect(database,row_factory=dict_row) as c:
                with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),c.transaction():
                    insert(c,f,'concurrent',views=99)
        finally:
            resume.set()
        result=pending.result(timeout=20)
    assert result.verification.row_count==1
    import pyarrow.parquet as pq
    archived=pq.read_table(result.object_path).to_pylist()
    assert archived[0]['views_count']==10
    assert 'like' in archived[0]['reaction_breakdown_json']
    with psycopg.connect(database,row_factory=dict_row) as c:
        insert(c,f,'after-export',views=11)
    # Reuse rechecks live canonical data, so the previous spool is insufficient.
    current=ColdArchiveService(database,tmp_path,batch_size=1,min_free_bytes=0).archive(MonthRange(f['month']))
    assert not current.reused
    assert current.verification.row_count==2
    assert current.verification.canonical_sha256!=result.verification.canonical_sha256
    with psycopg.connect(database) as c:
        c.execute('SELECT ops_and_admin.begin_publication_archive(%s)',(f['month'],))
        with pytest.raises(psycopg.errors.RaiseException,match='attestation'),c.transaction():
            c.execute('SELECT ops_and_admin.drop_publication_metric_partition(%s,%s)',(f['month'],current.manifest_id))
        c.rollback()


def test_empty_partition_canonical_archive(database,tmp_path):
    with psycopg.connect(database) as c:
        c.execute("SELECT ops_and_admin.ensure_publication_metric_partition('2025-04-01')")
    result=ColdArchiveService(database,tmp_path,min_free_bytes=0).archive(MonthRange.parse('2025-04'))
    assert result.verification.row_count==0
    import hashlib
    assert result.verification.canonical_sha256==hashlib.sha256(b'').hexdigest()


def test_collector_role_commits_retrievable_evidence_quality_and_corrections(database,tmp_path):
    from dataclasses import replace
    from collector_target.evidence import ImmutableEvidenceStore
    from collector_target.model import AccountRef,CollectionContext,Platform,RawCollectionBatch,RawPublication
    from collector_target.normalize import CanonicalNormalizer
    from collector_target.repository import PostgresCollectorRepository
    with psycopg.connect(database,row_factory=dict_row) as admin:
        f=seed(admin,'2025-05-01')
    def connect():
        c=psycopg.connect(database,autocommit=True,row_factory=dict_row)
        c.execute('SET ROLE collector_ingest')
        return c
    store=ImmutableEvidenceStore(tmp_path/'raw')
    repository=PostgresCollectorRepository(connection_factory=connect,evidence_store=store)
    account=AccountRef(f['account'],f['institution'],Platform.TELEGRAM,str(f['account']),'public_web')
    context=CollectionContext.create(Platform.TELEGRAM,'all','integrity',f['observed'],f['observed'])
    repository.start_run(context)
    assert repository.begin_account(context,account,f['observed'])
    raw=RawCollectionBatch(account,None,(RawPublication(
        external_id='m:42',published_at=f['observed']-timedelta(hours=2),discovered_at=f['observed'],
        observed_at=f['observed'],collected_at=f['observed'],publication_type='post',
        metrics={'views':10,'reactions':2,'comments':3,'shares':-1},
        source={'access_token':'must-disappear','metrics':{'views':10,'shares':-1}},
    ),),'fixture','1')
    batch=CanonicalNormalizer().normalize(raw,context)
    first=repository.persist_account_batch(batch)
    assert first.snapshot_count==1
    assert repository.persist_account_batch(batch).snapshot_count==0
    changed=replace(raw,publications=(replace(raw.publications[0],metrics={'views':12,'reactions':2,'comments':3,'shares':-1}),))
    assert repository.persist_account_batch(CanonicalNormalizer().normalize(changed,context)).snapshot_count==1
    with psycopg.connect(database,row_factory=dict_row) as admin:
        snapshots=admin.execute('SELECT * FROM ingest.publication_metric_snapshot WHERE collection_run_id=%s ORDER BY correction_sequence',(context.run_id,)).fetchall()
        assert len(snapshots)==2
        assert snapshots[1]['supersedes_snapshot_id']==snapshots[0]['id']
        assert snapshots[0]['views_quality']=='exact' and snapshots[0]['shares_quality']=='invalid'
        refs=admin.execute('SELECT * FROM ingest.raw_payload WHERE collection_run_id=%s',(context.run_id,)).fetchall()
        assert len(refs)==2
        for ref in refs:
            evidence=store.read(ref['external_ref'],ref['sha256'],purge_after=ref['purge_after'],now=f['observed'])
            assert evidence['source']['access_token']=='[REDACTED]'
        repository.quarantine_rejected_batch(raw,context,'ValueError')
        assert admin.execute('SELECT count(*) AS count FROM ingest.evidence_quarantine').fetchone()['count']==1


def test_drop_recomputes_digest_after_independent_attestation(database,tmp_path):
    # Rehearsal only: the attestation below is deliberately synthetic and lives
    # solely in this disposable fixture. No production/off-primary claim is made.
    with psycopg.connect(database,row_factory=dict_row) as c:
        f=seed(c,'2025-06-01','rutube')
        insert(c,f)
    result=ColdArchiveService(database,tmp_path,min_free_bytes=0).archive(MonthRange(f['month']))
    with psycopg.connect(database,row_factory=dict_row) as c:
        c.execute("""INSERT INTO ops_and_admin.archive_object_attestation
            (manifest_id,object_uri,object_version,sha256,canonical_sha256,row_count,failure_domain,immutable_until,verifier_subject)
            VALUES(%s,'s3://disposable-fixture/object','fixture-only',%s,%s,%s,'fixture-secondary',transaction_timestamp()+interval '1 day','synthetic-test')""",
            (result.manifest_id,result.verification.sha256,result.verification.canonical_sha256,result.verification.row_count))
        insert(c,f,'late-before-fence',views=99)
        c.execute('SELECT ops_and_admin.begin_publication_archive(%s)',(f['month'],))
        with pytest.raises(psycopg.errors.RaiseException,match='content changed'),c.transaction():
            c.execute('SELECT ops_and_admin.drop_publication_metric_partition(%s,%s)',(f['month'],result.manifest_id))
        assert c.execute('SELECT count(*) AS count FROM ingest.publication_metric_snapshot WHERE published_month=%s',(f['month'],)).fetchone()['count']==2
        c.execute('SELECT ops_and_admin.abort_publication_archive(%s)',(f['month'],))
    latest=ColdArchiveService(database,tmp_path,min_free_bytes=0).archive(MonthRange(f['month']))
    with psycopg.connect(database,row_factory=dict_row) as c:
        c.execute("""INSERT INTO ops_and_admin.archive_object_attestation
            (manifest_id,object_uri,object_version,sha256,canonical_sha256,row_count,failure_domain,immutable_until,verifier_subject)
            VALUES(%s,'s3://disposable-fixture/object-v2','fixture-only-v2',%s,%s,%s,'fixture-secondary',transaction_timestamp()+interval '1 day','synthetic-test')""",
            (latest.manifest_id,latest.verification.sha256,latest.verification.canonical_sha256,latest.verification.row_count))
        c.execute('SELECT ops_and_admin.begin_publication_archive(%s)',(f['month'],))
        c.execute('SELECT ops_and_admin.drop_publication_metric_partition(%s,%s)',(f['month'],latest.manifest_id))
        assert c.execute('SELECT state FROM ops_and_admin.publication_partition_fence WHERE published_month=%s',(f['month'],)).fetchone()['state']=='archived'
        assert c.execute('SELECT count(*) AS count FROM ingest.publication_metric_snapshot WHERE published_month=%s',(f['month'],)).fetchone()['count']==0


def test_v8_backfill_is_explicit_and_constraints_are_validated(database):
    with psycopg.connect(database,row_factory=dict_row) as c:
        rows=c.execute("SELECT views_count,reactions_count,comments_count,views_quality,reactions_quality,correction_sequence,supersedes_snapshot_id FROM ingest.publication_metric_snapshot WHERE source_fingerprint='v8-upgrade-fixture'").fetchall()
        for row in rows:
            assert row==dict(views_count=0,reactions_count=None,comments_count=1,views_quality='rounded',reactions_quality='rounded',correction_sequence=0,supersedes_snapshot_id=None)
        assert c.execute('SELECT count(*) AS count FROM ingest.raw_payload WHERE legacy_evidence_unavailable').fetchone()['count']==len(rows)
        assert c.execute("SELECT count(*) AS count FROM pg_constraint WHERE connamespace='ingest'::regnamespace AND NOT convalidated").fetchone()['count']==0



def test_quality_belongs_to_each_metric_in_latest_hourly_period_and_comparison(database):
    with psycopg.connect(database,row_factory=dict_row) as c:
        f=seed(c,'2025-07-01')
        insert(c,{**f,'observed':f['observed']-timedelta(hours=1)},age_seconds=3600,reactions_quality='rounded',comments_quality='estimated',shares=None,shares_quality='invalid')
        later={**f,'observed':f['observed']+timedelta(hours=22)}
        insert(c,later,'next-hour',views=20,bucket=2,age_seconds=86400,reactions_quality='rounded',comments_quality='estimated',shares=None,shares_quality='invalid')
        revision=c.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES('ingestion',%s,%s) RETURNING id",(uuid4(),later['observed'])).fetchone()['id']
        c.execute('SELECT analytics.rebuild_core_projections(%s)',(revision,))
        for table in ['publication_latest','publication_hourly','comparison_publication_hourly']:
            row=c.execute(sql.SQL('SELECT views_quality,reactions_quality,comments_quality,shares_count FROM analytics.{} WHERE publication_id=%s AND views_count IS NOT NULL LIMIT 1').format(sql.Identifier(table)),(f['publication'],)).fetchone()
            assert row==dict(views_quality='exact',reactions_quality='rounded',comments_quality='estimated',shares_count=None), table
        for table in ['institution_daily_metrics','institution_monthly_metrics','institution_period_metrics']:
            for metric,quality in [('views','exact'),('reactions','rounded'),('comments','estimated')]:
                period_filter=" AND period_key='1d'" if table=='institution_period_metrics' else ''
                rows=c.execute(sql.SQL("SELECT quality,sample_size FROM analytics.{} WHERE institution_id=%s AND platform='telegram' AND metric_key=%s AND aggregation='sum'"+period_filter).format(sql.Identifier(table)),(f['institution'],metric)).fetchall()
                assert rows and all(row==dict(quality=quality,sample_size=1) for row in rows)
        c.rollback()


def test_raw_expiry_gc_keeps_active_reference_then_removes_file_and_metadata(database,tmp_path):
    from collector_target.evidence import ImmutableEvidenceStore
    store=ImmutableEvidenceStore(tmp_path/'gc')
    uri,digest=store.put({'views':0,'token':'secret'})
    now=datetime.now(UTC)
    with psycopg.connect(database,row_factory=dict_row) as c:
        f=seed(c,'2025-08-01')
        c.execute("""INSERT INTO ingest.raw_payload(collection_run_id,owner_type,owner_id,collected_at,sha256,content_encoding,external_ref,purge_after)
          VALUES(%s,'publication',%s,%s,%s,'identity',%s,%s)""",(f['run'],f['publication'],now-timedelta(days=1),digest,uri,now+timedelta(days=6)))
    with psycopg.connect(database,row_factory=dict_row) as c:
        c.execute('SET ROLE maintenance')
        assert store.purge_expired(c,now=now)==0
        assert store.purge_expired(c,now=now+timedelta(days=7))==1
    assert not list((tmp_path/'gc').glob('*.json'))
    with psycopg.connect(database) as c:
        assert c.execute('SELECT count(*) FROM ingest.raw_payload WHERE external_ref=%s',(uri,)).fetchone()[0]==0



def test_overview_metadata_uses_independent_candidate_sets(database):
    with psycopg.connect(database,row_factory=dict_row) as c:
        f=seed(c,'2025-09-01','vk')
        c.execute("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid,legacy_route) VALUES('institutions',900001,%s,'/institutions/900001')",(f['institution'],))
        # A first observation within six minutes qualifies for legacy's zero
        # baseline. Completeness alone never qualifies a late first snapshot.
        first_published=f['observed']-timedelta(minutes=5)
        c.execute("UPDATE ingest.publication SET history_completeness='complete',published_at=%s WHERE id=%s",(first_published,f['publication']))
        for index in range(10):
            selected=dict(f)
            if index:
                selected['publication']=uuid4()
                c.execute("INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,created_at,publication_type,history_completeness) VALUES(%s,%s,%s,%s,%s,'post','complete')",(selected['publication'],f['account'],first_published,f['observed'],f['observed']))
            insert(c,selected,reactions=2 if index==0 else None,reactions_quality='rounded',shares=None,shares_quality='invalid',age_seconds=300)
        revision=c.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES('ingestion',%s,%s) RETURNING id",(uuid4(),f['observed'])).fetchone()['id']
        c.execute('SELECT analytics.rebuild_core_projections(%s)',(revision,))
        row=c.execute("SELECT total_views,total_reactions,aggregate_metadata FROM analytics.legacy_overview_card WHERE entity_id=%s AND platform='vk' AND period_key='1d'",(f['institution'],)).fetchone()
        assert row['total_views']==100 and row['total_reactions']==2
        views,reactions=row['aggregate_metadata']['views:0'],row['aggregate_metadata']['reactions:0']
        assert views['sampleSize']==10 and views['coverage']==1 and views['quality']=='exact'
        assert reactions['sampleSize']==1 and reactions['coverage']==0.1 and reactions['quality']=='rounded'
        c.rollback()
