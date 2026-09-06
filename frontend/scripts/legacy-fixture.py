"""Disposable, deterministic visual corpus and frozen legacy web server.

Never reads production settings or writes an existing SQLite file.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.clock import FrozenUtcClock
from app.config import Settings
from app.database import Database
from migration.legacy_reference import create_app
from migration.bridge.fixture import FIXTURE_ANCHOR, build_golden_fixture


def build(destination: Path, *, overview_status_only: bool = False) -> dict:
    build_golden_fixture(destination)
    db = Database(destination)
    # Status/identity coverage needs all continuation pages, not millions of
    # old fixed-cohort chart points. Keep the historical visual corpus intact.
    published = FIXTURE_ANCHOR - (timedelta(hours=2) if overview_status_only else timedelta(days=16))
    hours = [0, 1, 2] if overview_status_only else [0, 1, 24, 48, 72, 168, 336, 360, 381, 383, 384]
    # 205 additional institutions per platform exercise continuation past 200.
    for index in range(1, 206):
        institution = db.add_institution(f"Университет {index:03d}", f"ВУЗ {index:03d}")
        channel = db.add_channel(f"fixture_{index:03d}", institution)
        db.update_channel_public_metadata(channel, f"Университет {index:03d}", index * 100, str(index * 100))
        post = db.add_post(channel, f"message:{index}", [index], None, published, published + timedelta(minutes=2), 120, True, "text", False)
        for hour in hours:
            db.insert_snapshot(post, published + timedelta(hours=hour), hour * 3600, index + hour,
                {"👍": index + hour}, {"message": "Учебный корпус", "text": "Открытие кампуса"}, 60, 100, 5.0,
                comments_count=0 if index % 3 else None, views_count=index * 10 + hour * 5)
        for platform in ["vk", "max", "rutube"]:
            account = db.add_platform_account(institution, platform, f"fixture-{platform}-{index}", title=f"Университет {index:03d}", url=f"https://example.invalid/{platform}/{index}")
            db.update_platform_account_metadata(account, native_id=None, username=None, title=f"Университет {index:03d}", url=f"https://example.invalid/{platform}/{index}", subscriber_count=0 if index == 1 else index * 100, measured_at=FIXTURE_ANCHOR)
            publication = db.upsert_platform_post(account, f"publication-{index}", published, published + timedelta(minutes=2), "video" if platform == "rutube" else "post", f"https://example.invalid/{platform}/{index}/post", {"text": "Учебный корпус"}, history_complete=True)
            for hour in hours:
                db.insert_platform_snapshot(publication, published + timedelta(hours=hour), hour * 3600, 60,
                    views_count=index * 10 + hour * 5, reactions_count=index + hour, comments_count=0 if index % 3 else None,
                    shares_count=None if platform == "rutube" else 0, raw={"reactions": {"👍": index + hour}})
    # Explicit recovered entity, inaccessible/disabled account, custom emoji and uncertain history.
    with db.connect() as connection:
        fixed = FIXTURE_ANCHOR.isoformat()
        connection.execute("UPDATE reaction_snapshots SET interval_uncertain=1 WHERE id=2")
        connection.execute("UPDATE reaction_snapshots SET reactions_json=? WHERE id=2", (json.dumps({"custom:5368324170671202286": 8, "❤": 4}),))
        connection.execute("UPDATE platform_posts SET missing_check_count=0, deleted_at=NULL WHERE id=2")
        connection.execute("UPDATE platform_accounts SET enabled=0 WHERE id=(SELECT max(id) FROM platform_accounts)")
        for table in ["schema_migrations", "institutions", "platform_accounts", "channels", "platform_posts", "posts", "platform_snapshots", "reaction_snapshots"]:
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            for column in ["applied_at", "created_at", "added_at"]:
                if column in columns: connection.execute(f'UPDATE "{table}" SET "{column}"=?', (fixed,))
        connection.execute("UPDATE channels SET subscriber_measured_at=?, last_checked_at=?", (fixed, fixed))
        connection.execute("UPDATE platform_accounts SET last_checked_at=?", (fixed,))
    with db.connect() as connection:
        counts = {table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in ["institutions", "channels", "platform_accounts", "posts", "platform_posts", "reaction_snapshots", "platform_snapshots"]}
    return {"path": str(destination.resolve()), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "clock": FIXTURE_ANCHOR.isoformat(), "counts": counts,
            "profile": "overview-status" if overview_status_only else "legacy-visual",
            "coverage": ["telegram", "vk", "max", "rutube", "null", "zero", "negative", "reactions", "comments", "shares", "subscribers", "deleted", "recovered", "album", "joint", "repost", "custom_emoji", "incomplete", "uncertain", "synthetic", "official_rating", "overview_over_200" if overview_status_only else "rating_over_200"]}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--overview-status-only", action="store_true", help="Keep >200 entities per platform with short histories for status/identity checks")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    if not args.serve:
        result = build(args.database, overview_status_only=args.overview_status_only)
        args.database.with_suffix(".manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))
    else:
        import uvicorn
        # The file must be a corpus created by this producer, not an arbitrary DB.
        manifest = json.loads(args.database.with_suffix(".manifest.json").read_text())
        if hashlib.sha256(args.database.read_bytes()).hexdigest() != manifest["sha256"]:
            raise RuntimeError("Frozen corpus checksum changed")
        settings = Settings(telegram_api_id=None, telegram_api_hash=None, telegram_session_path=Path("/private/tmp/unused-fixture.session"),
            database_path=args.database, initial_channels=(), poll_interval_minutes=5, track_post_for_hours=960,
            complete_history_max_first_age_minutes=6, jump_min_abs=100, jump_min_ratio=5.0,
            web_host="127.0.0.1", web_port=args.port, display_timezone="Europe/Moscow", log_path=Path("/private/tmp/mranked-fixture.log"),
            discovery_limit=100, discovery_overlap=10, data_source="public_web",
            admin_username=os.getenv("LEGACY_ADMIN_USERNAME", "admin"),
            admin_password=os.getenv("LEGACY_ADMIN_PASSWORD") or None,
            admin_csrf_secret=os.getenv("LEGACY_ADMIN_CSRF_SECRET") or None)
        uvicorn.run(create_app(settings, Database(args.database), clock=FrozenUtcClock(FIXTURE_ANCHOR)), host="127.0.0.1", port=args.port)
