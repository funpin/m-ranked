from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .analytics import age_seconds, history_is_complete
from .config import Settings
from .database import Database, iso
from .max_api import max_post_url
from .max_user_api import MaxUserClient, max_username
from .public_web import snapshot_interval_minutes, snapshot_is_due

logger = logging.getLogger(__name__)


class MaxCollector:
    def __init__(self, settings: Settings, db: Database, client: Any | None = None):
        if not settings.max_user_phone and client is None:
            raise ValueError("MAX_USER_PHONE is required")
        if client is None and not settings.max_user_session_ready:
            raise ValueError("Authorize MAX first: python -m app auth-max")
        self.settings = settings
        self.db = db
        self.client = client or MaxUserClient(
            settings.max_user_phone or "", settings.max_session_path,
            settings.max_user_first_name, settings.max_user_last_name,
        )

    async def close(self) -> None:
        await self.client.close()

    async def poll_cycle(self) -> None:
        started = datetime.now(timezone.utc)
        self._cycle_started_at = started
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
        if native_id and not native_id.lstrip("-").isdigit():
            raise ValueError("MAX chat_id должен быть числом")
        measured_at = datetime.now(timezone.utc)
        scheduled_at = getattr(self, "_cycle_started_at", measured_at)
        reference = str(account["url"] or account["external_key"])
        channel = await self.client.resolve_channel(
            reference, int(native_id) if native_id else None,
        )
        chat_id = channel.id
        public_reference = str(
            account["url"] or account["username"] or channel.link
            or account["external_key"]
        )
        posts = await self.client.posts(chat_id, min(self.settings.discovery_limit, 100))
        self.db.update_platform_account_metadata(
            int(account["id"]), native_id=str(channel.id),
            username=max_username(str(account["url"] or account["username"] or account["external_key"])),
            title=channel.title, url=str(account["url"] or channel.link or ""),
            subscriber_count=channel.participants_count, measured_at=measured_at,
        )
        cutoff = measured_at - timedelta(hours=self.settings.track_post_for_hours)
        discovered_ids = {post.id for post in posts}
        stored = self.db.list_platform_posts(
            platform="max", account_id=int(account["id"]), published_after=cutoff,
            include_deleted=False,
        )
        due_rows: dict[str, Any] = {}
        for row in stored:
            external_id = str(row["external_id"])
            if external_id in discovered_ids:
                continue
            published_at = datetime.fromisoformat(str(row["published_at"]))
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            interval = snapshot_interval_minutes(
                age_seconds(published_at, measured_at), self.settings,
            )
            if snapshot_is_due(
                row["latest_measured_at"], scheduled_at, interval,
                last_measurement_bucket=row["latest_measurement_bucket"],
            ):
                due_rows[external_id] = row
        available_point_ids: set[int] = set()
        missing_rows: list[Any] = []
        due_ids = list(due_rows)
        for offset in range(0, len(due_ids), 100):
            requested_ids = due_ids[offset:offset + 100]
            refreshed = await self.client.posts_by_ids(chat_id, requested_ids)
            returned_ids = {post.id for post in refreshed}
            available_point_ids.update(
                int(due_rows[external_id]["id"])
                for external_id in requested_ids if external_id in returned_ids
            )
            missing_rows.extend(
                due_rows[external_id]
                for external_id in requested_ids if external_id not in returned_ids
            )
            posts.extend(refreshed)
        with self.db.connect() as conn:
            for post_id in available_point_ids:
                self.db.mark_platform_post_available(post_id, _conn=conn)
            for row in missing_rows:
                count, confirmed = self.db.record_platform_post_missing(
                    int(row["id"]), measured_at,
                    "max_get_messages_not_found_or_deleted",
                    self.settings.deletion_confirmation_checks,
                    _conn=conn,
                )
                logger.warning(
                    "MAX %s/%s unavailable confirmation=%s/%s deleted=%s",
                    channel.title, row["external_id"], count,
                    self.settings.deletion_confirmation_checks, confirmed,
                )
            for post in {post.id: post for post in posts}.values():
                if post.published_at < cutoff:
                    continue
                first_age = age_seconds(post.published_at, measured_at)
                post_id = self.db.upsert_platform_post(
                    int(account["id"]), post.id, post.published_at,
                    measured_at, post.post_type,
                    max_post_url(public_reference, post.id), post.raw,
                    history_complete=history_is_complete(
                        first_age, self.settings.complete_history_max_first_age_minutes,
                    ),
                    is_repost=post.is_repost, _conn=conn,
                )
                interval = snapshot_interval_minutes(
                    first_age, self.settings,
                )
                last_measured_at, last_bucket = (
                    self.db.latest_platform_snapshot_timing(post_id, _conn=conn)
                )
                if snapshot_is_due(
                    last_measured_at, scheduled_at, interval,
                    last_measurement_bucket=last_bucket,
                ):
                    self.db.insert_platform_snapshot(
                        post_id, measured_at, first_age, interval,
                        views_count=post.views, reactions_count=post.reactions,
                        comments_count=post.comments, shares_count=post.reposts,
                        raw={
                            "views": post.views, "reactions": post.reactions,
                            "reaction_breakdown": post.reaction_breakdown,
                            "comments": post.comments, "reposts": post.reposts,
                        },
                        bucket_at=scheduled_at, _conn=conn,
                    )
        self.db.finish_platform_account_check(int(account["id"]), measured_at, None)
