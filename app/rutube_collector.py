from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .analytics import age_seconds, history_is_complete
from .config import Settings
from .database import Database, iso
from .public_web import snapshot_interval_minutes, snapshot_is_due
from .rutube import RutubeClient

logger = logging.getLogger(__name__)


class RutubeCollector:
    def __init__(
        self, settings: Settings, db: Database,
        client: RutubeClient | None = None,
    ):
        self.settings = settings
        self.db = db
        self.client = client or RutubeClient(settings.rutube_api_base)

    async def close(self) -> None:
        await self.client.close()

    async def poll_cycle(self) -> None:
        started = datetime.now(timezone.utc)
        if not snapshot_is_due(
            self.db.get_state("rutube_poll_last_completed_at"), started,
            self.settings.rutube_first_three_days_poll_interval_minutes,
        ):
            logger.info("RUTUBE polling skipped: hourly interval has not elapsed")
            return
        accounts = self.db.list_platform_accounts(platform="rutube", enabled_only=True)
        errors = 0
        self.db.set_state("rutube_poll_last_started_at", iso(started))
        for account in accounts:
            try:
                await self._poll_account(account)
            except Exception as exc:
                errors += 1
                self.db.finish_platform_account_check(
                    int(account["id"]), datetime.now(timezone.utc), str(exc),
                )
                logger.exception("RUTUBE account %s polling failed", account["external_key"])
        completed = datetime.now(timezone.utc)
        self.db.set_state("rutube_poll_last_completed_at", iso(completed))
        self.db.set_state(
            "rutube_poll_last_duration_seconds", f"{(completed - started).total_seconds():.3f}",
        )
        self.db.set_state("rutube_poll_last_error_count", str(errors))
        self.db.set_state("rutube_poll_last_account_count", str(len(accounts)))

    async def _poll_account(self, account: Any) -> None:
        measured_at = datetime.now(timezone.utc)
        native_id = (
            int(account["native_id"])
            if account["native_id"] and str(account["native_id"]).isdigit()
            else await self.client.resolve_channel(
                str(account["external_key"]), str(account["url"] or "") or None,
            )
        )
        channel, videos = await self.client.videos(
            native_id, min(self.settings.discovery_limit, 100),
        )
        self.db.update_platform_account_metadata(
            int(account["id"]), native_id=str(channel.id),
            username=str(account["username"] or account["external_key"]),
            title=channel.name, url=str(account["url"] or channel.url),
            subscriber_count=None, measured_at=measured_at,
        )
        cutoff = measured_at - timedelta(hours=self.settings.track_post_for_hours)
        due: list[tuple[Any, int, int]] = []
        for video in videos:
            if video.published_at < cutoff:
                continue
            first_age = age_seconds(video.published_at, measured_at)
            post_id = self.db.upsert_platform_post(
                int(account["id"]), video.id, video.published_at,
                measured_at, "video", video.url, video.raw,
                history_complete=history_is_complete(
                    first_age, self.settings.complete_history_max_first_age_minutes,
                ),
            )
            interval = snapshot_interval_minutes(
                first_age, self.settings,
                platform="rutube",
            )
            if not snapshot_is_due(
                self.db.latest_platform_snapshot_at(post_id), measured_at, interval,
            ):
                continue
            due.append((video, post_id, interval))

        semaphore = asyncio.Semaphore(8)

        async def metrics(video_id: str) -> Any:
            async with semaphore:
                return await self.client.video_metrics(video_id)

        measurements = await asyncio.gather(
            *(metrics(video.id) for video, _, _ in due),
        )
        inserted = 0
        for (video, post_id, interval), engagement in zip(due, measurements):
            if self.db.insert_platform_snapshot(
                post_id, measured_at, age_seconds(video.published_at, measured_at), interval,
                views_count=video.views, reactions_count=engagement.likes,
                comments_count=engagement.comments, shares_count=None,
                raw={"hits": video.views, **engagement.raw},
            ):
                inserted += 1
        self.db.finish_platform_account_check(int(account["id"]), measured_at, None)
        logger.info("RUTUBE %s: discovered=%s snapshots=%s", channel.id, len(videos), inserted)
