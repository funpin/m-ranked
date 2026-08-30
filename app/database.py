from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .analytics import delta_by_reaction, interval_uncertain


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    title TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    added_at TEXT NOT NULL,
                    last_seen_message_id INTEGER NOT NULL DEFAULT 0,
                    last_checked_at TEXT,
                    last_error TEXT,
                    subscriber_count INTEGER,
                    subscriber_count_display TEXT,
                    subscriber_measured_at TEXT
                );
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL REFERENCES channels(id),
                    logical_key TEXT NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    telegram_grouped_id INTEGER,
                    published_at TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    first_observation_age_seconds INTEGER NOT NULL,
                    history_complete INTEGER NOT NULL,
                    baseline_from_publication INTEGER NOT NULL DEFAULT 0,
                    post_type TEXT NOT NULL,
                    ambiguous_album_reactions INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(channel_id, logical_key),
                    UNIQUE(channel_id, telegram_message_id)
                );
                CREATE TABLE IF NOT EXISTS post_messages (
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    telegram_message_id INTEGER NOT NULL,
                    PRIMARY KEY(post_id, telegram_message_id)
                );
                CREATE TABLE IF NOT EXISTS reaction_snapshots (
                    id INTEGER PRIMARY KEY,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    measured_at TEXT NOT NULL,
                    measurement_bucket INTEGER NOT NULL,
                    age_seconds INTEGER NOT NULL,
                    total_reactions INTEGER NOT NULL,
                    reactions_json TEXT NOT NULL,
                    raw_state_json TEXT,
                    delta_total INTEGER,
                    delta_by_reaction_json TEXT,
                    delta_seconds INTEGER,
                    rate_per_hour REAL,
                    interval_uncertain INTEGER NOT NULL DEFAULT 0,
                    spike INTEGER NOT NULL DEFAULT 0,
                    comments_count INTEGER,
                    delta_comments INTEGER,
                    views_count INTEGER,
                    delta_views INTEGER,
                    synthetic INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(post_id, measurement_bucket)
                );
                CREATE INDEX IF NOT EXISTS idx_posts_channel_published
                    ON posts(channel_id, published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_snapshots_post_age
                    ON reaction_snapshots(post_id, age_seconds);
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS institutions (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    short_name TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS platform_accounts (
                    id INTEGER PRIMARY KEY,
                    institution_id INTEGER NOT NULL REFERENCES institutions(id),
                    platform TEXT NOT NULL CHECK(platform IN ('telegram','vk','max','rutube')),
                    external_key TEXT NOT NULL COLLATE NOCASE,
                    native_id TEXT,
                    username TEXT COLLATE NOCASE,
                    title TEXT,
                    url TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    access_mode TEXT NOT NULL DEFAULT 'public',
                    data_quality TEXT NOT NULL DEFAULT 'exact',
                    subscriber_count INTEGER,
                    subscriber_count_display TEXT,
                    subscriber_measured_at TEXT,
                    last_checked_at TEXT,
                    last_error TEXT,
                    added_at TEXT NOT NULL,
                    UNIQUE(platform, external_key)
                );
                CREATE INDEX IF NOT EXISTS idx_platform_accounts_institution
                    ON platform_accounts(institution_id, platform);
                CREATE TABLE IF NOT EXISTS platform_posts (
                    id INTEGER PRIMARY KEY,
                    platform_account_id INTEGER NOT NULL
                        REFERENCES platform_accounts(id) ON DELETE CASCADE,
                    external_id TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    discovered_at TEXT NOT NULL,
                    post_type TEXT NOT NULL,
                    url TEXT,
                    deleted_at TEXT,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(platform_account_id, external_id)
                );
                CREATE INDEX IF NOT EXISTS idx_platform_posts_account_published
                    ON platform_posts(platform_account_id, published_at DESC);
                CREATE TABLE IF NOT EXISTS platform_snapshots (
                    id INTEGER PRIMARY KEY,
                    platform_post_id INTEGER NOT NULL
                        REFERENCES platform_posts(id) ON DELETE CASCADE,
                    measured_at TEXT NOT NULL,
                    measurement_bucket INTEGER NOT NULL,
                    age_seconds INTEGER NOT NULL,
                    views_count INTEGER,
                    reactions_count INTEGER,
                    comments_count INTEGER,
                    shares_count INTEGER,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(platform_post_id, measurement_bucket)
                );
                CREATE INDEX IF NOT EXISTS idx_platform_snapshots_post_age
                    ON platform_snapshots(platform_post_id, age_seconds);
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)",
                (iso(utc_now()),),
            )
            channel_columns = {row[1] for row in conn.execute("PRAGMA table_info(channels)")}
            for name, sql_type in (
                ("subscriber_count", "INTEGER"),
                ("subscriber_count_display", "TEXT"),
                ("subscriber_measured_at", "TEXT"),
                ("m_rating_tg_rank", "INTEGER"),
                ("m_rating_tg_score", "REAL"),
                ("m_rating_period", "TEXT"),
                ("m_rating_measured_at", "TEXT"),
            ):
                if name not in channel_columns:
                    conn.execute(f"ALTER TABLE channels ADD COLUMN {name} {sql_type}")
            snapshot_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(reaction_snapshots)")
            }
            for name in ("comments_count", "delta_comments"):
                if name not in snapshot_columns:
                    conn.execute(f"ALTER TABLE reaction_snapshots ADD COLUMN {name} INTEGER")
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(2, ?)",
                (iso(utc_now()),),
            )
            post_columns = {row[1] for row in conn.execute("PRAGMA table_info(posts)")}
            if "baseline_from_publication" not in post_columns:
                conn.execute(
                    "ALTER TABLE posts ADD COLUMN baseline_from_publication "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            if "deleted_at" not in post_columns:
                conn.execute("ALTER TABLE posts ADD COLUMN deleted_at TEXT")
            for name, sql_type in (
                ("missing_check_count", "INTEGER NOT NULL DEFAULT 0"),
                ("missing_last_checked_at", "TEXT"),
                ("missing_reason", "TEXT"),
            ):
                if name not in post_columns:
                    conn.execute(f"ALTER TABLE posts ADD COLUMN {name} {sql_type}")
            snapshot_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(reaction_snapshots)")
            }
            for name, sql_type in (
                ("views_count", "INTEGER"),
                ("delta_views", "INTEGER"),
                ("synthetic", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in snapshot_columns:
                    conn.execute(f"ALTER TABLE reaction_snapshots ADD COLUMN {name} {sql_type}")
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(3, ?)",
                (iso(utc_now()),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(4, ?)",
                (iso(utc_now()),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(5, ?)",
                (iso(utc_now()),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(6, ?)",
                (iso(utc_now()),),
            )
            channel_columns = {row[1] for row in conn.execute("PRAGMA table_info(channels)")}
            if "institution_id" not in channel_columns:
                conn.execute("ALTER TABLE channels ADD COLUMN institution_id INTEGER")
            if "platform_account_id" not in channel_columns:
                conn.execute("ALTER TABLE channels ADD COLUMN platform_account_id INTEGER")
            unlinked = list(conn.execute(
                """SELECT * FROM channels
                   WHERE institution_id IS NULL OR platform_account_id IS NULL
                   ORDER BY id"""
            ))
            for channel in unlinked:
                title = str(channel["title"] or f"@{channel['username']}")
                institution_id = channel["institution_id"]
                if institution_id is None:
                    cursor = conn.execute(
                        "INSERT INTO institutions(name, short_name, created_at) VALUES(?,?,?)",
                        (title, title, iso(utc_now())),
                    )
                    institution_id = int(cursor.lastrowid)
                account_id = channel["platform_account_id"]
                if account_id is None:
                    conn.execute(
                        """INSERT INTO platform_accounts(
                             institution_id, platform, external_key, native_id, username,
                             title, url, enabled, access_mode, data_quality,
                             subscriber_count, subscriber_count_display,
                             subscriber_measured_at, last_checked_at, last_error, added_at
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(platform, external_key) DO UPDATE SET
                             institution_id=excluded.institution_id,
                             username=excluded.username""",
                        (
                            institution_id, "telegram", str(channel["username"]).casefold(),
                            str(channel["telegram_id"]) if channel["telegram_id"] else None,
                            channel["username"], channel["title"],
                            f"https://t.me/{channel['username']}", channel["enabled"],
                            "mtproto" if channel["telegram_id"] else "public",
                            "exact" if channel["telegram_id"] else "rounded",
                            channel["subscriber_count"], channel["subscriber_count_display"],
                            channel["subscriber_measured_at"], channel["last_checked_at"],
                            channel["last_error"], channel["added_at"],
                        ),
                    )
                    account = conn.execute(
                        "SELECT id FROM platform_accounts WHERE platform='telegram' AND external_key=?",
                        (str(channel["username"]).casefold(),),
                    ).fetchone()
                    account_id = int(account["id"])
                conn.execute(
                    "UPDATE channels SET institution_id=?, platform_account_id=? WHERE id=?",
                    (institution_id, account_id, channel["id"]),
                )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(7, ?)",
                (iso(utc_now()),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(8, ?)",
                (iso(utc_now()),),
            )

    def add_institution(self, name: str, short_name: str | None = None) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO institutions(name, short_name, created_at) VALUES(?,?,?)",
                (name.strip(), (short_name or name).strip(), iso(utc_now())),
            )
            return int(cursor.lastrowid)

    def list_institutions(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute("SELECT * FROM institutions ORDER BY name COLLATE NOCASE"))

    def update_institution(self, institution_id: int, name: str, short_name: str) -> bool:
        name = name.strip()
        short_name = short_name.strip()
        if not name or not short_name:
            raise ValueError("Institution name and short name are required")
        with self.connect() as conn:
            result = conn.execute(
                "UPDATE institutions SET name=?, short_name=? WHERE id=?",
                (name, short_name, institution_id),
            )
            return result.rowcount > 0

    def add_platform_account(
        self,
        institution_id: int,
        platform: str,
        external_key: str,
        username: str | None = None,
        title: str | None = None,
        url: str | None = None,
        access_mode: str = "public",
        data_quality: str = "exact",
    ) -> int:
        if platform not in {"telegram", "vk", "max", "rutube"}:
            raise ValueError(f"Unsupported platform: {platform}")
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO platform_accounts(
                     institution_id, platform, external_key, username, title, url,
                     enabled, access_mode, data_quality, added_at
                   ) VALUES(?,?,?,?,?,?,1,?,?,?)
                   ON CONFLICT(platform, external_key) DO UPDATE SET
                     institution_id=excluded.institution_id, username=excluded.username,
                     title=coalesce(excluded.title, platform_accounts.title),
                     url=coalesce(excluded.url, platform_accounts.url), enabled=1,
                     access_mode=excluded.access_mode, data_quality=excluded.data_quality""",
                (
                    institution_id, platform, external_key, username, title, url,
                    access_mode, data_quality, iso(utc_now()),
                ),
            )
            row = conn.execute(
                "SELECT id FROM platform_accounts WHERE platform=? AND external_key=?",
                (platform, external_key),
            ).fetchone()
            return int(row["id"])

    def list_platform_accounts(
        self,
        institution_id: int | None = None,
        platform: str | None = None,
        enabled_only: bool = False,
    ) -> list[sqlite3.Row]:
        conditions: list[str] = []
        params: list[Any] = []
        if institution_id is not None:
            conditions.append("institution_id=?")
            params.append(institution_id)
        if platform is not None:
            conditions.append("platform=?")
            params.append(platform)
        if enabled_only:
            conditions.append("enabled=1")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self.connect() as conn:
            return list(conn.execute(
                f"SELECT * FROM platform_accounts {where} ORDER BY platform, title, username",
                tuple(params),
            ))

    def platform_account(self, account_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM platform_accounts WHERE id=?", (account_id,),
            ).fetchone()

    def set_platform_account_enabled(self, account_id: int, enabled: bool) -> bool:
        """Enable or pause an account and its legacy Telegram collector together."""
        with self.connect() as conn:
            result = conn.execute(
                "UPDATE platform_accounts SET enabled=? WHERE id=?",
                (int(enabled), account_id),
            )
            if result.rowcount:
                conn.execute(
                    "UPDATE channels SET enabled=? WHERE platform_account_id=?",
                    (int(enabled), account_id),
                )
            return result.rowcount > 0

    def delete_platform_account(self, account_id: int) -> bool:
        """Delete one account and its measurements, preserving the institution."""
        with self.connect() as conn:
            account = conn.execute(
                "SELECT id FROM platform_accounts WHERE id=?", (account_id,),
            ).fetchone()
            if account is None:
                return False
            channel_ids = [
                int(row["id"])
                for row in conn.execute(
                    "SELECT id FROM channels WHERE platform_account_id=?", (account_id,),
                )
            ]
            for channel_id in channel_ids:
                conn.execute("DELETE FROM posts WHERE channel_id=?", (channel_id,))
                conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))
            conn.execute("DELETE FROM platform_accounts WHERE id=?", (account_id,))
            return True

    def update_platform_account_metadata(
        self,
        account_id: int,
        *,
        native_id: str,
        username: str,
        title: str,
        url: str,
        subscriber_count: int | None,
        measured_at: datetime,
    ) -> None:
        display = (
            f"{subscriber_count:,}".replace(",", " ")
            if subscriber_count is not None else None
        )
        with self.connect() as conn:
            conn.execute(
                """UPDATE platform_accounts SET native_id=?, username=?, title=?, url=?,
                   subscriber_count=?, subscriber_count_display=?,
                   subscriber_measured_at=?, last_checked_at=?, last_error=NULL
                   WHERE id=?""",
                (
                    native_id, username, title, url, subscriber_count, display,
                    iso(measured_at), iso(measured_at), account_id,
                ),
            )

    def finish_platform_account_check(
        self, account_id: int, measured_at: datetime, error: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE platform_accounts SET last_checked_at=?, last_error=? WHERE id=?",
                (iso(measured_at), error, account_id),
            )

    def upsert_platform_post(
        self,
        platform_account_id: int,
        external_id: str,
        published_at: datetime,
        discovered_at: datetime,
        post_type: str,
        url: str | None,
        raw: Any,
    ) -> int:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO platform_posts(
                     platform_account_id, external_id, published_at, discovered_at,
                     post_type, url, raw_json, created_at
                   ) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(platform_account_id, external_id) DO UPDATE SET
                     post_type=excluded.post_type, url=excluded.url,
                     raw_json=excluded.raw_json, deleted_at=NULL""",
                (
                    platform_account_id, external_id, iso(published_at),
                    iso(discovered_at), post_type, url,
                    json.dumps(raw, ensure_ascii=False, sort_keys=True), iso(utc_now()),
                ),
            )
            row = conn.execute(
                """SELECT id FROM platform_posts
                   WHERE platform_account_id=? AND external_id=?""",
                (platform_account_id, external_id),
            ).fetchone()
            return int(row["id"])

    def latest_platform_snapshot_at(self, platform_post_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT measured_at FROM platform_snapshots
                   WHERE platform_post_id=? ORDER BY measured_at DESC LIMIT 1""",
                (platform_post_id,),
            ).fetchone()
            return str(row["measured_at"]) if row else None

    def insert_platform_snapshot(
        self,
        platform_post_id: int,
        measured_at: datetime,
        age_seconds: int,
        poll_interval_minutes: int,
        *,
        views_count: int | None,
        reactions_count: int | None,
        comments_count: int | None,
        shares_count: int | None,
        raw: Any,
    ) -> bool:
        bucket = int(measured_at.timestamp()) // (poll_interval_minutes * 60)
        with self.connect() as conn:
            result = conn.execute(
                """INSERT OR IGNORE INTO platform_snapshots(
                     platform_post_id, measured_at, measurement_bucket, age_seconds,
                     views_count, reactions_count, comments_count, shares_count,
                     raw_json, created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    platform_post_id, iso(measured_at), bucket, age_seconds,
                    views_count, reactions_count, comments_count, shares_count,
                    json.dumps(raw, ensure_ascii=False, sort_keys=True), iso(utc_now()),
                ),
            )
            return result.rowcount == 1

    def add_channel(self, username: str, institution_id: int | None = None) -> int:
        with self.connect() as conn:
            if institution_id is not None and conn.execute(
                "SELECT 1 FROM institutions WHERE id=?", (institution_id,)
            ).fetchone() is None:
                raise ValueError("Institution not found")
            conn.execute(
                """INSERT INTO channels(username, enabled, added_at)
                   VALUES(?, 1, ?)
                   ON CONFLICT(username) DO UPDATE SET enabled=1""",
                (username, iso(utc_now())),
            )
            row = conn.execute("SELECT id FROM channels WHERE username=?", (username,)).fetchone()
            channel_id = int(row["id"])
            channel = conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
            previous_institution_id = channel["institution_id"]
            if channel["institution_id"] is None and institution_id is None:
                title = f"@{username}"
                cursor = conn.execute(
                    "INSERT INTO institutions(name, short_name, created_at) VALUES(?,?,?)",
                    (title, title, iso(utc_now())),
                )
                institution_id = int(cursor.lastrowid)
                conn.execute(
                    """INSERT INTO platform_accounts(
                         institution_id, platform, external_key, username, url,
                         enabled, access_mode, data_quality, added_at
                       ) VALUES(?, 'telegram', ?, ?, ?, 1, 'public', 'rounded', ?)""",
                    (institution_id, username.casefold(), username, f"https://t.me/{username}", iso(utc_now())),
                )
                account_id = int(conn.execute(
                    "SELECT id FROM platform_accounts WHERE platform='telegram' AND external_key=?",
                    (username.casefold(),),
                ).fetchone()["id"])
                conn.execute(
                    "UPDATE channels SET institution_id=?, platform_account_id=? WHERE id=?",
                    (institution_id, account_id, channel_id),
                )
            elif institution_id is not None:
                account_id = channel["platform_account_id"]
                if account_id is None:
                    conn.execute(
                        """INSERT INTO platform_accounts(
                             institution_id, platform, external_key, username, url,
                             enabled, access_mode, data_quality, added_at
                           ) VALUES(?, 'telegram', ?, ?, ?, 1, 'public', 'rounded', ?)""",
                        (
                            institution_id, username.casefold(), username,
                            f"https://t.me/{username}", iso(utc_now()),
                        ),
                    )
                    account_id = int(conn.execute(
                        "SELECT id FROM platform_accounts WHERE platform='telegram' AND external_key=?",
                        (username.casefold(),),
                    ).fetchone()["id"])
                else:
                    conn.execute(
                        "UPDATE platform_accounts SET institution_id=?, enabled=1 WHERE id=?",
                        (institution_id, account_id),
                    )
                conn.execute(
                    "UPDATE channels SET institution_id=?, platform_account_id=? WHERE id=?",
                    (institution_id, account_id, channel_id),
                )
                if previous_institution_id not in (None, institution_id):
                    remaining = conn.execute(
                        "SELECT 1 FROM platform_accounts WHERE institution_id=? LIMIT 1",
                        (previous_institution_id,),
                    ).fetchone()
                    if remaining is None:
                        conn.execute("DELETE FROM institutions WHERE id=?", (previous_institution_id,))
            else:
                conn.execute(
                    "UPDATE platform_accounts SET enabled=1 WHERE id=?",
                    (channel["platform_account_id"],),
                )
            return channel_id

    def disable_channel(self, username: str) -> bool:
        with self.connect() as conn:
            result = conn.execute(
                "UPDATE channels SET enabled=0 WHERE username=? COLLATE NOCASE", (username,)
            )
            conn.execute(
                """UPDATE platform_accounts SET enabled=0 WHERE id=(
                     SELECT platform_account_id FROM channels WHERE username=? COLLATE NOCASE
                   )""",
                (username,),
            )
            return result.rowcount > 0

    def delete_channel(self, channel_id: int) -> bool:
        """Permanently remove a channel and every measurement stored for it."""
        with self.connect() as conn:
            # posts.channel_id predates the ON DELETE CASCADE migration.  Delete
            # posts explicitly; their dependent snapshots and message mappings do
            # cascade, then the channel itself can be deleted safely.
            conn.execute("DELETE FROM posts WHERE channel_id=?", (channel_id,))
            channel = conn.execute(
                "SELECT institution_id, platform_account_id FROM channels WHERE id=?", (channel_id,)
            ).fetchone()
            result = conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))
            if channel is not None and channel["platform_account_id"] is not None:
                conn.execute("DELETE FROM platform_accounts WHERE id=?", (channel["platform_account_id"],))
                remaining = conn.execute(
                    "SELECT 1 FROM platform_accounts WHERE institution_id=? LIMIT 1",
                    (channel["institution_id"],),
                ).fetchone()
                if remaining is None:
                    conn.execute("DELETE FROM institutions WHERE id=?", (channel["institution_id"],))
            return result.rowcount > 0

    def list_channels(self, enabled_only: bool = False) -> list[sqlite3.Row]:
        where = "WHERE enabled=1" if enabled_only else ""
        with self.connect() as conn:
            return list(conn.execute(f"SELECT * FROM channels {where} ORDER BY username"))

    def list_channels_with_institutions(self, enabled_only: bool = False) -> list[sqlite3.Row]:
        where = "WHERE c.enabled=1" if enabled_only else ""
        with self.connect() as conn:
            return list(conn.execute(
                f"""SELECT c.*, i.name AS institution_name,
                           i.short_name AS institution_short_name
                    FROM channels c
                    LEFT JOIN institutions i ON i.id=c.institution_id
                    {where} ORDER BY c.username"""
            ))

    def channel(self, channel_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()

    def update_channel_identity(self, channel_id: int, telegram_id: int, title: str, username: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE channels SET telegram_id=?, title=?, username=?, last_error=NULL WHERE id=?",
                (telegram_id, title, username, channel_id),
            )
            conn.execute(
                """UPDATE platform_accounts SET native_id=?, username=?, title=?, url=?,
                   access_mode='mtproto', data_quality='exact', last_error=NULL
                   WHERE id=(SELECT platform_account_id FROM channels WHERE id=?)""",
                (str(telegram_id), username, title, f"https://t.me/{username}", channel_id),
            )

    def update_channel_public_metadata(
        self, channel_id: int, title: str | None, subscribers: int | None, display: str | None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE channels SET title=coalesce(?, title), subscriber_count=?,
                   subscriber_count_display=?, subscriber_measured_at=?, last_error=NULL
                   WHERE id=?""",
                (title, subscribers, display, iso(utc_now()), channel_id),
            )
            conn.execute(
                """UPDATE platform_accounts SET title=coalesce(?, title),
                   subscriber_count=?, subscriber_count_display=?, subscriber_measured_at=?,
                   last_error=NULL WHERE id=(
                     SELECT platform_account_id FROM channels WHERE id=?
                   )""",
                (title, subscribers, display, iso(utc_now()), channel_id),
            )

    def update_channel_title(self, channel_id: int, title: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE channels SET title=coalesce(?, title), last_error=NULL WHERE id=?",
                (title, channel_id),
            )

    def update_channel_m_rating(
        self,
        channel_id: int,
        rank: int,
        score: float,
        period: str,
        measured_at: datetime,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE channels SET m_rating_tg_rank=?, m_rating_tg_score=?,
                   m_rating_period=?, m_rating_measured_at=? WHERE id=?""",
                (rank, score, period, iso(measured_at), channel_id),
            )

    def finish_channel_check(self, channel_id: int, last_seen: int, error: str | None = None) -> None:
        with self.connect() as conn:
            checked_at = iso(utc_now())
            conn.execute(
                """UPDATE channels SET last_seen_message_id=max(last_seen_message_id, ?),
                   last_checked_at=?, last_error=? WHERE id=?""",
                (last_seen, checked_at, error, channel_id),
            )
            conn.execute(
                """UPDATE platform_accounts SET last_checked_at=?, last_error=? WHERE id=(
                     SELECT platform_account_id FROM channels WHERE id=?
                   )""",
                (checked_at, error, channel_id),
            )

    def add_post(
        self,
        channel_id: int,
        logical_key: str,
        message_ids: Sequence[int],
        grouped_id: int | None,
        published_at: datetime,
        discovered_at: datetime,
        first_age_seconds: int,
        history_complete: bool,
        post_type: str,
        ambiguous: bool,
    ) -> int:
        representative = min(message_ids)
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO posts(
                    channel_id, logical_key, telegram_message_id, telegram_grouped_id,
                    published_at, discovered_at, first_observation_age_seconds,
                    history_complete, post_type, ambiguous_album_reactions, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    channel_id, logical_key, representative, grouped_id, iso(published_at),
                    iso(discovered_at), first_age_seconds, int(history_complete), post_type,
                    int(ambiguous), iso(utc_now()),
                ),
            )
            row = conn.execute(
                "SELECT id FROM posts WHERE channel_id=? AND logical_key=?",
                (channel_id, logical_key),
            ).fetchone()
            post_id = int(row["id"])
            conn.executemany(
                "INSERT OR IGNORE INTO post_messages(post_id, telegram_message_id) VALUES(?,?)",
                [(post_id, mid) for mid in message_ids],
            )
            return post_id

    def active_posts(self, channel_id: int, cutoff_iso: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """SELECT p.*,
                       (SELECT measured_at FROM reaction_snapshots s
                        WHERE s.post_id=p.id AND s.synthetic=0
                        ORDER BY measured_at DESC LIMIT 1) last_measured_at
                       FROM posts p WHERE p.channel_id=? AND p.published_at>=?
                         AND p.deleted_at IS NULL
                       ORDER BY p.published_at""",
                    (channel_id, cutoff_iso),
                )
            )

    def mark_post_deleted(self, post_id: int, detected_at: datetime) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE posts SET deleted_at=COALESCE(deleted_at, ?) WHERE id=?",
                (iso(detected_at), post_id),
            )

    def record_post_missing(
        self,
        post_id: int,
        detected_at: datetime,
        reason: str,
        confirmation_checks: int,
    ) -> tuple[int, bool]:
        """Record an explicit missing result and delete only after confirmation."""
        with self.connect() as conn:
            conn.execute(
                """UPDATE posts SET missing_check_count=missing_check_count+1,
                   missing_last_checked_at=?, missing_reason=? WHERE id=?""",
                (iso(detected_at), reason, post_id),
            )
            row = conn.execute(
                "SELECT missing_check_count, deleted_at FROM posts WHERE id=?", (post_id,)
            ).fetchone()
            if row is None:
                return 0, False
            count = int(row["missing_check_count"])
            confirmed = count >= confirmation_checks
            if confirmed and row["deleted_at"] is None:
                conn.execute(
                    "UPDATE posts SET deleted_at=? WHERE id=?", (iso(detected_at), post_id)
                )
            return count, confirmed

    def mark_post_available(self, post_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE posts SET deleted_at=NULL, missing_check_count=0,
                   missing_last_checked_at=NULL, missing_reason=NULL WHERE id=?""",
                (post_id,),
            )

    def expired_posts(self, cutoff_iso: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """SELECT p.*, c.username, c.title
                       FROM posts p JOIN channels c ON c.id=p.channel_id
                       WHERE p.published_at<? ORDER BY p.published_at, p.id""",
                    (cutoff_iso,),
                )
            )

    def archive_rows(self, post_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(
                conn.execute(
                    """SELECT c.username, c.title AS channel_title, p.telegram_message_id,
                       p.published_at, p.discovered_at, p.history_complete,
                       p.post_type, s.measured_at, s.age_seconds,
                       s.total_reactions, s.delta_total, s.views_count,
                       s.delta_views, s.comments_count, s.delta_comments,
                       s.reactions_json, s.delta_by_reaction_json,
                       s.interval_uncertain, s.spike, s.synthetic
                       FROM posts p JOIN channels c ON c.id=p.channel_id
                       LEFT JOIN reaction_snapshots s ON s.post_id=p.id
                       WHERE p.id=? ORDER BY s.measured_at""",
                    (post_id,),
                )
            )

    def delete_post(self, post_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM posts WHERE id=?", (post_id,))

    def ensure_publication_baseline(
        self,
        post_id: int,
        published_at: datetime,
        first_age_seconds: int,
        max_age_seconds: int,
    ) -> bool:
        """Insert the synthetic zero point only when the post was discovered on time."""
        if first_age_seconds > max_age_seconds:
            return False
        with self.connect() as conn:
            post = conn.execute(
                "SELECT baseline_from_publication FROM posts WHERE id=?", (post_id,)
            ).fetchone()
            if post is None or bool(post["baseline_from_publication"]):
                return False
            conn.execute(
                "UPDATE posts SET baseline_from_publication=1, history_complete=1 WHERE id=?",
                (post_id,),
            )
            result = conn.execute(
                """INSERT OR IGNORE INTO reaction_snapshots(
                    post_id, measured_at, measurement_bucket, age_seconds,
                    total_reactions, reactions_json, raw_state_json,
                    delta_total, delta_by_reaction_json, delta_seconds,
                    rate_per_hour, interval_uncertain, spike,
                    comments_count, delta_comments, views_count, delta_views,
                    synthetic, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    post_id, iso(published_at), -post_id, 0, 0, "{}",
                    '{"synthetic":"publication"}', None, None, None, None,
                    0, 0, 0, None, 0, None, 1, iso(utc_now()),
                ),
            )
            first_actual = conn.execute(
                """SELECT * FROM reaction_snapshots
                   WHERE post_id=? AND synthetic=0
                   ORDER BY measured_at LIMIT 1""",
                (post_id,),
            ).fetchone()
            if first_actual is not None:
                measured = datetime.fromisoformat(first_actual["measured_at"])
                elapsed = max(1, int((measured - published_at).total_seconds()))
                first_total = int(first_actual["total_reactions"])
                first_views = first_actual["views_count"]
                first_comments = first_actual["comments_count"]
                conn.execute(
                    """UPDATE reaction_snapshots SET delta_total=?,
                       delta_by_reaction_json=reactions_json, delta_seconds=?,
                       rate_per_hour=?, interval_uncertain=0, spike=0,
                       delta_comments=?, delta_views=? WHERE id=?""",
                    (
                        first_total, elapsed, first_total * 3600 / elapsed,
                        int(first_comments) if first_comments is not None else None,
                        int(first_views) if first_views is not None else None,
                        first_actual["id"],
                    ),
                )
            return result.rowcount == 1

    def recalculate_history_completeness(self, max_age_seconds: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """UPDATE posts SET history_complete=CASE
                   WHEN baseline_from_publication=1
                     OR first_observation_age_seconds<=? THEN 1 ELSE 0 END""",
                (max_age_seconds,),
            )

    def post_message_ids(self, post_id: int) -> list[int]:
        with self.connect() as conn:
            return [
                int(row[0]) for row in conn.execute(
                    "SELECT telegram_message_id FROM post_messages WHERE post_id=? ORDER BY telegram_message_id",
                    (post_id,),
                )
            ]

    def insert_snapshot(
        self,
        post_id: int,
        measured_at: datetime,
        age_seconds: int,
        total: int,
        reactions: Mapping[str, int],
        raw_state: Any,
        poll_interval_minutes: int,
        jump_min_abs: int,
        jump_min_ratio: float,
        comments_count: int | None = None,
        views_count: int | None = None,
    ) -> bool:
        bucket = int(measured_at.timestamp()) // (poll_interval_minutes * 60)
        with self.connect() as conn:
            previous = conn.execute(
                "SELECT * FROM reaction_snapshots WHERE post_id=? ORDER BY measured_at DESC LIMIT 1",
                (post_id,),
            ).fetchone()
            delta_total: int | None = None
            delta_json: str | None = None
            delta_seconds: int | None = None
            rate: float | None = None
            uncertain = False
            spike = False
            delta_comments: int | None = None
            delta_views: int | None = None
            if previous:
                delta_total = total - int(previous["total_reactions"])
                previous_reactions = json.loads(previous["reactions_json"])
                delta_json = json.dumps(
                    delta_by_reaction(reactions, previous_reactions), ensure_ascii=False, sort_keys=True
                )
                previous_time = datetime.fromisoformat(previous["measured_at"])
                delta_seconds = max(1, int((measured_at - previous_time).total_seconds()))
                rate = delta_total * 3600 / delta_seconds
                uncertain = interval_uncertain(delta_seconds, poll_interval_minutes)
                if comments_count is not None and previous["comments_count"] is not None:
                    delta_comments = comments_count - int(previous["comments_count"])
                if views_count is not None and previous["views_count"] is not None:
                    delta_views = views_count - int(previous["views_count"])
            result = conn.execute(
                """INSERT OR IGNORE INTO reaction_snapshots(
                    post_id, measured_at, measurement_bucket, age_seconds, total_reactions,
                    reactions_json, raw_state_json, delta_total, delta_by_reaction_json,
                    delta_seconds, rate_per_hour, interval_uncertain, spike,
                    comments_count, delta_comments, views_count, delta_views,
                    synthetic, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    post_id, iso(measured_at), bucket, age_seconds, total,
                    json.dumps(dict(reactions), ensure_ascii=False, sort_keys=True),
                    json.dumps(raw_state, ensure_ascii=False), delta_total, delta_json,
                    delta_seconds, rate, int(uncertain), int(spike), comments_count,
                    delta_comments, views_count, delta_views, 0, iso(utc_now()),
                ),
            )
            return result.rowcount == 1

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO app_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def get_state(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key=?", (key,)).fetchone()
            return str(row[0]) if row else None

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, params))
