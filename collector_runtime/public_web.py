from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup, Tag

from .config import Settings
from .models import ReactionState

@dataclass(frozen=True)
class PublicPost:
    message_id: int
    published_at: datetime
    post_type: str
    reactions: ReactionState
    views_count: int | None
    is_repost: bool = False


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


def _public_node_is_unavailable(node: Tag) -> bool:
    """Recognize Telegram's HTTP-200 placeholder for an unavailable post."""
    classes = set(node.get("class") or [])
    if "text_not_supported_wrap" not in classes:
        return False
    if "service_message" in classes:
        return True
    label = node.select_one(".message_media_not_supported_label")
    return bool(
        label
        and label.get_text(" ", strip=True).casefold() == "service message"
    )


def public_post_is_deleted(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    error = soup.select_one(".tgme_widget_message_error")
    if error and "not found" in error.get_text(" ", strip=True).casefold():
        return True
    return any(
        _public_node_is_unavailable(node)
        for node in soup.select("div.tgme_widget_message[data-post]")
    )


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
    scheduled_at: datetime,
    interval_minutes: int,
    *,
    last_measurement_bucket: int | None = None,
) -> bool:
    """Return whether a new wall-clock collection slot has started.

    Collectors pass their common cycle start as ``scheduled_at``.  Comparing
    slots instead of elapsed time prevents a channel that moves slightly
    earlier within the next cycle from being postponed for a whole cycle.
    """
    if not last_measured_at:
        return True
    previous = datetime.fromisoformat(last_measured_at)
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    slot_seconds = interval_minutes * 60
    previous_slot_for_interval = int(previous.timestamp()) // slot_seconds
    previous_slot = previous_slot_for_interval
    if last_measurement_bucket is not None:
        stored_slot = int(last_measurement_bucket)
        # Buckets created with another age-based interval have a different
        # scale.  A one-slot difference is still the same interval: it means
        # processing crossed a wall-clock boundary after the cycle started.
        if abs(stored_slot - previous_slot_for_interval) <= 1:
            previous_slot = stored_slot
    scheduled_slot = int(scheduled_at.timestamp()) // slot_seconds
    return scheduled_slot > previous_slot


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


def _is_public_repost(node: Tag, username: str) -> bool:
    forwarded = node.select_one(".tgme_widget_message_forwarded_from")
    if forwarded is None:
        return False
    source = forwarded.select_one(".tgme_widget_message_forwarded_from_name[href]")
    if source is None:
        return True
    href = str(source.get("href") or "").split("?", 1)[0].rstrip("/")
    source_username = href.rsplit("/", 1)[-1].lstrip("@").casefold()
    return not source_username or source_username != username.casefold()


def _parse_public_page(soup: BeautifulSoup, username: str) -> list[PublicPost]:
    posts: list[PublicPost] = []
    for node in soup.select("div.tgme_widget_message[data-post]"):
        # Deleted channel posts can keep an embeddable shell with their ID and
        # timestamp. It contains no counters and must not reset the missing
        # confirmation merely because it resembles a regular message node.
        if _public_node_is_unavailable(node):
            continue
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
                _is_public_repost(node, username),
            )
        )
    return sorted(posts, key=lambda post: post.message_id)


def parse_public_page(html: str, username: str) -> list[PublicPost]:
    return _parse_public_page(BeautifulSoup(html, "html.parser"), username)


def older_page_before(html: str) -> int | None:
    """Номер сообщения, с которого начинается предыдущая страница канала.

    Публичный предпросмотр отдаёт за раз лишь горсть сообщений — у активного
    канала это два десятка, а если посты выходят альбомами, то и семь: альбом
    занимает один блок, но съедает несколько номеров. Остальное лежит за
    ссылкой «ещё», и без неё история канала обрывается на том, что попало на
    первую страницу в день подключения.

    Ссылок в разметке может быть две — назад и вперёд; нам нужна та, что ведёт
    к более старым сообщениям, поэтому берём наименьший data-before.
    """
    soup = BeautifulSoup(html, "html.parser")
    values: list[int] = []
    for link in soup.select("a.tme_messages_more[data-before]"):
        raw = link.get("data-before")
        if isinstance(raw, str) and raw.isdigit():
            values.append(int(raw))
    return min(values) if values else None


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
    return PublicChannel(
        title, subscribers, subscriber_display, _parse_public_page(soup, username),
    )
