from __future__ import annotations

import re
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .analytics import age_seconds, history_is_complete
from .config import Settings
from .database import Database, iso
from .models import LogicalPost
from .reactions import choose_album_reactions, parse_message_reactions
from .public_web import snapshot_interval_minutes, snapshot_is_due
from .telegram_client import TelegramReader

logger = logging.getLogger(__name__)


def normalize_channel_ref(value: str) -> str:
    value = value.strip().rstrip("/")
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    parts = [part for part in value.lstrip("@").split("/") if part]
    # Telegram's public-preview URLs use /s/<username>.  The /s/ segment is
    # not a channel name and must never be saved as one.
    if parts and parts[0].lower() == "s":
        parts.pop(0)
    value = parts[0] if parts else ""
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
        raise ValueError("Invalid Telegram channel username")
    return value


def post_type(message: Any) -> str:
    media = getattr(message, "media", None)
    if media is None:
        return "text"
    name = media.__class__.__name__.lower()
    for kind in ("photo", "document", "poll", "webpage", "contact", "geo"):
        if kind in name:
            return kind
    return name.removeprefix("messagemedia").lower() or "media"


def is_published_post(message: Any) -> bool:
    return bool(
        message
        and getattr(message, "id", None)
        and getattr(message, "date", None)
        and getattr(message, "action", None) is None
    )


def logical_views(messages: Iterable[Any]) -> int | None:
    """Return the visible view counter for a Telegram post or album.

    Telegram may repeat the same counter on album elements.  Taking the
    maximum avoids multiplying one logical post's audience by its item count.
    """
    values = [int(value) for message in messages if (value := getattr(message, "views", None)) is not None]
    return max(values) if values else None


def logical_comments(messages: Iterable[Any]) -> int | None:
    """Return the reply/comment counter for a Telegram post or album."""
    values: list[int] = []
    for message in messages:
        replies = getattr(message, "replies", None)
        value = getattr(replies, "replies", None) if replies is not None else None
        if value is not None:
            values.append(int(value))
    return max(values) if values else None


def is_channel_repost(message: Any) -> bool:
    """Return whether a Telegram message was forwarded from another channel."""
    forwarded = getattr(message, "fwd_from", None)
    source = getattr(forwarded, "from_id", None) if forwarded is not None else None
    source_channel_id = getattr(source, "channel_id", None)
    if source_channel_id is None:
        return False
    destination = getattr(message, "peer_id", None)
    destination_channel_id = getattr(destination, "channel_id", None)
    return (
        destination_channel_id is None
        or int(source_channel_id) != int(destination_channel_id)
    )


def group_logical_posts(messages: Iterable[Any]) -> list[LogicalPost]:
    groups: dict[str, list[Any]] = defaultdict(list)
    for message in messages:
        if not is_published_post(message):
            continue
        grouped_id = getattr(message, "grouped_id", None)
        key = f"g:{grouped_id}" if grouped_id is not None else f"m:{message.id}"
        groups[key].append(message)

    logical: list[LogicalPost] = []
    for group in groups.values():
        group.sort(key=lambda item: item.id)
        grouped_id = getattr(group[0], "grouped_id", None)
        if grouped_id is not None:
            state, ambiguous = choose_album_reactions(group)
            kind = "album"
        else:
            state = parse_message_reactions(group[0])
            ambiguous = False
            kind = post_type(group[0])
        published_at = min(message.date for message in group)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        logical.append(
            LogicalPost(
                tuple(message.id for message in group), grouped_id, published_at,
                kind, state, ambiguous, any(is_channel_repost(message) for message in group),
            )
        )
    return sorted(logical, key=lambda item: item.published_at)


class Collector:
    def __init__(self, settings: Settings, db: Database, reader: TelegramReader):
        self.settings = settings
        self.db = db
        self.reader = reader

    async def poll_cycle(self) -> None:
        started = datetime.now(timezone.utc)
        channels = self.db.list_channels(enabled_only=True)
        error_count = 0
        self.db.set_state("poll_last_started_at", iso(started))
        logger.info("polling started")
        for channel in channels:
            try:
                await self._poll_channel(channel)
            except Exception as exc:
                if exc.__class__.__name__ == "FloodWaitError":
                    wait_seconds = int(getattr(exc, "seconds", 60))
                    logger.warning("Telegram FloodWait: sleeping %s seconds", wait_seconds)
                    await asyncio.sleep(wait_seconds)
                    try:
                        await self._poll_channel(channel)
                    except Exception as retry_exc:
                        error_count += 1
                        self.db.finish_channel_check(channel["id"], 0, str(retry_exc))
                        logger.exception("@%s polling failed after FloodWait", channel["username"])
                else:
                    error_count += 1
                    self.db.finish_channel_check(channel["id"], 0, str(exc))
                    logger.exception("@%s polling failed", channel["username"])
        completed = datetime.now(timezone.utc)
        duration = (completed - started).total_seconds()
        self.db.set_state("last_poll", iso(completed))
        self.db.set_state("poll_last_completed_at", iso(completed))
        self.db.set_state("poll_last_duration_seconds", f"{duration:.3f}")
        self.db.set_state("poll_last_error_count", str(error_count))
        self.db.set_state("poll_last_channel_count", str(len(channels)))
        next_poll = started + timedelta(minutes=self.settings.poll_interval_minutes)
        self.db.set_state("next_poll", iso(next_poll))
        logger.info(
            "polling complete duration=%.2fs channels=%s errors=%s",
            duration, len(channels), error_count,
        )

    async def _poll_channel(self, channel: Any) -> None:
        entity = await self.reader.client.get_entity(channel["username"])
        if not bool(getattr(entity, "broadcast", False)):
            raise ValueError(f"@{channel['username']} is not a broadcast channel")
        username = getattr(entity, "username", None) or channel["username"]
        self.db.update_channel_identity(
            channel["id"], int(entity.id), getattr(entity, "title", username), username
        )
        min_id = max(0, int(channel["last_seen_message_id"]) - self.settings.discovery_overlap)
        recent = [
            message
            async for message in self.reader.client.iter_messages(
                entity, limit=self.settings.discovery_limit, min_id=min_id
            )
        ]
        now = datetime.now(timezone.utc)
        max_seen = int(channel["last_seen_message_id"])
        for logical in group_logical_posts(recent):
            first_age = age_seconds(logical.published_at, now)
            key = f"g:{logical.grouped_id}" if logical.grouped_id else f"m:{logical.message_ids[0]}"
            post_id = self.db.add_post(
                channel["id"], key, logical.message_ids, logical.grouped_id,
                logical.published_at, now, first_age,
                history_is_complete(
                    first_age, self.settings.complete_history_max_first_age_minutes
                ),
                logical.post_type, logical.ambiguous_reactions,
                is_repost=logical.is_repost,
            )
            self.db.mark_post_available(post_id)
            if logical.ambiguous_reactions:
                logger.warning("@%s album %s returned inconsistent reaction states", username, key)
            max_seen = max(max_seen, *logical.message_ids)

        cutoff = now - timedelta(hours=self.settings.track_post_for_hours)
        active = self.db.active_posts(channel["id"], iso(cutoff))
        for post in active:
            published_at = datetime.fromisoformat(post["published_at"])
            measured = datetime.now(timezone.utc)
            interval_minutes = snapshot_interval_minutes(
                age_seconds(published_at, measured), self.settings,
            )
            if not snapshot_is_due(
                post["last_measured_at"], measured, interval_minutes,
            ):
                continue
            ids = self.db.post_message_ids(post["id"])
            fetched = await self.reader.client.get_messages(entity, ids=ids)
            fetched = [message for message in fetched if message is not None]
            if not fetched:
                detected = datetime.now(timezone.utc)
                count, confirmed = self.db.record_post_missing(
                    post["id"], detected, "mtproto_empty_get_messages",
                    self.settings.deletion_confirmation_checks,
                )
                logger.warning(
                    "@%s/%s missing check=%s/%s reason=mtproto_empty_get_messages "
                    "detected_at=%s confirmed=%s",
                    username, post["telegram_message_id"], count,
                    self.settings.deletion_confirmation_checks, iso(detected), confirmed,
                )
                continue
            self.db.mark_post_available(post["id"])
            self.db.set_post_repost(
                post["id"], any(is_channel_repost(message) for message in fetched),
            )
            if post["telegram_grouped_id"]:
                state, ambiguous = choose_album_reactions(fetched)
            else:
                state, ambiguous = parse_message_reactions(fetched[0]), False
            measured = datetime.now(timezone.utc)
            inserted = self.db.insert_snapshot(
                post["id"], measured, age_seconds(published_at, measured), state.total,
                state.reactions, state.raw, interval_minutes,
                self.settings.jump_min_abs, self.settings.jump_min_ratio,
                comments_count=logical_comments(fetched),
                views_count=logical_views(fetched),
            )
            if inserted:
                latest = self.db.query(
                    "SELECT delta_total, spike FROM reaction_snapshots WHERE post_id=? ORDER BY measured_at DESC LIMIT 1",
                    (post["id"],),
                )[0]
                logger.info(
                    "@%s/%s snapshot total=%s delta=%s views=%s comments=%s",
                    username, post["telegram_message_id"], state.total, latest["delta_total"],
                    logical_views(fetched), logical_comments(fetched),
                )
                if latest["spike"]:
                    logger.warning("@%s/%s reaction spike detected", username, post["telegram_message_id"])
            if ambiguous:
                logger.warning("@%s/%s ambiguous album reaction state", username, post["telegram_message_id"])
        self.db.finish_channel_check(channel["id"], max_seen)
        logger.info("@%s: %s active posts", username, len(active))
