"""Collector buffer preserves scheduler semantics and full undelivered facts."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib.util
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from collector_target.model import (
    AccountRef, CollectionContext, HistoryCompleteness, Platform,
    RawCollectionBatch, RawPublication,
)
from collector_target.normalize import CanonicalNormalizer
from collector_target.repository import PostgresCollectorRepository
from collector_target.transfer import (
    InProcessTransport, PostgresDataAdapter, PostgresTransferProducer,
)


@pytest.fixture
def db():
    dsn = os.getenv("MRANKED_TEST_POSTGRES_ADMIN_DSN")
    if not dsn:
        pytest.skip("isolated PostgreSQL not configured")
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as connection:
        yield connection, dsn


def account(db):
    connection, _ = db
    owner, identity = uuid4(), uuid4()
    result = AccountRef(identity, owner, Platform.VK, "working_"+identity.hex, "official_api")
    connection.execute("INSERT INTO catalog.institution(id,canonical_name) VALUES(%s,%s)", (owner,"working "+str(owner)))
    connection.execute("INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode) VALUES(%s,%s,'vk',%s,'official_api')", (identity,owner,result.canonical_external_id))
    return result


def batch(context, owner, published, observed, metrics):
    raw = RawCollectionBatch(owner, None, (RawPublication(
        "wall:-1_100", published, observed, observed, observed, "post",
        metrics, {"kind":"working-set-test"},
        history_completeness=HistoryCompleteness.COMPLETE,
    ),), "working-set", "1")
    return CanonicalNormalizer().normalize(raw, context)


def seed(connection):
    path=Path(__file__).parents[1]/"operations/scripts/seed-collector-working-set.py"
    spec=importlib.util.spec_from_file_location("working_set_seed",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.seed(connection,batch_size=20)


def test_seed_preserves_last_24_null_zero_and_tracking_state(db):
    connection, dsn = db
    owner = account(db)
    now=datetime.now(timezone.utc).replace(microsecond=0)
    published=now-timedelta(days=29)
    regular=PostgresCollectorRepository(dsn,deployment_profile="b",transfer_producer_id="seed-"+owner.id.hex)
    try:
        for index in range(28):
            observed=now-timedelta(hours=30-index)
            context=CollectionContext.create(Platform.VK,"seed-"+owner.id.hex,"seed-v1",observed,observed)
            regular.start_run(context)
            regular.begin_account(context,owner,observed)
            regular.persist_account_batch(batch(context,owner,published,observed,
                {"views":100+index,"reactions":None,"comments":0,"shares":None}))
        before=regular.metric_ever_positive(owner,["wall:-1_100"])
        tracked=regular.tracked_publications(owner,published_after=now-timedelta(days=30),limit=100)
        seed(connection)
        compact=PostgresCollectorRepository(dsn,deployment_profile="b",transfer_producer_id="seed-"+owner.id.hex,compact_working_set=True)
        try:
            compact.assert_schema_contract()
            assert compact.metric_ever_positive(owner,["wall:-1_100"])==before
            assert compact.tracked_publications(owner,published_after=now-timedelta(days=30),limit=100)==tracked
            assert connection.execute("SELECT count(*) FROM ingest.collector_publication_working_set WHERE publication_id=%s",(tracked[0].id,)).fetchone()[0]==24
            assert connection.execute("SELECT count(*) FROM ingest.publication_metric_snapshot WHERE publication_id=%s",(tracked[0].id,)).fetchone()[0]==28
        finally: compact.close()
    finally: regular.close()


def test_pruning_buffer_keeps_full_payload_until_receiver_applies(db):
    connection, dsn=db
    owner=account(db)
    now=datetime.now(timezone.utc).replace(microsecond=0)
    producer="delivery-"+owner.id.hex
    connection.execute("INSERT INTO ops_and_admin.collector_working_set_seed(singleton,completed_at) VALUES(true,now()) ON CONFLICT(singleton) DO UPDATE SET completed_at=now()")
    source=PostgresCollectorRepository(dsn,deployment_profile="b",transfer_producer_id=producer,compact_working_set=True)
    receiver=PostgresCollectorRepository(dsn)
    try:
        publication_id=None
        for index in range(27):
            observed=now-timedelta(hours=30-index)
            context=CollectionContext.create(Platform.VK,producer,"delivery-v1",observed,observed)
            source.start_run(context)
            source.begin_account(context,owner,observed)
            value=batch(context,owner,now-timedelta(days=29),observed,
                        {"views":100+index,"reactions":index+1,"comments":0,"shares":None})
            value=replace(value,publications=tuple(replace(p,snapshot=replace(p.snapshot,reaction_breakdown={"like":index+1})) for p in value.publications))
            if index==0:
                with pytest.raises(ValueError,match="transactional payload sealing"),connection.transaction():
                    source.persist_account_batch_in_transaction(connection,value)
            result=source.persist_account_batch(value)
            assert result.revision_id is None
            publication_id=value.publications[0].id
        assert connection.execute("SELECT count(*) FROM ingest.collector_publication_working_set WHERE publication_id=%s",(publication_id,)).fetchone()[0]==24
        assert connection.execute("SELECT count(*) FROM ingest.publication_metric_snapshot WHERE publication_id=%s",(publication_id,)).fetchone()[0]==0
        assert connection.execute("SELECT count(*) FROM ingest.publication_availability_event WHERE publication_id=%s",(publication_id,)).fetchone()[0]==0
        assert connection.execute("SELECT status FROM ingest.publication_availability_state WHERE publication_id=%s",(publication_id,)).fetchone()[0]=='present'
        assert connection.execute("SELECT count(*) FROM ops_and_admin.transfer_outbox WHERE producer_id=%s AND state='sealed'",(producer,)).fetchone()[0]==27
        sender=PostgresTransferProducer(source,InProcessTransport(PostgresDataAdapter(receiver)))
        assert sender.deliver_pending(limit=100)>=27
        assert connection.execute("SELECT count(*) FROM ops_and_admin.transfer_outbox WHERE producer_id=%s AND state='acknowledged'",(producer,)).fetchone()[0]==27
        assert connection.execute("SELECT count(*) FROM ingest.publication_metric_snapshot WHERE publication_id=%s",(publication_id,)).fetchone()[0]==27
        assert connection.execute("SELECT max(views_count),sum(reactions_count) FROM ingest.publication_metric_snapshot WHERE publication_id=%s",(publication_id,)).fetchone()==(126,378)
        assert connection.execute("SELECT count(*) FROM ingest.reaction_breakdown r JOIN ingest.publication_metric_snapshot s ON (s.published_month,s.id)=(r.snapshot_published_month,r.snapshot_id) WHERE s.publication_id=%s",(publication_id,)).fetchone()[0]==27
        assert len(source.tracked_publications(owner,published_after=now-timedelta(days=30),limit=100))==1
    finally:
        source.close(); receiver.close()


def test_compact_requires_transport_and_seed(db):
    _,dsn=db
    with pytest.raises(ValueError,match="durable transfer"):
        PostgresCollectorRepository(dsn,deployment_profile="b",compact_working_set=True)
    with pytest.raises(ValueError,match="profile b"):
        PostgresCollectorRepository(dsn,transfer_producer_id="test",compact_working_set=True)


def test_31_day_expiry_never_expires_undelivered_history(db):
    connection,dsn=db
    owner=account(db)
    now=datetime.now(timezone.utc).replace(microsecond=0)
    observed=now-timedelta(days=32)
    producer="expired-"+owner.id.hex
    context=CollectionContext.create(Platform.VK,producer,"expired-v1",observed,observed)
    source=PostgresCollectorRepository(dsn,deployment_profile="b",transfer_producer_id=producer,compact_working_set=True)
    try:
        source.start_run(context)
        source.begin_account(context,owner,observed)
        value=batch(context,owner,now-timedelta(days=33),observed,
                    {"views":123,"reactions":10,"comments":0,"shares":None})
        source.persist_account_batch(value)
        assert connection.execute("SELECT count(*) FROM ingest.collector_publication_working_set WHERE publication_id=%s",(value.publications[0].id,)).fetchone()[0]==0
        assert connection.execute("SELECT count(*) FROM ops_and_admin.transfer_outbox WHERE producer_id=%s AND state='sealed'",(producer,)).fetchone()[0]==1
        assert connection.execute("SELECT count(*) FROM ingest.publication WHERE id=%s",(value.publications[0].id,)).fetchone()[0]==1
    finally: source.close()


def test_full_history_drop_requires_current_generation_counts_and_independent_target(db):
    import psycopg
    connection,_=db
    with connection.transaction():
        connection.execute((Path(__file__).parents[1]/'db/migrations/pending/0048_retire_compact_collector_history.sql').read_text())
        connection.execute("SELECT set_config('mranked.deployment_profile','b',true)")
        month='1980-01-01'
        connection.execute('SELECT ops_and_admin.ensure_publication_metric_partition(%s::date)',(month,))
        stamp=connection.execute('SELECT ops_and_admin.fence_compact_collector_history(%s::date)',(month,)).fetchone()[0]
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),connection.transaction():
            connection.execute('SELECT ops_and_admin.drop_compact_collector_history(%s::date)',(month,))
        connection.execute("INSERT INTO ops_and_admin.collector_full_history_coverage VALUES(%s,%s,clock_timestamp(),%s,%s,1,0,0,'1234567890123456789',2)",(month,stamp,'0'*64,'0'*64))
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),connection.transaction():
            connection.execute('SELECT ops_and_admin.drop_compact_collector_history(%s::date)',(month,))
        connection.execute('UPDATE ops_and_admin.collector_full_history_coverage SET snapshot_rows=0,fence_at=fence_at-interval \'1 second\'')
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),connection.transaction():
            connection.execute('SELECT ops_and_admin.drop_compact_collector_history(%s::date)',(month,))
        connection.execute('UPDATE ops_and_admin.collector_full_history_coverage SET fence_at=%s,destination_system_identifier=(SELECT system_identifier::text FROM pg_control_system())',(stamp,))
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),connection.transaction():
            connection.execute('SELECT ops_and_admin.drop_compact_collector_history(%s::date)',(month,))
        connection.execute("UPDATE ops_and_admin.collector_full_history_coverage SET destination_system_identifier='1234567890123456789'")
        working_before=connection.execute('SELECT count(*) FROM ingest.collector_publication_working_set').fetchone()[0]
        assert connection.execute('SELECT ops_and_admin.drop_compact_collector_history(%s::date)',(month,)).fetchone()[0] is True
        assert connection.execute('SELECT count(*) FROM ingest.collector_publication_working_set').fetchone()[0]==working_before
        raise psycopg.Rollback()


def test_runtime_expiry_keeps_tracking_and_undelivered_context(db):
    import psycopg
    connection,dsn=db
    owner=account(db)
    now=datetime.now(timezone.utc).replace(microsecond=0)
    old=now-timedelta(days=32)
    producer='runtime-'+owner.id.hex
    context=CollectionContext.create(Platform.VK,producer,'runtime-v1',old,old)
    source=PostgresCollectorRepository(dsn,deployment_profile='b',transfer_producer_id=producer,compact_working_set=True)
    receiver=PostgresCollectorRepository(dsn)
    try:
        source.start_run(context);source.begin_account(context,owner,old)
        value=batch(context,owner,now-timedelta(days=33),old,{'views':456,'reactions':None,'comments':0,'shares':None})
        source.persist_account_batch(value)
        source.finish_run(context,old)
        connection.execute((Path(__file__).parents[1]/'db/migrations/0049_collector_runtime_retention.sql').read_text())
        with connection.transaction():
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),connection.transaction():
                connection.execute('SELECT ops_and_admin.prune_compact_collector_runtime(1000)')
            connection.execute("SELECT set_config('mranked.deployment_profile','b',true)")
            result=connection.execute('SELECT ops_and_admin.prune_compact_collector_runtime(1000)').fetchone()[0]
            assert result['account_results']>=1
            assert connection.execute('SELECT count(*) FROM ingest.collection_account_result WHERE collection_run_id=%s',(context.run_id,)).fetchone()[0]==0
            assert connection.execute('SELECT state FROM ops_and_admin.transfer_outbox WHERE producer_id=%s',(producer,)).fetchone()[0]=='sealed'
            assert connection.execute('SELECT count(*) FROM ingest.publication WHERE id=%s',(value.publications[0].id,)).fetchone()[0]==1
        # Runtime context survives expiry inside the self-contained payload.
        sender=PostgresTransferProducer(source,InProcessTransport(PostgresDataAdapter(receiver)))
        assert sender.deliver_pending(limit=100)>=1
        assert connection.execute('SELECT max(views_count) FROM ingest.publication_metric_snapshot WHERE publication_id=%s',(value.publications[0].id,)).fetchone()[0]==456
    finally: source.close();receiver.close()


def test_coverage_digest_proves_full_source_when_target_has_extra_facts(db,tmp_path):
    connection,dsn=db
    path=Path(__file__).parents[1]/'operations/scripts/digest-collector-history.py'
    spec=importlib.util.spec_from_file_location('coverage_v2',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    owner=account(db);now=datetime.now(timezone.utc).replace(microsecond=0)
    published=now-timedelta(days=2)
    month=published.date().replace(day=1)
    cutoff=now+timedelta(minutes=1)
    writer=PostgresCollectorRepository(dsn)
    try:
        for index in range(2):
            observed=now-timedelta(hours=3-index)
            context=CollectionContext.create(Platform.VK,'coverage-'+owner.id.hex,'coverage-v1',observed,observed)
            writer.start_run(context);writer.begin_account(context,owner,observed)
            value=batch(context,owner,published,observed,{'views':900+index,'reactions':index+1,'comments':0,'shares':None})
            value=replace(value,publications=tuple(replace(p,snapshot=replace(p.snapshot,reaction_breakdown={'like':index+1})) for p in value.publications))
            writer.persist_account_batch(value)
        with connection.transaction():
            connection.execute("SET LOCAL timezone='UTC'; SET LOCAL enable_hashjoin=off; SET LOCAL enable_mergejoin=off")
            before=module.digest(connection,month,cutoff,tmp_path)
        observed=now-timedelta(hours=1)
        context=CollectionContext.create(Platform.VK,'coverage-'+owner.id.hex,'coverage-v1',observed,observed)
        writer.start_run(context);writer.begin_account(context,owner,observed)
        value=batch(context,owner,published,observed,{'views':902,'reactions':3,'comments':0,'shares':None})
        value=replace(value,publications=tuple(replace(p,snapshot=replace(p.snapshot,reaction_breakdown={'like':3})) for p in value.publications))
        writer.persist_account_batch(value)
        row=connection.execute('SELECT publication_id,sampling_bucket,source_fingerprint FROM ingest.publication_metric_snapshot WHERE publication_id=%s AND observed_at=%s',(value.publications[0].id,observed)).fetchone()
        extra=dict(zip(['publication_id','sampling_bucket','source_fingerprint'],[str(row[0]),row[1],row[2]]))
        with connection.transaction():
            connection.execute("SET LOCAL timezone='UTC'; SET LOCAL enable_hashjoin=off; SET LOCAL enable_mergejoin=off")
            after=module.digest(connection,month,cutoff,tmp_path)
            selected=module.digest(connection,month,cutoff,tmp_path,exclude_keys=[extra])
        assert after['snapshot_rows']==before['snapshot_rows']+1
        assert after['reaction_rows']==before['reaction_rows']+1
        assert after['sha256']!=before['sha256']
        assert selected==before
    finally: writer.close()


def test_coverage_lineage_equivalence_checks_every_fact_and_target_record(db,tmp_path):
    connection,dsn=db
    path=Path(__file__).parents[1]/'operations/scripts/digest-collector-history.py'
    spec=importlib.util.spec_from_file_location('coverage_lineage',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    owner=account(db);now=datetime.now(timezone.utc).replace(microsecond=0)
    month=now.date().replace(day=1);cutoff=now+timedelta(minutes=1)
    writer=PostgresCollectorRepository(dsn)
    try:
        context=CollectionContext.create(Platform.VK,'lineage-'+owner.id.hex,'lineage-v1',now,now)
        writer.start_run(context);writer.begin_account(context,owner,now)
        value=batch(context,owner,now,now,{'views':987,'reactions':1,'comments':0,'shares':None})
        writer.persist_account_batch(value)
        compare=importlib.util.spec_from_file_location('coverage_query',path.with_name('compare-retention-month.py'))
        query_module=importlib.util.module_from_spec(compare);compare.loader.exec_module(query_module)
        with connection.transaction():
            connection.execute("SET LOCAL timezone='UTC'; SET LOCAL enable_hashjoin=off; SET LOCAL enable_mergejoin=off")
            records=connection.execute(query_module.QUERY,(month,)).fetchall()
            target=next(json.loads(row[0]) for row in records if json.loads(row[0])['snapshot']['publication_id']==str(value.publications[0].id))
            source=json.loads(json.dumps(target))
            source['snapshot']['correction_sequence']=1
            source['snapshot']['correction_reason']='provider_payload_changed'
            pair={'source':source,'target':target}
            hashes=[connection.execute("SELECT encode(sha256(convert_to(%s::jsonb::text,'UTF8')),'hex')",(json.dumps(source if json.loads(row[0])==target else json.loads(row[0])),)).fetchone()[0] for row in records]
            expected=hashlib.sha256(('\n'.join(sorted(hashes))+'\n').encode()).hexdigest()
            selected=module.digest(connection,month,cutoff,tmp_path,lineage_equivalences=[pair])
            assert selected['sha256']==expected
            assert selected['snapshot_rows']==len(records)
            assert selected['reaction_rows']==sum(row[1] for row in records)
            for field in ['views_count','observed_at','context_run_id']:
                altered=json.loads(json.dumps(pair));altered['source']['snapshot'][field]='changed'
                with pytest.raises(ValueError,match='canonical facts'):
                    module.digest(connection,month,cutoff,tmp_path,lineage_equivalences=[altered])
            for field in ['evidence','reactions']:
                altered=json.loads(json.dumps(pair));altered['source'][field]={'changed':1}
                with pytest.raises(ValueError,match='canonical facts'):
                    module.digest(connection,month,cutoff,tmp_path,lineage_equivalences=[altered])
            stale=json.loads(json.dumps(pair))
            stale['source']['snapshot']['correction_sequence']=2
            stale['target']['snapshot']['correction_sequence']=2
            with pytest.raises(RuntimeError,match='target lineage changed'):
                module.digest(connection,month,cutoff,tmp_path,lineage_equivalences=[stale])
            with pytest.raises(ValueError,match='duplicate'):
                module.digest(connection,month,cutoff,tmp_path,lineage_equivalences=[pair,pair])
    finally: writer.close()
