from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .analytics import age_seconds, history_is_complete
from .config import Settings
from .database import Database, iso
from .max_api import MaxClient
from .public_web import snapshot_interval_minutes, snapshot_is_due

logger = logging.getLogger(__name__)


class MaxCollector:
    def __init__(self, settings: Settings, db: Database, client: MaxClient | None = None):
        if not settings.max_access_token and client is None:
            raise ValueError("MAX_ACCESS_TOKEN is required")
        self.settings = settings
        self.db = db
        self.client = client or MaxClient(
            settings.max_access_token or "", settings.max_api_base,
        )

    async def close(self) -> None:
        await self.client.close()

    async def poll_cycle(self) -> None:
        started = datetime.now(timezone.utc)
        accounts = self.db.list_platform_accounts(platform="max", enabled_only=True)
        errors = 0
        self.db.set_state("max_poll_last_started_at", iso(started))
        for account in accounts:
            try:
                await self._poll_account(account)
            except Exception as exc:
                errors += 1
                self.db.finish_platform_account_check(
                    int(account["id"]), datetime.now(timezone.utc), str(exc),
                )
                logger.exception("MAX account %s polling failed", account["external_key"])
        completed = datetime.now(timezone.utc)
        self.db.set_state("max_poll_last_completed_at", iso(completed))
        self.db.set_state("max_poll_last_error_count", str(errors))
        self.db.set_state("max_poll_last_account_count", str(len(accounts)))
        self.db.set_state(
            "max_poll_last_duration_seconds", f"{(completed - started).total_seconds():.3f}",
        )

    async def _poll_account(self, account: Any) -> None:
        native_id = str(account["native_id"] or "").strip()
        if not native_id or not native_id.lstrip("-").isdigit():
            raise ValueError("Укажите числовой chat_id MAX после добавления бота в канал")
        measured_at = datetime.now(timezone.utc)
        chat_id = int(native_id)
        channel = await self.client.channel(chat_id)
        posts = await self.client.posts(chat_id, min(self.settings.discovery_limit, 100))
        self.db.update_platform_account_metadata(
            int(account["id"]), native_id=str(channel.id),
            username=str(account["username"] or account["external_key"]),
            title=channel.title, url=str(account["url"] or channel.link or ""),
            subscriber_count=channel.participants_count, measured_at=measured_at,
        )
        cutoff = measured_at - timedelta(hours=self.settings.track_post_for_hours)
        for post in posts:
            if post.published_at < cutoff:
                continue
            first_age = age_seconds(post.published_at, measured_at)
            post_id = self.db.upsert_platform_post(
                int(account["id"]), post.id, post.published_at,
                measured_at, "post", post.url, post.raw,
                history_complete=history_is_complete(
                    first_age, self.settings.complete_history_max_first_age_minutes,
                ),
                is_repost=post.is_repost,
            )
            interval = snapshot_interval_minutes(
                first_age, self.settings,
            )
            if snapshot_is_due(
                self.db.latest_platform_snapshot_at(post_id), measured_at, interval,
            ):
                self.db.insert_platform_snapshot(
                    post_id, measured_at, first_age, interval,
                    views_count=post.views, reactions_count=None,
                    comments_count=post.comments, shares_count=post.reposts,
                    raw={
                        "views": post.views, "comments": post.comments,
                        "reposts": post.reposts,
                    },
                )
        self.db.finish_platform_account_check(int(account["id"]), measured_at, None)
