"""Independent original Python period formulas versus actual target projections."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import timedelta
from pathlib import Path

import psycopg
from app.config import Settings
from app.database import Database
from app.platform_analytics import platform_activity_cards
from migration.bridge.fixture import FIXTURE_ANCHOR
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource
from migration.bridge.target import PostgresTarget


def verify(destination: Path, dsn: str, *, prepare_only: bool = False) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / "period-source.sqlite"
    database = Database(source)
    database.migrate()
    anchor = FIXTURE_ANCHOR
    cases = (
        ("complete-late-single", 3*86400, True, False, ((3600,1000,50,None),)),
        ("incomplete-early-at-limit", 2*86400, False, False, ((360,7,1,0),)),
        ("forced-early", 2*86400, True, True, ((300,11,2,0),)),
        ("late-interval", 2*86400, True, False, ((3600,10,4,0),(7200,16,None,2))),
        ("window-first-not-lifetime-first", 2*86400, True, False,
            ((60,1,1,0),(46*3600,10,3,0),(47*3600,20,5,2))),
        ("previous-window", 10*86400, False, False, ((60,12,2,0),(2*86400,20,3,1))),
        ("open-left-boundary", 25*3600, True, False, ((3600,100,10,0),(24*3600,120,12,1))),
    )
    for platform in ("vk", "max", "rutube"):
        for name, age, complete, forced, points in cases:
            institution = database.add_institution(f"{platform}-{name}", name)
            account = database.add_platform_account(institution, platform, f"{platform}-{name}",
                title=name, url=f"https://example.org/{platform}/{name}", access_mode="public_api")
            published = anchor-timedelta(seconds=age)
            publication = database.upsert_platform_post(account,name,published,published,"post",
                f"https://example.org/{platform}/{name}/1",{},history_complete=complete)
            for seconds, views, reactions, comments in points:
                database.insert_platform_snapshot(publication,published+timedelta(seconds=seconds),seconds,60,
                    views_count=views,reactions_count=reactions,comments_count=comments,shares_count=None,raw={})
            if forced:
                with database.connect() as connection:
                    connection.execute("UPDATE platform_posts SET history_complete=0,history_forced_incomplete=1 WHERE id=?",(publication,))
    with database.connect() as connection:
        for table,column in (("schema_migrations","applied_at"),("institutions","created_at"),("platform_accounts","added_at"),
            ("platform_posts","created_at"),("platform_snapshots","created_at")):
            connection.execute(f"UPDATE {table} SET {column}=?",(anchor.isoformat(),))
    settings = Settings(telegram_api_id=None,telegram_api_hash=None,telegram_session_path=destination/"session",
        database_path=source,initial_channels=(),poll_interval_minutes=60,track_post_for_hours=336,
        complete_history_max_first_age_minutes=6,jump_min_abs=100,jump_min_ratio=5,
        web_host="127.0.0.1",web_port=8080,display_timezone="Europe/Moscow",log_path=destination/"legacy.log",
        discovery_limit=200,discovery_overlap=20)
    expected=[]
    for platform in ("vk","max","rutube"):
        for period,duration in (("3h",timedelta(hours=3)),("1d",timedelta(days=1)),
                ("7d",timedelta(days=7)),("30d",timedelta(days=30))):
            for card in platform_activity_cards(database,settings,platform,anchor-duration,anchor-2*duration,anchor):
                if not card["accounts"]: continue
                fields={key:card[key] for key in ("activity_post_count","total_post_count","post_count")}
                for metric in ("views","reactions","comments","shares"):
                    fields.update({key:card[key] for key in (f"total_{metric}",f"median_{metric}",
                        f"delta_total_{metric}",f"delta_median_{metric}")})
                expected.append({"platform":platform,"period":period,"legacyId":card["institution"]["id"],"fields":fields})
    frozen=destination/"period-frozen.sqlite"
    with sqlite3.connect(source) as original,sqlite3.connect(frozen) as snapshot: original.backup(snapshot)
    os.utime(frozen,(anchor.timestamp(),anchor.timestamp()))
    with PostgresTarget(dsn) as target:
        _,report=BridgeService(BridgeOptions(frozen,"legacy-first-window-age",batch_size=20),LegacySource(frozen),target,
            snapshot_kind="fixture").run()
        assert report["gate"]["status"]=="pass",report["mismatches"]
    result={"status":"prepared","sourceSha256":hashlib.sha256(frozen.read_bytes()).hexdigest(),"anchor":anchor.isoformat(),
        "firstAgeLimitSeconds":360,"scenarios":len(cases)*3,"cardCases":len(expected),"metricCases":len(expected)*8,
        "oracle":"app.platform_analytics.platform_activity_cards","cases":expected}
    (destination/"period-oracle.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result if prepare_only else verify_existing(destination,dsn)


def verify_existing(destination: Path, dsn: str) -> dict:
    result=json.loads((destination/"period-oracle.json").read_text())
    expected=result["cases"]
    names={"activity_post_count":"activity_publication_count","total_post_count":"total_publication_count","post_count":"new_publication_count"}
    with psycopg.connect(dsn,autocommit=True) as connection:
        for item in expected:
            columns=[names.get(field,field) for field in item["fields"]]
            row=connection.execute("SELECT "+",".join(columns)+" FROM analytics.legacy_overview_card WHERE platform=%s AND period_key=%s AND legacy_id=%s",
                (item["platform"],item["period"],item["legacyId"])).fetchone()
            assert row is not None
            actual=dict(zip(item["fields"],row))
            assert actual==item["fields"],(item,actual)
            for metric in ("views","reactions","comments","shares"):
                for aggregation,field in (("sum",f"total_{metric}"),("median",f"median_{metric}")):
                    value=connection.execute("""SELECT metrics.value FROM analytics.institution_period_metrics metrics
                        JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=metrics.institution_id AND alias.entity_type='institutions'
                        WHERE metrics.platform=%s AND metrics.period_key=%s AND alias.legacy_id=%s AND metrics.metric_key=%s AND metrics.aggregation=%s""",
                        (item["platform"],item["period"],item["legacyId"],metric,aggregation)).fetchone()
                    assert value is not None and value[0]==item["fields"][field],(item,metric,aggregation,value)
        revision=connection.execute("SELECT max(dataset_revision_id) FROM analytics.projection_state").fetchone()[0]
        # Replacing a published projection is detectable independently of map hashes.
        connection.execute("UPDATE analytics.legacy_overview_card SET total_views=999999 WHERE platform='vk' AND period_key='7d'")
        assert connection.execute("SELECT count(*) FROM analytics.legacy_overview_card WHERE platform='vk' AND period_key='7d' AND total_views=999999").fetchone()[0]>0
        connection.execute("SELECT analytics.rebuild_core_projections(%s)",(revision,))
        assert connection.execute("SELECT count(*) FROM analytics.legacy_overview_card WHERE total_views=999999").fetchone()[0]==0
        connection.execute("BEGIN")
        try:
            try:
                with connection.transaction():
                    connection.execute("INSERT INTO analytics.legacy_period_policy VALUES(%s,60,'retroactive must fail',now())",(revision,))
                raise AssertionError("Retroactive policy accepted")
            except psycopg.errors.CheckViolation: pass
            future=connection.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id,committed_at) VALUES('configuration',gen_random_uuid(),%s) RETURNING id",(result["anchor"],)).fetchone()[0]
            connection.execute("INSERT INTO analytics.legacy_period_policy VALUES(%s,60,'test next revision',now())",(future,))
            connection.execute("SELECT analytics.rebuild_core_projections(%s)",(future,))
            assert connection.execute("SELECT total_views FROM analytics.legacy_overview_card WHERE platform='vk' AND period_key='7d' AND legacy_id=2").fetchone()[0] is None
            assert connection.execute("SELECT analytics.legacy_period_first_age_limit(%s),analytics.legacy_period_first_age_limit(%s)",(revision,future)).fetchone()==(360,60)
        finally: connection.rollback()
    result["status"]="pass"
    result["configurationRevisionPinning"]="pass"
    (destination/"period-oracle.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--prepare-only",action="store_true");parser.add_argument("--verify-existing",action="store_true")
    arguments=parser.parse_args();dsn=os.environ["MRANKED_LEGACY_CSV_DSN"]
    result=verify_existing(arguments.output,dsn) if arguments.verify_existing else verify(arguments.output,dsn,prepare_only=arguments.prepare_only)
    print(json.dumps(result,ensure_ascii=False))
