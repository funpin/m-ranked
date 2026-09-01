from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .analytics import age_seconds, history_is_complete
from .config import Settings
from .database import Database, iso
from .public_web import snapshot_interval_minutes, snapshot_is_due
from .vk import VkClient

logger = logging.getLogger(__name__)


def validated_vk_metrics(
    post: Any,
    high_watermarks: dict[str, int | None],
) -> tuple[dict[str, int | None], list[str]]:
    """Turn VK's transient resets to zero into missing measurements."""
    metrics = {
        "views": post.views,
        "reactions": post.likes,
        "comments": post.comments,
        "shares": post.reposts,
    }
    ignored: list[str] = []
    for metric, value in metrics.items():
        previous_high = high_watermarks.get(metric)
        if value == 0 and previous_high is not None and previous_high > 0:
            metrics[metric] = None
            ignored.append(metric)
    return metrics, ignored


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
            requests_per_second=settings.vk_requests_per_second,
        )

    async def close(self) -> None:
        await self.client.close()

    async def poll_cycle(self) -> None:
        started = datetime.now(timezone.utc)
        accounts = self.db.list_platform_accounts(platform="vk", enabled_only=True)
        error_count = 0
        self.db.set_state("vk_poll_last_started_at", iso(started))
        logger.info("VK polling started accounts=%s", len(accounts))
        semaphore = asyncio.Semaphore(max(1, int(self.settings.vk_concurrency)))

        async def poll_account(account: Any) -> int:
            async with semaphore:
                try:
                    await self._poll_account(account)
                    return 0
                except Exception as exc:
                    self.db.finish_platform_account_check(
                        int(account["id"]), datetime.now(timezone.utc), str(exc),
                    )
                    logger.exception("VK account %s polling failed", account["external_key"])
                    return 1

        error_count = sum(await asyncio.gather(*(poll_account(row) for row in accounts)))
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
        wall_keys = {
            identity.external_key
            for post in posts
            if (identity := post.identity_for_community(community.id)) is not None
        }
        stored = self.db.list_platform_posts(
            platform="vk", account_id=int(account["id"]), published_after=cutoff,
            include_deleted=False,
        )
        due_rows: dict[str, Any] = {}
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
                row["latest_measured_at"], measured_at, interval,
            ):
                probe_id = str(row["source_external_id"] or external_id)
                due_rows[probe_id] = row
        available_point_ids: set[int] = set()
        missing_rows: list[Any] = []
        due_ids = list(due_rows)
        for offset in range(0, len(due_ids), 100):
            requested_ids = due_ids[offset:offset + 100]
            refreshed = await self.client.posts(requested_ids)
            returned_ids = {post.external_key for post in refreshed}
            available_point_ids.update(
                int(due_rows[external_id]["id"])
                for external_id in requested_ids if external_id in returned_ids
            )
            missing_rows.extend(
                due_rows[external_id]
                for external_id in requested_ids if external_id not in returned_ids
            )
            posts.extend(refreshed)
        posts_by_local_key = {}
        for post in posts:
            identity = post.identity_for_community(community.id)
            if identity is not None:
                posts_by_local_key[identity.external_key] = (post, identity)
        with self.db.connect() as conn:
            for post_id in available_point_ids:
                self.db.mark_platform_post_available(post_id, _conn=conn)
            for row in missing_rows:
                count, confirmed = self.db.record_platform_post_missing(
                    int(row["id"]), measured_at,
                    "vk_wall_get_by_id_not_found_or_deleted",
                    self.settings.deletion_confirmation_checks,
                    _conn=conn,
                )
                logger.warning(
                    "VK %s/%s unavailable confirmation=%s/%s deleted=%s",
                    community.screen_name, row["external_id"], count,
                    self.settings.deletion_confirmation_checks, confirmed,
                )
            for post, identity in posts_by_local_key.values():
                if post.published_at < cutoff:
                    continue
                first_age = age_seconds(post.published_at, measured_at)
                public_external_id = (
                    identity.source_external_key or identity.external_key
                )
                post_id = self.db.upsert_platform_post(
                    int(account["id"]), identity.external_key, post.published_at,
                    measured_at, post.post_type,
                    f"https://vk.ru/wall{public_external_id}", post.raw,
                    history_complete=history_is_complete(
                        first_age, self.settings.complete_history_max_first_age_minutes,
                    ),
                    source_external_id=identity.source_external_key,
                    is_joint=identity.is_joint,
                    additional_author_count=identity.additional_author_count,
                    _conn=conn,
                )
                interval_minutes = snapshot_interval_minutes(
                    first_age, self.settings,
                )
                if not snapshot_is_due(
                    self.db.latest_platform_snapshot_at(post_id, _conn=conn),
                    measured_at,
                    interval_minutes,
                ):
                    continue
                metrics, ignored_metrics = validated_vk_metrics(
                    post,
                    self.db.platform_metric_high_watermarks(post_id, _conn=conn),
                )
                if ignored_metrics:
                    logger.warning(
                        "VK %s/%s ignored transient zero metrics=%s",
                        community.screen_name, identity.external_key,
                        ",".join(ignored_metrics),
                    )
                raw_snapshot: dict[str, Any] = {
                    "views": post.views,
                    "likes": post.likes,
                    "comments": post.comments,
                    "reposts": post.reposts,
                }
                if ignored_metrics:
                    raw_snapshot["ignored_transient_zero_metrics"] = ignored_metrics
                if self.db.insert_platform_snapshot(
                    post_id,
                    measured_at,
                    first_age,
                    interval_minutes,
                    views_count=metrics["views"],
                    reactions_count=metrics["reactions"],
                    comments_count=metrics["comments"],
                    shares_count=metrics["shares"],
                    raw=raw_snapshot,
                    _conn=conn,
                ):
                    inserted += 1
        self.db.finish_platform_account_check(
            int(account["id"]), datetime.now(timezone.utc), None,
        )
        logger.info(
            "VK %s: discovered=%s snapshots=%s",
            community.screen_name, len(posts), inserted,
        )
