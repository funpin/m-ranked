from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from inspect import isawaitable
from typing import Any, Awaitable, Callable, Iterable, Mapping

from app.collector import group_logical_posts, logical_comments, logical_views
from app.max_api import MaxChannel, MaxPost, max_post_url
from app.public_web import PublicChannel
from app.rutube import RutubeChannel, RutubeVideo, RutubeVideoMetrics
from app.telegram_identity import (
    telegram_message_external_id,
    telegram_publication_external_id,
)
from app.vk import VkCommunity, VkPost
from app.vk_collector import validated_vk_metrics

from .model import (
    AccountRef,
    CollectionContext,
    HistoryCompleteness,
    IdentityCandidate,
    IdentityRole,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawPublication,
    utc,
)


Interval = int | Callable[[datetime], int]
BatchFactory = Callable[
    [AccountRef, CollectionContext],
    RawCollectionBatch | Awaitable[RawCollectionBatch],
]


def _interval_seconds(value: Interval, published_at: datetime) -> int:
    interval = value(published_at) if callable(value) else value
    interval = int(interval)
    if interval <= 0:
        raise ValueError("sampling interval must be positive")
    return interval


def _history(
    published_at: datetime,
    discovered_at: datetime,
    complete_history_max_first_age_seconds: int,
) -> HistoryCompleteness:
    age = max(0, int((discovered_at - published_at).total_seconds()))
    return (
        HistoryCompleteness.COMPLETE
        if age <= complete_history_max_first_age_seconds
        else HistoryCompleteness.INCOMPLETE
    )


@dataclass(slots=True)
class DelegatingPlatformCollector:
    """Small adapter seam for gateway orchestration owned by a deployment."""

    platform: Platform
    factory: BatchFactory

    async def collect(
        self,
        account: AccountRef,
        context: CollectionContext,
    ) -> RawCollectionBatch:
        if account.platform != self.platform or context.platform != self.platform:
            raise ValueError("gateway adapter platform mismatch")
        result = self.factory(account, context)
        return await result if isawaitable(result) else result


def telegram_batch(
    *,
    account: AccountRef,
    messages: Iterable[Any],
    observed_at: datetime,
    collected_at: datetime,
    subscriber_count: int | None,
    subscriber_display: str | None = None,
    channel_id: str | int | None = None,
    channel_title: str | None = None,
    channel_username: str | None = None,
    sampling_interval_seconds: Interval = 300,
    complete_history_max_first_age_seconds: int = 360,
    quality: ObservationQuality = ObservationQuality.EXACT,
    source_name: str = "telegram_mtproto",
    source_version: str = "telethon",
) -> RawCollectionBatch:
    observed = utc(observed_at, "observed_at")
    collected = utc(collected_at, "collected_at")
    values = tuple(messages)
    by_id = {
        int(message.id): message
        for message in values
        if getattr(message, "id", None) is not None
    }
    username = channel_username or account.current_username or account.canonical_external_id
    publications: list[RawPublication] = []
    for logical in group_logical_posts(values):
        external_id = telegram_publication_external_id(
            logical.message_ids[0], logical.grouped_id
        )
        group_messages = [by_id[message_id] for message_id in logical.message_ids]
        public_url = (
            f"https://t.me/{username.lstrip('@')}/{logical.message_ids[0]}"
            if username else None
        )
        identities = tuple(
            IdentityCandidate(
                telegram_message_external_id(message_id),
                IdentityRole.ALBUM_MEMBER,
                public_url=(
                    f"https://t.me/{username.lstrip('@')}/{message_id}"
                    if username else None
                ),
            )
            for message_id in logical.message_ids
            if telegram_message_external_id(message_id) != external_id
        )
        source = {
            "gateway": source_name,
            "message_ids": logical.message_ids,
            "grouped_id": logical.grouped_id,
            "views": logical_views(group_messages),
            "comments": logical_comments(group_messages),
            "reactions": logical.reaction_state.raw,
        }
        publications.append(RawPublication(
            external_id=external_id,
            published_at=logical.published_at,
            discovered_at=observed,
            observed_at=observed,
            collected_at=collected,
            publication_type=logical.post_type,
            metrics={
                "views": logical_views(group_messages),
                "reactions": logical.reaction_state.total,
                "comments": logical_comments(group_messages),
                "shares": None,
            },
            source=source,
            public_url=public_url,
            identities=identities,
            reaction_breakdown=logical.reaction_state.reactions,
            quality=quality,
            history_completeness=_history(
                logical.published_at,
                observed,
                complete_history_max_first_age_seconds,
            ),
            is_repost=logical.is_repost,
            group_key=(
                f"telegram:{logical.grouped_id}"
                if logical.grouped_id is not None else None
            ),
            sampling_interval_seconds=_interval_seconds(
                sampling_interval_seconds, logical.published_at,
            ),
            quality_flags={"ambiguous_reactions": logical.ambiguous_reactions},
        ))
    cursor = str(max(by_id)) if by_id else None
    account_source = {
        "gateway": source_name,
        "channel_id": channel_id,
        "username": username,
        "title": channel_title,
    }
    return RawCollectionBatch(
        account=account,
        account_observation=RawAccountObservation(
            observed,
            collected,
            subscriber_count,
            subscriber_display,
            quality,
            username,
            channel_title,
            f"https://t.me/{username.lstrip('@')}" if username else None,
            str(channel_id) if channel_id is not None else None,
            account_source,
        ),
        publications=tuple(publications),
        source_name=source_name,
        source_version=source_version,
        cursor=cursor,
    )


def telegram_public_batch(
    *,
    account: AccountRef,
    channel: PublicChannel,
    observed_at: datetime,
    collected_at: datetime,
    username: str,
    exact_subscriber_count: int | None = None,
    comments: Mapping[int, int | None] | None = None,
    sampling_interval_seconds: Interval = 300,
    complete_history_max_first_age_seconds: int = 360,
    source_name: str = "telegram_public_web",
    source_version: str = "t.me-preview-v1",
) -> RawCollectionBatch:
    observed = utc(observed_at, "observed_at")
    collected = utc(collected_at, "collected_at")
    comment_counts = comments or {}

    def publication_rows(post: Any) -> tuple[RawPublication, ...]:
        history = _history(
            post.published_at,
            observed,
            complete_history_max_first_age_seconds,
        )
        actual = RawPublication(
            external_id=telegram_message_external_id(post.message_id),
            published_at=post.published_at,
            discovered_at=observed,
            observed_at=observed,
            collected_at=collected,
            publication_type=post.post_type,
            metrics={
                "views": post.views_count,
                "reactions": post.reactions.total,
                "comments": comment_counts.get(post.message_id),
                "shares": None,
            },
            source={
                "gateway": source_name,
                "message_id": post.message_id,
                "views": post.views_count,
                "reactions": post.reactions.raw,
                "comments": comment_counts.get(post.message_id),
            },
            public_url=f"https://t.me/{username}/{post.message_id}",
            reaction_breakdown=post.reactions.reactions,
            quality=ObservationQuality.ROUNDED,
            metric_quality={
                "comments": (
                    ObservationQuality.EXACT
                    if post.message_id in comment_counts
                    else ObservationQuality.UNKNOWN
                ),
                "shares": ObservationQuality.UNKNOWN,
            },
            history_completeness=history,
            is_repost=post.is_repost,
            sampling_interval_seconds=_interval_seconds(
                sampling_interval_seconds, post.published_at,
            ),
        )
        if history != HistoryCompleteness.COMPLETE:
            return (actual,)
        baseline = RawPublication(
            external_id=actual.external_id,
            published_at=actual.published_at,
            discovered_at=actual.discovered_at,
            observed_at=actual.published_at,
            collected_at=collected,
            publication_type=actual.publication_type,
            metrics={
                "views": 0,
                "reactions": 0,
                "comments": 0,
                "shares": None,
            },
            source={
                "gateway": source_name,
                "message_id": post.message_id,
                "synthetic": "publication",
            },
            public_url=actual.public_url,
            reaction_breakdown={},
            quality=ObservationQuality.ESTIMATED,
            metric_quality={"shares": ObservationQuality.UNKNOWN},
            history_completeness=HistoryCompleteness.COMPLETE,
            is_repost=actual.is_repost,
            synthetic=True,
            sampling_interval_seconds=actual.sampling_interval_seconds,
        )
        return baseline, actual

    publications = tuple(
        publication
        for post in channel.posts
        for publication in publication_rows(post)
    )
    subscribers = (
        exact_subscriber_count
        if exact_subscriber_count is not None else channel.subscribers
    )
    subscriber_quality = (
        ObservationQuality.EXACT
        if exact_subscriber_count is not None else ObservationQuality.ROUNDED
    )
    return RawCollectionBatch(
        account,
        RawAccountObservation(
            observed,
            collected,
            subscribers,
            (
                str(exact_subscriber_count)
                if exact_subscriber_count is not None else channel.subscribers_display
            ),
            subscriber_quality,
            username,
            channel.title,
            f"https://t.me/{username}",
            source={"gateway": source_name, "username": username},
        ),
        publications,
        source_name,
        source_version,
        str(max((post.message_id for post in channel.posts), default="")) or None,
    )


def vk_batch(
    *,
    account: AccountRef,
    community: VkCommunity,
    posts: Iterable[VkPost],
    observed_at: datetime,
    collected_at: datetime,
    high_watermarks: Mapping[str, Mapping[str, int | None]] | None = None,
    sampling_interval_seconds: Interval = 300,
    complete_history_max_first_age_seconds: int = 360,
    source_version: str = "5.199",
) -> RawCollectionBatch:
    observed = utc(observed_at, "observed_at")
    collected = utc(collected_at, "collected_at")
    watermarks = high_watermarks or {}
    publications: list[RawPublication] = []
    for post in posts:
        identity = post.identity_for_community(community.id)
        if identity is None:
            continue
        metrics, ignored = validated_vk_metrics(
            post, dict(watermarks.get(identity.external_key, {})),
        )
        public_key = identity.source_external_key or identity.external_key
        extra_identities = (
            (
                IdentityCandidate(
                    identity.source_external_key,
                    IdentityRole.JOINT_AUTHOR,
                    public_url=f"https://vk.com/wall{identity.source_external_key}",
                ),
            )
            if identity.source_external_key else ()
        )
        publications.append(RawPublication(
            external_id=identity.external_key,
            source_external_id=identity.source_external_key,
            published_at=post.published_at,
            discovered_at=observed,
            observed_at=observed,
            collected_at=collected,
            publication_type=post.post_type,
            metrics=metrics,
            source={
                "gateway": "vk_official_api",
                "owner_id": post.owner_id,
                "post_id": post.post_id,
                "metrics": {
                    "views": post.views,
                    "reactions": post.likes,
                    "comments": post.comments,
                    "shares": post.reposts,
                },
                "ignored_transient_zero_metrics": ignored,
            },
            public_url=f"https://vk.com/wall{public_key}",
            identities=extra_identities,
            quality=ObservationQuality.EXACT,
            suspected_reset_metrics=frozenset(ignored),
            history_completeness=_history(
                post.published_at,
                observed,
                complete_history_max_first_age_seconds,
            ),
            sampling_interval_seconds=_interval_seconds(
                sampling_interval_seconds, post.published_at,
            ),
            quality_flags={
                "joint_post": identity.is_joint,
                "additional_author_count": identity.additional_author_count,
            },
        ))
    return RawCollectionBatch(
        account,
        RawAccountObservation(
            observed,
            collected,
            community.members_count,
            quality=ObservationQuality.EXACT,
            username=community.screen_name,
            title=community.name,
            url=f"https://vk.com/{community.screen_name}",
            native_external_id=str(community.id),
            source={"gateway": "vk_official_api", "community_id": community.id},
        ),
        tuple(publications),
        "vk_official_api",
        source_version,
        None,
    )


def max_batch(
    *,
    account: AccountRef,
    channel: MaxChannel,
    posts: Iterable[MaxPost],
    observed_at: datetime,
    collected_at: datetime,
    public_reference: str,
    sampling_interval_seconds: Interval = 300,
    complete_history_max_first_age_seconds: int = 360,
    source_version: str = "pymax",
) -> RawCollectionBatch:
    observed = utc(observed_at, "observed_at")
    collected = utc(collected_at, "collected_at")
    publications = tuple(
        RawPublication(
            external_id=post.id,
            published_at=post.published_at,
            discovered_at=observed,
            observed_at=observed,
            collected_at=collected,
            publication_type=post.post_type,
            metrics={
                "views": post.views,
                "reactions": post.reactions,
                "comments": post.comments,
                "shares": post.reposts,
            },
            source={
                "gateway": "max_user_session",
                "message_id": post.id,
                "views": post.views,
                "reactions": post.reactions,
                "comments": post.comments,
                "shares": post.reposts,
            },
            public_url=post.url or max_post_url(public_reference, post.id),
            reaction_breakdown=post.reaction_breakdown or {},
            quality=ObservationQuality.EXACT,
            metric_quality={
                metric: (
                    ObservationQuality.UNKNOWN
                    if value is None else ObservationQuality.EXACT
                )
                for metric, value in {
                    "views": post.views,
                    "reactions": post.reactions,
                    "comments": post.comments,
                    "shares": post.reposts,
                }.items()
            },
            history_completeness=_history(
                post.published_at,
                observed,
                complete_history_max_first_age_seconds,
            ),
            is_repost=post.is_repost,
            sampling_interval_seconds=_interval_seconds(
                sampling_interval_seconds, post.published_at,
            ),
        )
        for post in posts
    )
    return RawCollectionBatch(
        account,
        RawAccountObservation(
            observed,
            collected,
            channel.participants_count,
            quality=ObservationQuality.EXACT,
            title=channel.title,
            url=channel.link,
            native_external_id=str(channel.id),
            source={"gateway": "max_user_session", "chat_id": channel.id},
        ),
        publications,
        "max_user_session",
        source_version,
        None,
    )


def rutube_batch(
    *,
    account: AccountRef,
    channel: RutubeChannel,
    videos: Iterable[RutubeVideo],
    metrics: Mapping[str, RutubeVideoMetrics | None],
    observed_at: datetime,
    collected_at: datetime,
    subscriber_count: int | None,
    sampling_interval_seconds: Interval = 3600,
    complete_history_max_first_age_seconds: int = 360,
    source_version: str = "public-api-v1",
) -> RawCollectionBatch:
    observed = utc(observed_at, "observed_at")
    collected = utc(collected_at, "collected_at")
    publications: list[RawPublication] = []
    for video in videos:
        engagement = metrics.get(video.id)
        likes = engagement.likes if engagement is not None else None
        comments = engagement.comments if engagement is not None else None
        publications.append(RawPublication(
            external_id=video.id,
            published_at=video.published_at,
            discovered_at=observed,
            observed_at=observed,
            collected_at=collected,
            publication_type="video",
            metrics={
                "views": video.views,
                "reactions": likes,
                "comments": comments,
                "shares": None,
            },
            source={
                "gateway": "rutube_public_api",
                "video_id": video.id,
                "views": video.views,
                "engagement": engagement.raw if engagement is not None else None,
            },
            public_url=video.url,
            quality=(
                ObservationQuality.EXACT
                if engagement is not None
                   and likes is not None
                   and comments is not None
                else ObservationQuality.DEGRADED
            ),
            metric_quality={
                "reactions": (
                    ObservationQuality.EXACT
                    if likes is not None else ObservationQuality.DEGRADED
                ),
                "comments": (
                    ObservationQuality.EXACT
                    if comments is not None else ObservationQuality.DEGRADED
                ),
                "shares": ObservationQuality.UNKNOWN,
            },
            history_completeness=_history(
                video.published_at,
                observed,
                complete_history_max_first_age_seconds,
            ),
            sampling_interval_seconds=_interval_seconds(
                sampling_interval_seconds, video.published_at,
            ),
            quality_flags={"engagement_request_degraded": engagement is None},
        ))
    return RawCollectionBatch(
        account,
        RawAccountObservation(
            observed,
            collected,
            subscriber_count,
            quality=(
                ObservationQuality.EXACT
                if subscriber_count is not None else ObservationQuality.DEGRADED
            ),
            title=channel.name,
            url=channel.url,
            native_external_id=str(channel.id),
            source={"gateway": "rutube_public_api", "channel_id": channel.id},
        ),
        tuple(publications),
        "rutube_public_api",
        source_version,
        None,
    )
