from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from .analytics import age_seconds
from .config import Settings
from .database import Database, iso
from .maintenance import archive_and_purge
from .models import ReactionState

logger = logging.getLogger(__name__)

POLLING_JITTER_TOLERANCE_SECONDS = 30


@dataclass(frozen=True)
class PublicPost:
    message_id: int
    published_at: datetime
    post_type: str
    reactions: ReactionState
    views_count: int | None


@dataclass(frozen=True)
class PublicChannel:
    title: str | None
    subscribers: int | None
    subscribers_display: str | None
    posts: list[PublicPost]


def parse_compact_count(value: str) -> int:
    cleaned = value.strip().replace("\u00a0", "").upper()
    match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*([KMB]?)$", cleaned)
    if not match:
        return 0
    number = float(match.group(1).replace(",", "."))
    multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[match.group(2)]
    return int(round(number * multiplier))


def parse_exact_subscriber_count(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    extra = soup.select_one(".tgme_page_extra")
    if extra is None:
        return None
    text = extra.get_text(" ", strip=True).replace("\u00a0", " ")
    match = re.search(r"([0-9][0-9\s]*)\s+(?:subscribers|members)\b", text, re.IGNORECASE)
    return int(re.sub(r"\s+", "", match.group(1))) if match else None


def public_post_is_deleted(html: str) -> bool:
    error = BeautifulSoup(html, "html.parser").select_one(".tgme_widget_message_error")
    return bool(error and "not found" in error.get_text(" ", strip=True).casefold())


def snapshot_interval_minutes(
    age_in_seconds: int, settings: Settings, *, platform: str | None = None,
) -> int:
    if platform == "rutube":
        if age_in_seconds < 72 * 3600:
            return settings.rutube_first_three_days_poll_interval_minutes
        if age_in_seconds < 7 * 24 * 3600:
            return settings.rutube_days_4_to_6_poll_interval_minutes
        if age_in_seconds < 14 * 24 * 3600:
            return settings.rutube_days_7_to_13_poll_interval_minutes
        return settings.rutube_day_14_plus_poll_interval_minutes
    if age_in_seconds < 24 * 3600:
        return settings.poll_interval_minutes
    if age_in_seconds < 48 * 3600:
        return settings.second_day_poll_interval_minutes
    if age_in_seconds < 72 * 3600:
        return settings.third_day_poll_interval_minutes
    if age_in_seconds < 7 * 24 * 3600:
        return settings.days_4_to_6_poll_interval_minutes
    if age_in_seconds < 14 * 24 * 3600:
        return settings.days_7_to_13_poll_interval_minutes
    return settings.day_14_plus_poll_interval_minutes


def snapshot_is_due(
    last_measured_at: str | None,
    measured_at: datetime,
    interval_minutes: int,
) -> bool:
    if not last_measured_at:
        return True
    previous = datetime.fromisoformat(last_measured_at)
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    due_after_seconds = max(
        0, interval_minutes * 60 - POLLING_JITTER_TOLERANCE_SECONDS,
    )
    return (measured_at - previous).total_seconds() >= due_after_seconds


def metadata_is_due(
    measured_at: str | None,
    now: datetime,
    refresh_hours: int,
) -> bool:
    if not measured_at:
        return True
    previous = datetime.fromisoformat(measured_at)
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    return (now - previous).total_seconds() >= refresh_hours * 3600


def _reaction_key(span: Tag) -> str:
    if "tgme_reaction_paid" in (span.get("class") or []):
        return "paid:star"
    animated = span.select_one("tg-emoji[emoji-id], tg-emoji[data-emoji-id], [data-emoji-id]")
    if animated:
        emoji_id = animated.get("emoji-id") or animated.get("data-emoji-id")
        if emoji_id:
            return f"custom:{emoji_id}"
    emoji = span.select_one("i.emoji b")
    if emoji and emoji.get_text(strip=True):
        return emoji.get_text(strip=True)
    image = span.select_one("img[alt]")
    if image and image.get("alt"):
        return str(image.get("alt")).strip()
    text = span.get_text(" ", strip=True)
    plain = re.sub(r"\s*[0-9]+(?:[.,][0-9]+)?\s*[KMB]?\s*$", "", text, flags=re.I).strip()
    if plain:
        return plain
    return "unknown:web"


def _post_type(node: Tag) -> str:
    media_count = len(node.select(".tgme_widget_message_photo_wrap, .tgme_widget_message_video_player"))
    if media_count > 1:
        return "album"
    if node.select_one(".tgme_widget_message_photo_wrap"):
        return "photo"
    if node.select_one(".tgme_widget_message_video_player"):
        return "video"
    if node.select_one(".tgme_widget_message_document"):
        return "document"
    if node.select_one(".tgme_widget_message_poll"):
        return "poll"
    return "text"


def parse_public_page(html: str, username: str) -> list[PublicPost]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[PublicPost] = []
    for node in soup.select("div.tgme_widget_message[data-post]"):
        data_post = str(node.get("data-post", ""))
        if "/" not in data_post or data_post.rsplit("/", 1)[0].lower() != username.lower():
            continue
        try:
            message_id = int(data_post.rsplit("/", 1)[1])
        except ValueError:
            continue
        time_node = node.select_one("time[datetime]")
        if not time_node:
            continue
        published = datetime.fromisoformat(str(time_node.get("datetime")))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        reactions: dict[str, int] = {}
        raw: list[dict[str, Any]] = []
        for span in node.select(".tgme_widget_message_reactions .tgme_reaction"):
            key = _reaction_key(span)
            count = parse_compact_count(span.get_text(" ", strip=True))
            reactions[key] = reactions.get(key, 0) + count
            raw.append({"key": key, "displayed_count": span.get_text(" ", strip=True), "count": count})
        views_node = node.select_one(".tgme_widget_message_views")
        views_count = (
            parse_compact_count(views_node.get_text(" ", strip=True))
            if views_node else None
        )
        posts.append(
            PublicPost(
                message_id, published.astimezone(timezone.utc), _post_type(node),
                ReactionState(reactions, sum(reactions.values()), raw), views_count,
            )
        )
    return sorted(posts, key=lambda post: post.message_id)


def parse_public_channel(html: str, username: str) -> PublicChannel:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one(".tgme_channel_info_header_title")
    title = title_node.get_text(" ", strip=True) if title_node else None
    subscriber_display: str | None = None
    for counter in soup.select(".tgme_channel_info_counter"):
        kind = counter.select_one(".counter_type")
        if kind and kind.get_text(strip=True).lower() in {"subscribers", "members"}:
            value = counter.select_one(".counter_value")
            subscriber_display = value.get_text(strip=True) if value else None
            break
    subscribers = parse_compact_count(subscriber_display) if subscriber_display else None
    return PublicChannel(title, subscribers, subscriber_display, parse_public_page(html, username))


class PublicWebCollector:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; m-ranked/1.0; read-only)"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _fetch(self, url: str) -> str:
        response = await self.client.get(url)
        response.raise_for_status()
        return response.text

    async def poll_cycle(self) -> None:
        started = datetime.now(timezone.utc)
        channels = self.db.list_channels(enabled_only=True)
        error_count = 0
        self.db.set_state("poll_last_started_at", iso(started))
        logger.info("public web polling started")
        for channel in channels:
            try:
                await self._poll_channel(channel)
            except Exception as exc:
                error_count += 1
                self.db.finish_channel_check(channel["id"], 0, str(exc))
                logger.exception("@%s public web polling failed", channel["username"])
        try:
            archive_and_purge(self.settings, self.db)
        except Exception:
            error_count += 1
            logger.exception("post archive and retention cleanup failed")
        completed = datetime.now(timezone.utc)
        duration = (completed - started).total_seconds()
        self.db.set_state("last_poll", iso(completed))
        self.db.set_state("poll_last_completed_at", iso(completed))
        self.db.set_state("poll_last_duration_seconds", f"{duration:.3f}")
        self.db.set_state("poll_last_error_count", str(error_count))
        self.db.set_state("poll_last_channel_count", str(len(channels)))
        self.db.set_state(
            "next_poll", iso(started + timedelta(minutes=self.settings.poll_interval_minutes))
        )
        logger.info(
            "public web polling complete duration=%.2fs channels=%s errors=%s",
            duration, len(channels), error_count,
        )

    def _record_missing(
        self, post_id: int, username: str, message_id: int,
        measured: datetime, reason: str,
    ) -> bool:
        count, confirmed = self.db.record_post_missing(
            post_id, measured, reason, self.settings.deletion_confirmation_checks,
        )
        logger.warning(
            "@%s/%s missing check=%s/%s reason=%s detected_at=%s confirmed=%s",
            username, message_id, count, self.settings.deletion_confirmation_checks,
            reason, iso(measured), confirmed,
        )
        return confirmed

    async def _poll_channel(self, channel: Any) -> None:
        username = str(channel["username"])
        page = parse_public_channel(await self._fetch(f"https://t.me/s/{username}"), username)
        feed = page.posts
        if not feed:
            raise ValueError("no public posts found; channel may be private or unavailable")
        now = datetime.now(timezone.utc)
        if metadata_is_due(
            channel["subscriber_measured_at"], now, self.settings.subscriber_refresh_hours
        ):
            exact = parse_exact_subscriber_count(
                await self._fetch(f"https://t.me/{username}")
            )
            subscribers = exact if exact is not None else page.subscribers
            display = (
                f"{subscribers:,}".replace(",", " ")
                if subscribers is not None else page.subscribers_display
            )
            self.db.update_channel_public_metadata(
                channel["id"], page.title, subscribers, display
            )
        else:
            self.db.update_channel_title(channel["id"], page.title)
        current = {post.message_id: post for post in feed}
        max_seen = int(channel["last_seen_message_id"])
        for post in feed:
            first_age = age_seconds(post.published_at, now)
            post_id = self.db.add_post(
                channel["id"], f"m:{post.message_id}", [post.message_id], None,
                post.published_at, now, first_age, False,
                post.post_type, False,
            )
            self.db.mark_post_available(post_id)
            self.db.ensure_publication_baseline(
                post_id, post.published_at, first_age,
                self.settings.complete_history_max_first_age_minutes * 60,
            )
            max_seen = max(max_seen, post.message_id)

        cutoff = now - timedelta(hours=self.settings.track_post_for_hours)
        active = self.db.active_posts(channel["id"], iso(cutoff))
        for stored in active:
            measured = datetime.now(timezone.utc)
            stored_published = datetime.fromisoformat(stored["published_at"])
            interval_minutes = snapshot_interval_minutes(
                age_seconds(stored_published, measured), self.settings
            )
            if not snapshot_is_due(
                stored["last_measured_at"], measured, interval_minutes
            ):
                continue
            mid = int(stored["telegram_message_id"])
            public_post = current.get(mid)
            if public_post is None:
                try:
                    html = await self._fetch(
                        f"https://t.me/{username}/{mid}?embed=1&mode=tme"
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code not in {404, 410}:
                        raise
                    self._record_missing(
                        stored["id"], username, mid, measured,
                        f"telegram_embed_http_{exc.response.status_code}",
                    )
                    continue
                parsed = parse_public_page(html, username)
                public_post = next((post for post in parsed if post.message_id == mid), None)
            if public_post is None:
                if public_post_is_deleted(html):
                    self._record_missing(
                        stored["id"], username, mid, measured,
                        "telegram_embed_post_not_found",
                    )
                    continue
                logger.warning("@%s/%s unavailable in public preview", username, mid)
                continue
            self.db.mark_post_available(stored["id"])
            inserted = self.db.insert_snapshot(
                stored["id"], measured, age_seconds(public_post.published_at, measured),
                public_post.reactions.total, public_post.reactions.reactions,
                public_post.reactions.raw, interval_minutes,
                self.settings.jump_min_abs, self.settings.jump_min_ratio,
                views_count=public_post.views_count,
            )
            if inserted:
                logger.info(
                    "@%s/%s public snapshot total=%s views=%s interval=%sm",
                    username, mid, public_post.reactions.total,
                    public_post.views_count, interval_minutes,
                )
        self.db.finish_channel_check(channel["id"], max_seen)
        logger.info("@%s: %s active public posts", username, len(active))
