from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .analytics import age_seconds
from .config import Settings
from .database import Database, iso
from .public_web import snapshot_interval_minutes, snapshot_is_due
from .vk import VkClient

logger = logging.getLogger(__name__)


class VkCollector:
    """Collect raw public counters from configured VK communities."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        client: VkClient | None = None,
    ):
        if not settings.vk_access_token and client is None:
            raise ValueError("VK_ACCESS_TOKEN is required")
        self.settings = settings
        self.db = db
        self.client = client or VkClient(
            settings.vk_access_token or "", settings.vk_api_version,
        )

    async def close(self) -> None:
        await self.client.close()

    async def poll_cycle(self) -> None:
        started = datetime.now(timezone.utc)
        accounts = self.db.list_platform_accounts(platform="vk", enabled_only=True)
        error_count = 0
        self.db.set_state("vk_poll_last_started_at", iso(started))
        logger.info("VK polling started accounts=%s", len(accounts))
        for account in accounts:
            try:
                await self._poll_account(account)
            except Exception as exc:
                error_count += 1
                self.db.finish_platform_account_check(
                    int(account["id"]), datetime.now(timezone.utc), str(exc),
                )
                logger.exception("VK account %s polling failed", account["external_key"])
        completed = datetime.now(timezone.utc)
        duration = (completed - started).total_seconds()
        self.db.set_state("vk_poll_last_completed_at", iso(completed))
        self.db.set_state("vk_poll_last_duration_seconds", f"{duration:.3f}")
        self.db.set_state("vk_poll_last_error_count", str(error_count))
        self.db.set_state("vk_poll_last_account_count", str(len(accounts)))
        logger.info(
            "VK polling complete duration=%.2fs accounts=%s errors=%s",
            duration, len(accounts), error_count,
        )

    async def _poll_account(self, account: Any) -> None:
        measured_at = datetime.now(timezone.utc)
        reference = str(account["external_key"])
        community = await self.client.community(reference)
        self.db.update_platform_account_metadata(
            int(account["id"]),
            native_id=str(community.id),
            username=community.screen_name,
            title=community.name,
            url=f"https://vk.com/{community.screen_name}",
            subscriber_count=community.members_count,
            measured_at=measured_at,
        )
        posts = await self.client.wall(
            community.id, count=min(self.settings.discovery_limit, 100),
        )
        cutoff = measured_at - timedelta(hours=self.settings.track_post_for_hours)
        inserted = 0
        wall_keys = {post.external_key for post in posts}
        stored = self.db.list_platform_posts(
            platform="vk", account_id=int(account["id"]), published_after=cutoff,
        )
        due_ids: list[str] = []
        for row in stored:
            external_id = str(row["external_id"])
            if external_id in wall_keys:
                continue
            published_at = datetime.fromisoformat(str(row["published_at"]))
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            interval = snapshot_interval_minutes(
                age_seconds(published_at, measured_at), self.settings,
            )
            if snapshot_is_due(
                self.db.latest_platform_snapshot_at(int(row["id"])), measured_at, interval,
            ):
                due_ids.append(external_id)
        for offset in range(0, len(due_ids), 100):
            posts.extend(await self.client.posts(due_ids[offset:offset + 100]))
        for post in posts:
            if post.published_at < cutoff:
                continue
            post_id = self.db.upsert_platform_post(
                int(account["id"]), post.external_key, post.published_at,
                measured_at, post.post_type,
                f"https://vk.com/wall{post.external_key}", post.raw,
            )
            interval_minutes = snapshot_interval_minutes(
                age_seconds(post.published_at, measured_at), self.settings,
            )
            if not snapshot_is_due(
                self.db.latest_platform_snapshot_at(post_id),
                measured_at,
                interval_minutes,
            ):
                continue
            if self.db.insert_platform_snapshot(
                post_id,
                measured_at,
                age_seconds(post.published_at, measured_at),
                interval_minutes,
                views_count=post.views,
                reactions_count=post.likes,
                comments_count=post.comments,
                shares_count=post.reposts,
                raw={
                    "views": post.views,
                    "likes": post.likes,
                    "comments": post.comments,
                    "reposts": post.reposts,
                },
            ):
                inserted += 1
        self.db.finish_platform_account_check(
            int(account["id"]), datetime.now(timezone.utc), None,
        )
        logger.info(
            "VK %s: discovered=%s snapshots=%s",
            community.screen_name, len(posts), inserted,
        )
