"""Original disabled-account period values, independently read from frozen SQLite."""
from contextlib import closing
from datetime import timedelta
import argparse
import json
import os
from pathlib import Path
import sqlite3

import psycopg
from app.database import Database
from app.clock import CallableUtcClock
from app.web.app import create_app
from migration.bridge.fixture import FIXTURE_ANCHOR
from migration.bridge.model import BridgeOptions
from migration.bridge.projection_reconciliation import ReadOnlyLegacyDatabase,_settings,_source_period_metrics,_target_period_metrics
from migration.bridge.reconciliation import compare_rows
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource,create_online_backup,sha256_file
from migration.bridge.target import PostgresTarget


def prepare(output,dsn):
    output.mkdir(parents=True,exist_ok=True)
    live=output/"live.sqlite";database=Database(live);database.migrate()
    anchor=FIXTURE_ANCHOR;published=anchor-timedelta(days=40)
    for platform in ("vk","max","rutube"):
        for variant in ("disabled","mixed","empty"):
            institution=database.add_institution(platform+" "+variant,variant)
            for factor in ((1,2) if variant=="mixed" else (1,)):
                account=database.add_platform_account(institution,platform,platform+variant+str(factor),
                    title=variant,url="http://example.org/"+platform+variant,access_mode="public_api")
                if variant!="empty":
                    post=database.upsert_platform_post(account,str(account),published,published,"post",
                        "https://example.org/"+str(account),{},history_complete=False)
                    for hours,views,reactions in ((31*24,10,1),(29*24,20,2),(8*24,50,5),(6*24,80,8),
                            (2*24,100,10),(20,130,13),(4,150,15),(2,160,16),(1,180,18)):
                        at=anchor-timedelta(hours=hours)
                        database.insert_platform_snapshot(post,at,int((at-published).total_seconds()),60,
                            views_count=views*factor,reactions_count=reactions*factor,comments_count=0,shares_count=None,raw={})
                if factor==1:
                    with closing(sqlite3.connect(live)) as c,c:
                        c.execute("UPDATE platform_accounts SET enabled=0 WHERE id=?",(account,))
    telegram=database.add_institution("Disabled Telegram","TG")
    channel=database.add_channel("disabled_history_policy",telegram)
    with closing(sqlite3.connect(live)) as c,c:
        c.execute("UPDATE channels SET enabled=0 WHERE id=?",(channel,))
        c.execute("UPDATE platform_accounts SET enabled=0 WHERE platform='telegram'")
        for table,column in (("institutions","created_at"),("channels","added_at"),("platform_accounts","added_at"),
                ("platform_posts","created_at"),("platform_snapshots","created_at")):
            c.execute(f"UPDATE {table} SET {column}=?",(anchor.isoformat(),))
    frozen=output/"frozen.sqlite";create_online_backup(live,frozen)
    os.utime(frozen,(anchor.timestamp(),anchor.timestamp()))
    app=create_app(_settings(frozen,output,360),ReadOnlyLegacyDatabase(frozen),clock=CallableUtcClock(lambda:anchor))
    expected=[{"key":key,"value":body["value"]} for key,body in _source_period_metrics(app)]
    with PostgresTarget(dsn) as target:
        _,report=BridgeService(BridgeOptions(frozen,"disabled-period-history",batch_size=100),LegacySource(frozen),target,snapshot_kind="fixture").run()
        assert report["gate"]["status"]=="pass",report["mismatches"]
    proof={"status":"prepared","sourceSha256":sha256_file(frozen),"anchor":anchor.isoformat(),"cases":expected}
    (output/"disabled-period-oracle.json").write_text(json.dumps(proof,indent=2))


def verify(output,dsn):
    proof=json.loads((output/"disabled-period-oracle.json").read_text());source=output/"frozen.sqlite"
    assert sha256_file(source)==proof["sourceSha256"]
    expected=[(row["key"],{"value":row["value"]}) for row in proof["cases"]]
    with psycopg.connect(dsn) as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        revision=connection.execute("SELECT max(dataset_revision_id) FROM analytics.projection_state WHERE status='ready'").fetchone()[0]
        compared=compare_rows(expected,_target_period_metrics(connection,revision))
        assert compared["expected"]==compared["actual"],compared
        assert connection.execute("SELECT count(*) FROM analytics.institution_period_metrics WHERE platform='telegram'").fetchone()[0]==0
        definition=connection.execute("SELECT pg_get_functiondef('analytics.rebuild_core_projections_v5(bigint)'::regprocedure)").fetchone()[0]
        assert "catalog.visible_platform_account" in definition and "ingest.visible_publication" in definition
    with psycopg.connect(dsn,autocommit=True) as connection:
        with connection.transaction(force_rollback=True):
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            assert connection.execute("DELETE FROM analytics.institution_period_metrics WHERE platform='rutube' AND period_key='7d' AND value>0").rowcount>0
            bad=compare_rows(expected,_target_period_metrics(connection,revision))
            assert bad["expected"]!=bad["actual"]
    proof.update(status="pass",comparison=compared,revision=revision,missingPopulatedRowsDetected=True,
        telegramEnabledPolicyUnchanged=True,visibilityPreserved=True,sourceUnchanged=sha256_file(source)==proof["sourceSha256"])
    (output/"disabled-period-oracle.json").write_text(json.dumps(proof,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);parser.add_argument("--verify",action="store_true")
    args=parser.parse_args();(verify if args.verify else prepare)(args.output,os.environ["MRANKED_LEGACY_CSV_DSN"])
