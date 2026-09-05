from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database import Database

from .source import LegacySource


FIXTURE_ANCHOR = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def build_golden_fixture(destination: Path, *, revision: int = 1) -> dict[str, object]:
    """Build a small deterministic SQLite corpus covering migration edge semantics."""

    if revision not in {1, 2}:
        raise ValueError("fixture revision must be 1 or 2")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    database = Database(destination)
    database.migrate()

    alpha = database.add_institution("Альфа Университет", "Альфа")
    beta = database.add_institution("Бета Институт", "Бета")
    telegram_channel = database.add_channel("alpha_university", alpha)
    database.update_channel_identity(
        telegram_channel, -1001234567890, "Альфа — официальный канал", "alpha_university"
    )
    database.update_channel_public_metadata(
        telegram_channel, "Альфа — официальный канал", 12_345, "12,3K"
    )
    database.update_channel_m_rating(
        telegram_channel, 2, 91.25, "2026-Q2", FIXTURE_ANCHOR
    )

    database.update_institution_m_rating(
        alpha,
        {
            "social": (1, 95.5),
            "tg": (2, 91.25),
            "vk": (3, 88.0),
            "max": (4, 84.5),
            "rutube": (5, 80.0),
        },
        "2026-Q2",
        FIXTURE_ANCHOR,
    )

    vk_account = database.add_platform_account(
        alpha,
        "vk",
        "club100",
        username="alpha_vk",
        title="Альфа VK",
        url="https://vk.ru/alpha_vk",
        access_mode="official_api",
    )
    max_account = database.add_platform_account(
        beta,
        "max",
        "beta_max",
        username="beta_max",
        title="Бета MAX",
        url="https://max.ru/beta_max",
        access_mode="user_session",
        data_quality="rounded",
    )
    rutube_account = database.add_platform_account(
        beta,
        "rutube",
        "beta-rutube",
        title="Бета Rutube",
        url="https://rutube.ru/channel/beta-rutube/",
        access_mode="public_api",
    )
    for account_id, native_id, username, title, url, subscribers in (
        (vk_account, "-100", "alpha_vk", "Альфа VK", "https://vk.ru/alpha_vk", 20_000),
        (max_account, "200", "beta_max", "Бета MAX", "https://max.ru/beta_max", 0),
        (
            rutube_account,
            "beta-rutube",
            "beta_video",
            "Бета Rutube",
            "https://rutube.ru/channel/beta-rutube/",
            None,
        ),
    ):
        database.update_platform_account_metadata(
            account_id,
            native_id=native_id,
            username=username,
            title=title,
            url=url,
            subscriber_count=subscribers,
            measured_at=FIXTURE_ANCHOR,
        )

    telegram_published = FIXTURE_ANCHOR - timedelta(days=2)
    telegram_post = database.add_post(
        telegram_channel,
        "album:777",
        [101, 102, 103],
        777,
        telegram_published,
        telegram_published + timedelta(minutes=5),
        300,
        True,
        "album",
        True,
        is_repost=True,
    )
    database.ensure_publication_baseline(
        telegram_post, telegram_published, 300, 600
    )
    database.insert_snapshot(
        telegram_post,
        telegram_published + timedelta(hours=1),
        3_600,
        12,
        {"👍": 8, "❤": 4},
        {"access_token": "fixture-secret", "views": 100},
        60,
        100,
        5.0,
        comments_count=2,
        views_count=100,
    )
    database.insert_snapshot(
        telegram_post,
        telegram_published + timedelta(hours=2),
        7_200,
        10,
        {"👍": 7, "❤": 3},
        {"views": 90},
        60,
        100,
        5.0,
        comments_count=1,
        views_count=90,
    )
    database.record_post_missing(
        telegram_post, FIXTURE_ANCHOR - timedelta(hours=1), "not_found", 1
    )

    vk_post = database.upsert_platform_post(
        vk_account,
        "-100_55",
        FIXTURE_ANCHOR - timedelta(days=3),
        FIXTURE_ANCHOR - timedelta(days=3, minutes=-2),
        "post",
        "https://vk.ru/wall-100_55",
        {"access_token": "fixture-secret", "id": 55},
        history_complete=True,
        source_external_id="9_55",
        is_joint=True,
        additional_author_count=2,
    )
    database.insert_platform_snapshot(
        vk_post,
        FIXTURE_ANCHOR - timedelta(days=2, hours=23),
        3_600,
        60,
        views_count=1_000,
        reactions_count=50,
        comments_count=0,
        shares_count=0,
        raw={"views": 1_000},
    )

    max_post = database.upsert_platform_post(
        max_account,
        "9001",
        FIXTURE_ANCHOR - timedelta(days=1),
        FIXTURE_ANCHOR - timedelta(days=1, minutes=-10),
        "post",
        "https://max.ru/beta_max/9001",
        {"id": 9001},
        history_complete=False,
        is_repost=True,
    )
    database.insert_platform_snapshot(
        max_post,
        FIXTURE_ANCHOR - timedelta(hours=23),
        3_600,
        60,
        views_count=0,
        reactions_count=None,
        comments_count=None,
        shares_count=0,
        raw={"views": "0"},
    )
    database.record_platform_post_missing(
        max_post, FIXTURE_ANCHOR - timedelta(minutes=30), "not_found", 1
    )

    rutube_post = database.upsert_platform_post(
        rutube_account,
        "video-1",
        FIXTURE_ANCHOR - timedelta(hours=6),
        FIXTURE_ANCHOR - timedelta(hours=5, minutes=55),
        "video",
        "https://rutube.ru/video/video-1/",
        {"video": {"id": "video-1"}},
        history_complete=True,
    )
    database.insert_platform_snapshot(
        rutube_post,
        FIXTURE_ANCHOR - timedelta(hours=5),
        3_600,
        60,
        views_count=250,
        reactions_count=0,
        comments_count=None,
        shares_count=None,
        raw={"views": 250},
    )

    database.set_state("last_poll", FIXTURE_ANCHOR.isoformat())
    database.set_state("unknown_fixture_key", "opaque-value")

    if revision >= 2:
        database.update_institution(alpha, "Альфа Университет — обновлено", "Альфа")
        database.insert_snapshot(
            telegram_post,
            telegram_published + timedelta(hours=3),
            10_800,
            15,
            {"👍": 10, "❤": 5},
            {"views": 140},
            60,
            100,
            5.0,
            comments_count=3,
            views_count=140,
        )
        database.insert_platform_snapshot(
            max_post,
            FIXTURE_ANCHOR - timedelta(minutes=5),
            86_100,
            60,
            views_count=5,
            reactions_count=1,
            comments_count=None,
            shares_count=0,
            raw={"views": 5, "reactions": 1},
        )
        database.set_state(
            "last_poll", (FIXTURE_ANCHOR + timedelta(minutes=5)).isoformat()
        )

    # Remove wall-clock noise introduced by legacy helper methods. Canonical row
    # hashes from two independently built fixtures must be identical.
    fixed = FIXTURE_ANCHOR.isoformat()
    with database.connect() as connection:
        for table in (
            "schema_migrations",
            "institutions",
            "platform_accounts",
            "channels",
            "platform_posts",
            "posts",
            "platform_snapshots",
            "reaction_snapshots",
        ):
            columns = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            for column in ("applied_at", "created_at", "added_at"):
                if column in columns:
                    connection.execute(f'UPDATE "{table}" SET "{column}"=?', (fixed,))
        connection.execute(
            "UPDATE channels SET subscriber_measured_at=?, last_checked_at=?",
            (fixed, fixed),
        )
        connection.execute(
            "UPDATE platform_accounts SET subscriber_measured_at=?, last_checked_at=?",
            (fixed, fixed),
        )

    inventory = LegacySource(destination).inventory()
    return {
        "path": str(destination),
        "fixture_revision": revision,
        "schema_version": inventory.schema_version,
        "source_sha256": inventory.source_sha256,
        "tables": {table.name: table.row_count for table in inventory.tables},
        "totals": dict(inventory.totals),
    }
