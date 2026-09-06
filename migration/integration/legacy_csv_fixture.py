"""Independent legacy HTTP byte oracle and actual bridge fixture for Spring tests."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
from app.config import Settings
from app.database import Database
from app.web.app import create_app
from migration.bridge.fixture import FIXTURE_ANCHOR, build_golden_fixture
from migration.bridge.model import BridgeOptions
from migration.bridge.service import BridgeService
from migration.bridge.source import LegacySource
from migration.bridge.target import PostgresTarget


def produce(destination: Path, dsn: str) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    source = destination / "legacy.sqlite"
    build_golden_fixture(source, revision=2)
    with closing(sqlite3.connect(source)) as connection:
        # The source's JSON serializer spelling is observable, including whitespace,
        # non-ASCII text, quotes and embedded CRLF. It must not pass through JSONB.
        connection.execute("UPDATE platform_snapshots SET raw_json=? WHERE id=1",
            ('{ "z": [1, null], "a": "Юникод,\\r\\n\\\"цитата\\\"" }',))
        connection.execute("UPDATE institutions SET short_name=? WHERE id=1", ('  =Альфа, "университет"\r\nстрока  ',))
        connection.execute("UPDATE platform_accounts SET url='http://vk.ru/alpha_vk' WHERE platform='vk'")
        connection.execute("UPDATE reaction_snapshots SET age_seconds=1 WHERE age_seconds=3600")
        # Two equally large jumps must choose the latest point, matching the
        # legacy (post_id, measured_at DESC) index used by the scalar subquery.
        connection.execute("UPDATE reaction_snapshots SET total_reactions=24,delta_total=12,reactions_json=? WHERE age_seconds=7200",
            ('{"❤": 4, "👍": 20}',))
        # Explicit latest NULL must not fall back to an older measured value.
        connection.execute("UPDATE platform_snapshots SET comments_count=NULL WHERE id=(SELECT max(id) FROM platform_snapshots)")
        if os.environ.get("MRANKED_LEGACY_CSV_OLD_FIXTURE")=="1":
            # Archive tests use actual retained partitions old enough for the
            # unchanged >=70-day DROP gate; no retention exception is installed.
            from datetime import datetime,timedelta
            for table in ("institutions","platform_accounts","channels","posts","platform_posts","reaction_snapshots","platform_snapshots"):
                columns=[row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
                for column in columns:
                    if column.endswith("_at"):
                        for key,value in connection.execute(f"SELECT id,{column} FROM {table} WHERE {column} IS NOT NULL").fetchall():
                            try: shifted=(datetime.fromisoformat(value)-timedelta(days=365)).isoformat()
                            except (ValueError,TypeError): continue
                            connection.execute(f"UPDATE {table} SET {column}=? WHERE id=?",(shifted,key))
        connection.commit()
    cfg = Settings(telegram_api_id=None,telegram_api_hash=None,telegram_session_path=destination/"session",
        database_path=source,initial_channels=(),poll_interval_minutes=60,track_post_for_hours=336,
        complete_history_max_first_age_minutes=90,jump_min_abs=15,jump_min_ratio=2.0,
        web_host="127.0.0.1",web_port=8080,display_timezone="Europe/Moscow",log_path=destination/"legacy.log",
        discovery_limit=200,discovery_overlap=20)
    cases = []
    client = TestClient(create_app(cfg, Database(source)))
    requests = [(kind, platform) for kind in ("snapshots", "posts") for platform in ("telegram", "all", "vk", "max", "rutube")]
    requests += [("snapshots", " TG "), ("posts", "общий"), ("posts", "unknown"), ("posts", "")]
    for index, (kind, platform) in enumerate(requests):
        response = client.get(f"/export/{kind}.csv", params={"platform":platform,"ignored":"1"})
        assert response.status_code == 200
        name = f"{index:02d}.csv"
        (destination/name).write_bytes(response.content)
        cases.append({"kind":kind,"platform":platform,"file":name,"sha256":hashlib.sha256(response.content).hexdigest(),
            "contentType":response.headers["content-type"],"disposition":response.headers["content-disposition"]})
    assert client.get("/export.csv").status_code == 404
    client.close()
    frozen=destination/"frozen.sqlite"
    with closing(sqlite3.connect(source)) as live, closing(sqlite3.connect(frozen)) as snapshot:
        live.backup(snapshot)
    source=frozen
    os.utime(source,(FIXTURE_ANCHOR.timestamp(),FIXTURE_ANCHOR.timestamp()))
    with PostgresTarget(dsn) as target:
        historical_sources=()
        if os.environ.get("MRANKED_LEGACY_CSV_OLD_FIXTURE")=="1":
            earlier=destination/"before-correction.sqlite"
            with closing(sqlite3.connect(source)) as original,closing(sqlite3.connect(earlier)) as previous:
                original.backup(previous)
                previous.execute("UPDATE reaction_snapshots SET views_count=views_count+1 WHERE id=(SELECT min(id) FROM reaction_snapshots WHERE synthetic=0)")
                previous.commit()
                earlier=destination/"before-correction-frozen.sqlite"
                with closing(sqlite3.connect(earlier)) as consistent: previous.backup(consistent)
            os.utime(earlier,(FIXTURE_ANCHOR.timestamp(),FIXTURE_ANCHOR.timestamp()))
            _,previous_report=BridgeService(BridgeOptions(earlier,"legacy-csv-http-golden",batch_size=2),LegacySource(earlier),target,snapshot_kind="s0").run()
            assert previous_report["gate"]["status"]=="pass",previous_report["mismatches"]
            historical_sources=(earlier,)
        service = BridgeService(BridgeOptions(source=source,source_namespace="legacy-csv-http-golden",batch_size=2,
            historical_source_paths=historical_sources),
            LegacySource(source),target,snapshot_kind="s_final")
        _, report = service.run()
        if report["projection_verification"] and report["projection_verification"].get("errorCode"):
            from migration.bridge.projection_reconciliation import verify_projections
            verify_projections(source,target.connection,source_name=service.options.source_namespace,
                expected_sha256=service.inventory.source_sha256)
        assert report["gate"]["status"] == "pass", report["mismatches"]
    manifest = {"cases":cases,"sourceSha256":hashlib.sha256(source.read_bytes()).hexdigest(),"legacyExportCsvStatus":404}
    (destination/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--native",action="store_true")
    arguments = parser.parse_args()
    if arguments.native:
        from migration.integration.legacy_native_csv_fixture import native_round_trip
        result=native_round_trip(arguments.output,os.environ["MRANKED_LEGACY_CSV_DSN"])
    else:
        result = produce(arguments.output,os.environ["MRANKED_LEGACY_CSV_DSN"])
    print(json.dumps({"cases":len(result["cases"]),"sourceSha256":result["sourceSha256"]}))
