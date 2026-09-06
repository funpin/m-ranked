"""Real collector → CSV → reverse SQLite → bridge byte parity on a local clone."""
from __future__ import annotations
from contextlib import closing
import csv
import hashlib
import io
import json
import os
import sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from fastapi.testclient import TestClient
from app.config import Settings
from app.database import Database
from migration.legacy_reference import create_app
from collector_target.evidence import ImmutableEvidenceStore
from collector_target.model import CollectionContext,Platform,RawPublication,RawCollectionBatch
from collector_target.normalize import CanonicalNormalizer
from collector_target.repository import PostgresCollectorRepository
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource,create_online_backup
from migration.bridge.target import PostgresTarget
from operations.reverse_sync.journal import ReverseSyncJournal
from operations.reverse_sync.postgres import PostgresReverseSource
from operations.reverse_sync.service import ReverseSyncService
from operations.reverse_sync.sqlite_target import LegacySqliteTarget


def native_round_trip(destination:Path,admin_dsn:str)->dict:
    destination=destination.resolve()
    values=conninfo_to_dict(admin_dsn)
    collector_dsn=make_conninfo(**(values|{'user':'collector_ingest','password':os.environ['MRANKED_LEGACY_CSV_COLLECTOR_PASSWORD']}))
    bridge_dsn=make_conninfo(**(values|{'user':'migration_bridge','password':os.environ['MRANKED_LEGACY_CSV_BRIDGE_PASSWORD']}))
    source=destination/'frozen.sqlite'
    reverse=destination/'reverse.sqlite'
    create_online_backup(source,reverse)
    # This separate clone becomes a live legacy reverse-sync destination. The
    # accepted frozen source remains a standalone artifact with its original SHA.
    with closing(sqlite3.connect(reverse)) as target:
        assert target.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    namespace='legacy-csv-http-golden'
    service=ReverseSyncService(PostgresReverseSource(bridge_dsn,namespace),
        LegacySqliteTarget(reverse,namespace,min_free_bytes=0),ReverseSyncJournal(destination/'native-journal.sqlite'))
    assert service.preflight()['status']=='pass'
    service.start(rollback_window_hours=24,operator='local-csv-test',ticket='CSV-NATIVE-ROUNDTRIP')
    repository=PostgresCollectorRepository(collector_dsn,evidence_store=ImmutableEvidenceStore(destination/'native-evidence'))
    base=(datetime(2025,8,1,12,tzinfo=timezone.utc)
        if os.environ.get('MRANKED_LEGACY_CSV_OLD_FIXTURE')=='1' else datetime.now(timezone.utc))
    latest_revision=None
    for platform in Platform:
        account=next(iter(repository.enabled_accounts(platform,'all')))
        external='m:90001' if platform==Platform.TELEGRAM else 'csv-native-90001'
        url=f'https://t.me/{account.current_username}/90001' if platform==Platform.TELEGRAM else f'https://example.org/{platform.value}/90001'
        for step in range(2):
            observed=base+timedelta(minutes=5*step)
            context=CollectionContext.create(platform,'csv-native-roundtrip','csv-native-v1',observed,observed)
            raw=RawPublication(external,base-timedelta(hours=2),base-timedelta(hours=2)+timedelta(minutes=5),observed,observed,'post',
                {'views':10+step*7,'reactions':3+step,'comments':0 if step==0 else None,'shares':None if platform==Platform.TELEGRAM else step},
                {'provider':'csv-roundtrip','text':'Unicode, "quote"\r\nline','access_token':'[REDACTED]'},
                public_url=url,reaction_breakdown={'👍':3+step} if platform==Platform.TELEGRAM else {})
            batch=CanonicalNormalizer().normalize(RawCollectionBatch(account,None,(raw,),'csv-native','1'),context)
            repository.start_run(context)
            assert repository.begin_account(context,account,observed)
            result=repository.persist_account_batch(batch)
            assert result.snapshot_count==1
            latest_revision=result.revision_id
            assert repository.finish_run(context,observed).status.value=='succeeded'
    with psycopg.connect(admin_dsn,autocommit=True) as connection:
        connection.execute('SELECT analytics.rebuild_core_projections(%s)',(latest_revision,))
        assert connection.execute("SELECT count(*) FROM analytics.legacy_native_export_lexeme").fetchone()[0]==8
        assert connection.execute("SELECT count(*) FROM analytics.legacy_export_row WHERE blocked_reason IS NOT NULL").fetchone()[0]==0
        before={}
        manifest=json.loads((destination/'manifest.json').read_text())
        for item in manifest['cases'][:10]:
            kind,platform=item['kind'],item['platform']
            header=next(csv.reader(io.StringIO((destination/item['file']).read_text())))
            stream=io.StringIO(newline='')
            writer=csv.writer(stream)
            writer.writerow(header)
            rows=connection.execute("""SELECT cells FROM analytics.legacy_export_row WHERE kind=%s AND namespace=%s
                AND (%s='all' OR platform::text=%s) ORDER BY ordinal""",
                (kind,'telegram' if platform=='telegram' else 'generic',platform,platform))
            writer.writerows(row[0] for row in rows)
            before[(kind,platform)]=stream.getvalue().encode()
    drained=service.drain(operator='local-csv-test',ticket='CSV-NATIVE-ROUNDTRIP')
    assert drained['status']=='drained'
    assert service.verify()['status']=='verified'
    assert service.stop()['status']=='stopped'
    cfg=Settings(telegram_api_id=None,telegram_api_hash=None,telegram_session_path=destination/'native-session',database_path=reverse,
        initial_channels=(),poll_interval_minutes=60,track_post_for_hours=336,complete_history_max_first_age_minutes=90,
        jump_min_abs=15,jump_min_ratio=2.0,web_host='127.0.0.1',web_port=8080,display_timezone='Europe/Moscow',
        log_path=destination/'native.log',discovery_limit=200,discovery_overlap=20)
    client=TestClient(create_app(cfg,Database(reverse)))
    cases=[]
    for (kind,platform),expected in before.items():
        response=client.get(f'/export/{kind}.csv',params={'platform':platform})
        assert response.status_code==200
        if response.content!=expected:
            import difflib
            difference=''.join(difflib.unified_diff(expected.decode().splitlines(keepends=True),
                response.content.decode().splitlines(keepends=True),fromfile='target',tofile='legacy'))
            raise AssertionError((kind,platform,'native → legacy CSV bytes differ',difference))
        filename=f'native-{kind}-{platform}.csv'
        (destination/filename).write_bytes(response.content)
        cases.append({'kind':kind,'platform':platform,'file':filename,'sha256':hashlib.sha256(expected).hexdigest(),
            'contentType':response.headers['content-type'],'disposition':response.headers['content-disposition']})
    client.close()
    exported=destination/'native-roundtrip.sqlite'
    create_online_backup(reverse,exported)
    with PostgresTarget(bridge_dsn) as target:
        _,report=BridgeService(BridgeOptions(exported,namespace,batch_size=2),LegacySource(exported),target,snapshot_kind='catch_up').run()
        assert report['gate']['status']=='pass',report['mismatches']
    result={'cases':cases,'sourceSha256':hashlib.sha256(exported.read_bytes()).hexdigest(),'attribution':'target-generated-v1',
        'nativeSnapshots':8,'platforms':[platform.value for platform in Platform],'reverseStatus':'verified'}
    (destination/'native-manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
