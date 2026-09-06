"""Fresh original-formula oracle plus direct projection tamper detection."""
from __future__ import annotations
import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from app.database import Database
from migration.bridge.fixture import FIXTURE_ANCHOR
from migration.bridge.model import BridgeOptions,stable_uuid
from migration.bridge.source import LegacySource
from migration.bridge.service import BridgeService
from migration.bridge.target import PostgresTarget
from migration.bridge.projection_reconciliation import verify_projections,ReadOnlyLegacyDatabase


def run(destination:Path,dsn:str):
    destination.mkdir(parents=True,exist_ok=True)
    source=destination/'source.sqlite';database=Database(source);database.migrate()
    institution=database.add_institution('Projection oracle university','Oracle')
    database.add_institution('No accounts','Empty')
    channel=database.add_channel('projection_oracle',institution)
    published=FIXTURE_ANCHOR-timedelta(days=21)
    for platform in ('telegram','vk','max','rutube'):
        account=channel if platform=='telegram' else database.add_platform_account(institution,platform,'oracle-'+platform,
            title='Oracle '+platform,url='https://example.org/'+platform,access_mode='public_api')
        for variant in (0,1):
            external=900+variant
            if platform=='telegram':
                publication=database.add_post(channel,f'message:{external}',[external],None,published,published,
                    variant*3600,variant==0,'text',False)
            else:
                publication=database.upsert_platform_post(account,str(external),published,published,'post',
                    'https://example.org/'+platform+'/'+str(external),{},history_complete=variant==0)
            for hour in (0,1,24,48,72,168,336):
                if hour<variant:continue
                reactions=hour+variant*5+1;views=10*(hour+variant*5+1)
                if platform=='telegram':
                    database.insert_snapshot(publication,published+timedelta(hours=hour),hour*3600,reactions,
                        {'👍':reactions},{},60,10000,5,comments_count=0,views_count=views)
                else:
                    database.insert_platform_snapshot(publication,published+timedelta(hours=hour),hour*3600,60,
                        views_count=views,reactions_count=reactions,comments_count=0,shares_count=0,raw={})
    with database.connect() as connection:
        connection.execute('UPDATE posts SET baseline_from_publication=1 WHERE history_complete=1')
        for table,column in (('schema_migrations','applied_at'),('institutions','created_at'),('channels','added_at'),
                ('platform_accounts','added_at'),('posts','created_at'),('platform_posts','created_at'),
                ('reaction_snapshots','created_at'),('platform_snapshots','created_at')):
            connection.execute(f'UPDATE {table} SET {column}=?',(FIXTURE_ANCHOR.isoformat(),))
    frozen=destination/'frozen.sqlite'
    with sqlite3.connect(source) as original,sqlite3.connect(frozen) as snapshot:original.backup(snapshot)
    os.utime(frozen,(FIXTURE_ANCHOR.timestamp(),FIXTURE_ANCHOR.timestamp()))
    with PostgresTarget(dsn) as target:
        _,report=BridgeService(BridgeOptions(frozen,'projection-independent',batch_size=20,verify_projections=True),LegacySource(frozen),target,snapshot_kind='fixture').run()
        assert report['gate']['status']=='pass',report['mismatches']
    sha=hashlib.sha256(frozen.read_bytes()).hexdigest()
    arguments={'source_name':'projection-independent','expected_sha256':sha}
    with ReadOnlyLegacyDatabase(frozen).connect() as source_connection:
        try:source_connection.execute("UPDATE institutions SET name='forbidden'")
        except sqlite3.OperationalError:pass
        else:raise AssertionError('Source oracle connection writable')
    with psycopg.connect(dsn,autocommit=True) as connection:
        target=PostgresTarget(dsn);target.connection=connection
        service=BridgeService(BridgeOptions(frozen,'projection-independent',batch_size=20,verify_projections=True),
            LegacySource(frozen),target,snapshot_kind='fixture')
        baseline=verify_projections(frozen,connection,**arguments)
        assert baseline['status']=='pass',baseline
        assert service.reconcile()['gate']['status']=='pass'
        tamper_cases={
            'overview':"UPDATE analytics.legacy_overview_card SET total_views=coalesce(total_views,0)+1 WHERE platform='vk' AND period_key='7d' AND legacy_id=1",
            'periodMetrics':"UPDATE analytics.institution_period_metrics SET value=coalesce(value,0)+1 WHERE platform='vk' AND period_key='7d' AND metric_key='views' AND aggregation='sum'",
            'hourly':"UPDATE analytics.comparison_publication_hourly SET reactions_count=reactions_count+13 WHERE platform='vk' AND hour_offset=24",
            'membership':"DELETE FROM analytics.comparison_cohort_member WHERE cohort_id=(SELECT id FROM analytics.comparison_cohort WHERE platform='vk' AND horizon_seconds=86400 AND (filter_definition->>'include_partial')::boolean=false LIMIT 1)"}
        detected={}
        for name,sql in tamper_cases.items():
            with connection.transaction():
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                assert connection.execute(sql).rowcount>0
                changed=verify_projections(frozen,connection,**arguments)
                expected_check=name if name in ('overview','periodMetrics') else 'fixedCohort'
                assert changed['status']=='fail' and changed['checks'][expected_check]['status']=='fail',(name,changed)
                overall=service.reconcile()
                assert overall['gate']['status']=='fail'
                assert any(item['check']=='derived_projection_parity' and item['critical'] for item in overall['mismatches'])
                detected[name]=changed['checks'][expected_check]['changedKeysSample']
                raise psycopg.Rollback()
        final=verify_projections(frozen,connection,**arguments)
        assert final['checks']==baseline['checks']
        assert hashlib.sha256(frozen.read_bytes()).hexdigest()==sha
        with connection.transaction():
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            connection.execute("""INSERT INTO migration.source_preservation(id,source_namespace,current_batch_id,
                prior_source_sha256,facts_sha256,operator,ticket,reason)
                SELECT gen_random_uuid(),%s,id,source_sha256,repeat('0',64),
                    'local-test','PROJECTION-PRESERVED','assert unrepresented preserved source blocks oracle'
                FROM migration.import_batch WHERE source_name='projection-independent' LIMIT 1""",
                (stable_uuid('m-ranked-bridge','source_namespace',{'name':'projection-independent'}),))
            unsupported=verify_projections(frozen,connection,**arguments)
            assert unsupported['status']=='fail' and unsupported['errorCode']=='PRESERVED_HISTORY_ORACLE_RECONSTRUCTION_REQUIRED'
            raise psycopg.Rollback()
    bridge_dsn=make_conninfo(**(conninfo_to_dict(dsn)|{'user':'migration_bridge','password':os.environ['MRANKED_LEGACY_CSV_BRIDGE_PASSWORD']}))
    with psycopg.connect(bridge_dsn,autocommit=True) as connection:
        bridge=verify_projections(frozen,connection,**arguments)
        assert bridge['checks']==baseline['checks']
    result=baseline|{'tamperDetectedWithoutRebuild':detected,'sourceSqliteWriteDenied':True,
        'preservedSourceFailsClosed':True,'migrationBridgeRole':'pass','overallNoGoOnEachTamper':True}
    (destination/'projection-oracle.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    arguments=parser.parse_args();print(json.dumps(run(arguments.output,os.environ['MRANKED_LEGACY_CSV_DSN']),ensure_ascii=False))
