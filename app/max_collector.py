from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .analytics import age_seconds, history_is_complete
from .config import Settings
from .database import Database, iso
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
        reference = str(account["url"] or account["external_key"])
        channel = await self.client.resolve_channel(
            reference, int(native_id) if native_id else None,
        )
        chat_id = channel.id
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
        )
        due_ids: list[str] = []
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
                row["latest_measured_at"], measured_at, interval,
            ):
                due_ids.append(external_id)
        for offset in range(0, len(due_ids), 100):
            posts.extend(await self.client.posts_by_ids(
                chat_id, due_ids[offset:offset + 100],
            ))
        with self.db.connect() as conn:
            for post in {post.id: post for post in posts}.values():
                if post.published_at < cutoff:
                    continue
                first_age = age_seconds(post.published_at, measured_at)
                post_id = self.db.upsert_platform_post(
                    int(account["id"]), post.id, post.published_at,
                    measured_at, post.post_type, post.url, post.raw,
                    history_complete=history_is_complete(
                        first_age, self.settings.complete_history_max_first_age_minutes,
                    ),
                    is_repost=post.is_repost, _conn=conn,
                )
                interval = snapshot_interval_minutes(
                    first_age, self.settings,
                )
                if snapshot_is_due(
                    self.db.latest_platform_snapshot_at(post_id, _conn=conn),
                    measured_at, interval,
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
                        _conn=conn,
                    )
        self.db.finish_platform_account_check(int(account["id"]), measured_at, None)
