from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
import logging
from typing import Any, Callable

import httpx

from app.analytics import age_seconds
from app.collector import normalize_channel_ref
from app.config import Settings
from app.max_user_api import MaxUserClient
from app.public_web import (
    PublicChannel,
    parse_exact_subscriber_count,
    parse_public_channel,
    parse_public_page,
    public_post_is_deleted,
    snapshot_interval_minutes,
)
from app.rutube import RutubeClient, RutubeVideoMetrics
from app.telegram_client import TelegramReader
from app.telegram_identity import (
    parse_telegram_external_id,
    telegram_message_external_id,
)
from app.telegram_web import TelegramWebSession
from app.vk import VkClient

from .adapters import (
    max_batch,
    rutube_batch,
    telegram_batch,
    telegram_public_batch,
    vk_batch,
)
from .model import (
    AccountRef,
    CollectionContext,
    DeletionProbeOutcome,
    IdentityCandidate,
    IdentityRole,
    Platform,
    RawCollectionBatch,
    RawDeletionProbe,
    TrackedPublication,
    utc,
)
from .normalize import sanitize_error_code
from .ports import MetricHistoryReader, PublicationTrackingReader, UtcClock
from .tracking import (
    by_chunks,
    deletion_confirmation_threshold,
    missing_probe,
    plan_refresh,
    transient_probe,
    unsupported_probe,
)


logger = logging.getLogger(__name__)


def _reference(account: AccountRef) -> str:
    return (
        account.current_url
        or account.current_username
        or account.canonical_external_id
    )


def _interval(
    settings: Settings,
    observed_at: datetime,
    *,
    platform: str | None = None,
) -> Callable[[datetime], int]:
    def seconds(published_at: datetime) -> int:
        return 60 * snapshot_interval_minutes(
            age_seconds(published_at, observed_at),
            settings,
            platform=platform,
        )

    return seconds


def _times(clock: UtcClock) -> tuple[datetime, datetime]:
    observed = utc(clock.now(), "gateway.observed_at")
    collected = utc(clock.now(), "gateway.collected_at")
    if collected < observed:
        raise ValueError("gateway clock moved backwards")
    return observed, collected


def _tracking_reader(value: Any) -> PublicationTrackingReader | None:
    return value if callable(getattr(value, "tracked_publications", None)) else None


def _telegram_ids(publication: TrackedPublication) -> tuple[int, ...]:
    candidates = (
        publication.external_id,
        *publication.identity_external_ids,
    )
    message_ids: list[int] = []
    for value in candidates:
        try:
            namespace, identifier = parse_telegram_external_id(str(value))
        except ValueError:
            continue
        if namespace == "m":
            message_ids.append(identifier)
    return tuple(dict.fromkeys(message_ids))


def _deduplicate(values: list[Any], key: Callable[[Any], Any]) -> list[Any]:
    result: dict[Any, Any] = {}
    for value in values:
        result[key(value)] = value
    return list(result.values())


class TelegramMtprotoCollector:
    platform = Platform.TELEGRAM

    def __init__(
        self,
        settings: Settings,
        clock: UtcClock,
        tracking: PublicationTrackingReader | None = None,
    ) -> None:
        api_id, api_hash = settings.require_telegram()
        self.settings = settings
        self.clock = clock
        self.reader = TelegramReader(api_id, api_hash, settings.telegram_session_path)
        self.tracking = tracking
        self._connect_lock = asyncio.Lock()
        self._connected = False

    async def _connect(self) -> None:
        if self._connected:
            return
        async with self._connect_lock:
            if not self._connected:
                await self.reader.connect()
                self._connected = True

    async def collect(
        self, account: AccountRef, context: CollectionContext,
    ) -> RawCollectionBatch:
        await self._connect()
        reference = account.current_username or account.canonical_external_id
        entity = await self.reader.client.get_entity(reference)
        if not bool(getattr(entity, "broadcast", False)):
            raise ValueError("Telegram entity is not a broadcast channel")
        messages = [
            message
            async for message in self.reader.client.iter_messages(
                entity,
                limit=self.settings.discovery_limit,
            )
        ]
        observed, collected = _times(self.clock)
        initial = telegram_batch(
            account=account,
            messages=messages,
            observed_at=observed,
            collected_at=collected,
            subscriber_count=getattr(entity, "participants_count", None),
            channel_id=getattr(entity, "id", None),
            channel_title=getattr(entity, "title", account.current_title),
            channel_username=getattr(entity, "username", account.current_username),
            sampling_interval_seconds=_interval(self.settings, observed),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
        )
        plan = plan_refresh(
            tracking=self.tracking,
            account=account,
            context=context,
            settings=self.settings,
            observed_at=observed,
            discovered_external_ids={
                publication.external_id for publication in initial.publications
            },
        )
        message_ids = {
            publication.id: _telegram_ids(publication)
            for publication in plan.publications
        }
        fetched_by_id: dict[int, Any] = {}
        errors_by_id: dict[int, BaseException] = {}
        all_ids = tuple(dict.fromkeys(
            message_id
            for ids in message_ids.values()
            for message_id in ids
        ))
        for chunk in by_chunks(all_ids, 100):
            try:
                fetched = await self.reader.client.get_messages(entity, ids=list(chunk))
            except Exception as error:
                errors_by_id.update((message_id, error) for message_id in chunk)
                continue
            items = fetched if isinstance(fetched, (list, tuple)) else (fetched,)
            fetched_by_id.update(
                (int(message.id), message)
                for message in items
                if message is not None and getattr(message, "id", None) is not None
            )

        probes: list[RawDeletionProbe] = []
        refreshed_messages: list[Any] = []
        for publication in plan.publications:
            ids = message_ids[publication.id]
            if not ids:
                probes.append(unsupported_probe(
                    publication,
                    observed,
                    self.settings,
                    "telegram_mtproto_identity_unsupported",
                ))
                continue
            failure = next(
                (errors_by_id[message_id] for message_id in ids if message_id in errors_by_id),
                None,
            )
            if failure is not None:
                probes.append(transient_probe(
                    publication,
                    observed,
                    self.settings,
                    "telegram_mtproto",
                    failure,
                ))
                continue
            available = [
                fetched_by_id[message_id]
                for message_id in ids
                if message_id in fetched_by_id
            ]
            if not available:
                probes.append(missing_probe(
                    publication,
                    observed,
                    self.settings,
                    "telegram_mtproto_empty_get_messages",
                ))
                continue
            refreshed_messages.extend(available)

        if not plan.publications:
            return replace(initial, refresh_cursor=plan.next_cursor)
        final_collected = utc(self.clock.now(), "gateway.collected_at")
        if final_collected < observed:
            raise ValueError("gateway clock moved backwards")
        combined = _deduplicate(
            [*messages, *refreshed_messages],
            lambda message: int(message.id),
        )
        final = telegram_batch(
            account=account,
            messages=combined,
            observed_at=observed,
            collected_at=final_collected,
            subscriber_count=getattr(entity, "participants_count", None),
            channel_id=getattr(entity, "id", None),
            channel_title=getattr(entity, "title", account.current_title),
            channel_username=getattr(entity, "username", account.current_username),
            sampling_interval_seconds=_interval(self.settings, observed),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
        )
        return replace(
            final,
            deletion_probes=tuple(probes),
            refresh_cursor=plan.next_cursor,
        )

    async def close(self) -> None:
        await self.reader.disconnect()
        self._connected = False


class TelegramPublicWebCollector:
    platform = Platform.TELEGRAM

    def __init__(
        self,
        settings: Settings,
        clock: UtcClock,
        *,
        comments_reader: TelegramWebSession | None = None,
        client: httpx.AsyncClient | None = None,
        tracking: PublicationTrackingReader | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.comments_reader = comments_reader
        self.tracking = tracking
        self.client = client or httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; m-ranked/target; read-only)"},
        )
        self._owns_client = client is None

    async def collect(
        self, account: AccountRef, context: CollectionContext,
    ) -> RawCollectionBatch:
        username = normalize_channel_ref(
            account.current_username or account.canonical_external_id,
        )
        feed_response, exact_response = await asyncio.gather(
            self.client.get(f"https://t.me/s/{username}"),
            self.client.get(f"https://t.me/{username}"),
        )
        feed_response.raise_for_status()
        exact_response.raise_for_status()
        channel = parse_public_channel(feed_response.text, username)
        if not channel.posts:
            raise ValueError("Telegram public preview returned no posts")
        comments: dict[int, int | None] = {}
        if self.comments_reader is not None:
            try:
                comments = await self.comments_reader.comments(
                    username, (post.message_id for post in channel.posts),
                )
            except Exception as error:
                logger.warning(
                    "telegram comment gateway degraded account=%s code=%s",
                    account.id,
                    sanitize_error_code(error),
                )
        observed, collected = _times(self.clock)
        initial = telegram_public_batch(
            account=account,
            channel=channel,
            observed_at=observed,
            collected_at=collected,
            username=username,
            exact_subscriber_count=parse_exact_subscriber_count(exact_response.text),
            comments=comments,
            sampling_interval_seconds=_interval(self.settings, observed),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
            source_name=(
                "telegram_web"
                if self.comments_reader is not None else "telegram_public_web"
            ),
        )
        plan = plan_refresh(
            tracking=self.tracking,
            account=account,
            context=context,
            settings=self.settings,
            observed_at=observed,
            discovered_external_ids={
                publication.external_id for publication in initial.publications
            },
        )
        semaphore = asyncio.Semaphore(
            max(1, int(getattr(self.settings, "telegram_web_concurrency", 3))),
        )

        async def point_lookup(
            publication: TrackedPublication,
        ) -> tuple[TrackedPublication, Any | None, RawDeletionProbe | None]:
            ids = _telegram_ids(publication)
            if not ids:
                return publication, None, unsupported_probe(
                    publication,
                    observed,
                    self.settings,
                    "telegram_public_identity_unsupported",
                )
            message_id = ids[0]
            try:
                async with semaphore:
                    response = await self.client.get(
                        f"https://t.me/{username}/{message_id}?embed=1&mode=tme"
                    )
                if response.status_code in {404, 410}:
                    return publication, None, missing_probe(
                        publication,
                        observed,
                        self.settings,
                        f"telegram_public_http_{response.status_code}",
                    )
                response.raise_for_status()
            except Exception as error:
                return publication, None, transient_probe(
                    publication,
                    observed,
                    self.settings,
                    "telegram_public",
                    error,
                )
            parsed = next(
                (
                    post
                    for post in parse_public_page(response.text, username)
                    if post.message_id == message_id
                ),
                None,
            )
            if parsed is not None:
                return publication, parsed, None
            if public_post_is_deleted(response.text):
                return publication, None, missing_probe(
                    publication,
                    observed,
                    self.settings,
                    "telegram_public_deleted_marker",
                )
            return publication, None, RawDeletionProbe(
                publication.id,
                observed,
                DeletionProbeOutcome.TRANSIENT_ERROR,
                "telegram_public_ambiguous_response",
                deletion_confirmation_threshold(self.settings),
            )

        lookups = await asyncio.gather(*(
            point_lookup(publication) for publication in plan.publications
        ))
        present = [
            (publication, post)
            for publication, post, probe in lookups
            if post is not None and probe is None
        ]
        probes = tuple(
            probe for _publication, _post, probe in lookups if probe is not None
        )
        point_comments: dict[int, int | None] = {}
        if self.comments_reader is not None and present:
            try:
                point_comments = await self.comments_reader.comments(
                    username,
                    (
                        int(post.message_id)
                        for _publication, post in present
                    ),
                )
            except Exception as error:
                logger.warning(
                    "telegram point-comment gateway degraded account=%s code=%s",
                    account.id,
                    sanitize_error_code(error),
                )
        final_collected = utc(self.clock.now(), "gateway.collected_at")
        if final_collected < observed:
            raise ValueError("gateway clock moved backwards")
        refreshed = []
        for publication, post in present:
            converted = telegram_public_batch(
                account=account,
                channel=PublicChannel(
                    channel.title,
                    channel.subscribers,
                    channel.subscribers_display,
                    [post],
                ),
                observed_at=observed,
                collected_at=final_collected,
                username=username,
                comments=point_comments,
                sampling_interval_seconds=_interval(self.settings, observed),
                complete_history_max_first_age_seconds=(
                    self.settings.complete_history_max_first_age_minutes * 60
                ),
                source_name=(
                    "telegram_web"
                    if self.comments_reader is not None else "telegram_public_web"
                ),
            ).publications[-1]
            refreshed.append(replace(
                converted,
                external_id=publication.external_id,
                source_external_id=publication.source_external_id,
                identities=tuple(
                    IdentityCandidate(
                        telegram_message_external_id(message_id),
                        IdentityRole.ALBUM_MEMBER,
                        public_url=f"https://t.me/{username}/{message_id}",
                    )
                    for message_id in _telegram_ids(publication)
                ),
            ))
        return replace(
            initial,
            publications=tuple((*initial.publications, *refreshed)),
            deletion_probes=probes,
            refresh_cursor=plan.next_cursor,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
        if self.comments_reader is not None:
            await self.comments_reader.close()


class VkGatewayCollector:
    platform = Platform.VK

    def __init__(
        self,
        settings: Settings,
        clock: UtcClock,
        history: MetricHistoryReader,
        client: VkClient | None = None,
    ) -> None:
        if client is None and not settings.vk_access_token:
            raise ValueError("VK_ACCESS_TOKEN is required")
        self.settings = settings
        self.clock = clock
        self.history = history
        self.tracking = _tracking_reader(history)
        self.client = client or VkClient(
            settings.vk_access_token or "",
            settings.vk_api_version,
            requests_per_second=settings.vk_requests_per_second,
        )

    async def collect(
        self, account: AccountRef, context: CollectionContext,
    ) -> RawCollectionBatch:
        community = await self.client.community(_reference(account))
        posts = await self.client.wall(
            community.id, min(self.settings.discovery_limit, 100),
        )
        external_ids = [
            identity.external_key
            for post in posts
            if (identity := post.identity_for_community(community.id)) is not None
        ]
        high_watermarks = self.history.metric_high_watermarks(account, external_ids)
        observed, collected = _times(self.clock)
        initial = vk_batch(
            account=account,
            community=community,
            posts=posts,
            observed_at=observed,
            collected_at=collected,
            high_watermarks=high_watermarks,
            sampling_interval_seconds=_interval(self.settings, observed),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
            source_version=self.settings.vk_api_version,
        )
        plan = plan_refresh(
            tracking=self.tracking,
            account=account,
            context=context,
            settings=self.settings,
            observed_at=observed,
            discovered_external_ids={
                publication.external_id for publication in initial.publications
            },
        )
        refreshed: list[Any] = []
        probes: list[RawDeletionProbe] = []
        for chunk in by_chunks(plan.publications, 100):
            request_ids = [
                publication.source_external_id or publication.external_id
                for publication in chunk
            ]
            try:
                values = await self.client.posts(request_ids)
            except Exception as error:
                probes.extend(
                    transient_probe(
                        publication,
                        observed,
                        self.settings,
                        "vk",
                        error,
                    )
                    for publication in chunk
                )
                continue
            refreshed.extend(values)
            returned_keys: set[str] = set()
            for post in values:
                returned_keys.add(post.external_key)
                identity = post.identity_for_community(community.id)
                if identity is not None:
                    returned_keys.add(identity.external_key)
                    if identity.source_external_key:
                        returned_keys.add(identity.source_external_key)
            for publication, request_id in zip(chunk, request_ids):
                if (
                    request_id not in returned_keys
                    and publication.external_id not in returned_keys
                ):
                    probes.append(missing_probe(
                        publication,
                        observed,
                        self.settings,
                        "vk_wall_get_by_id_not_found_or_deleted",
                    ))
        final_posts = _deduplicate(
            [*posts, *refreshed],
            lambda post: (
                identity.external_key
                if (identity := post.identity_for_community(community.id)) is not None
                else post.external_key
            ),
        )
        final_external_ids = [
            identity.external_key
            for post in final_posts
            if (identity := post.identity_for_community(community.id)) is not None
        ]
        final_watermarks = self.history.metric_high_watermarks(
            account, final_external_ids,
        )
        final_collected = utc(self.clock.now(), "gateway.collected_at")
        if final_collected < observed:
            raise ValueError("gateway clock moved backwards")
        final = vk_batch(
            account=account,
            community=community,
            posts=final_posts,
            observed_at=observed,
            collected_at=final_collected,
            high_watermarks=final_watermarks,
            sampling_interval_seconds=_interval(self.settings, observed),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
            source_version=self.settings.vk_api_version,
        )
        return replace(
            final,
            deletion_probes=tuple(probes),
            refresh_cursor=plan.next_cursor,
        )

    async def close(self) -> None:
        await self.client.close()


class MaxGatewayCollector:
    platform = Platform.MAX

    def __init__(
        self,
        settings: Settings,
        clock: UtcClock,
        client: Any | None = None,
        *,
        tracking: PublicationTrackingReader | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.tracking = tracking
        if client is None and not settings.max_user_session_ready:
            raise ValueError("MAX user session is not authorized")
        self.client = client or MaxUserClient(
            settings.require_max_user(),
            settings.max_session_path,
            settings.max_user_first_name,
            settings.max_user_last_name,
        )

    async def collect(
        self, account: AccountRef, context: CollectionContext,
    ) -> RawCollectionBatch:
        reference = _reference(account)
        native = account.native_external_id
        channel = await self.client.resolve_channel(
            reference,
            int(native) if native and native.lstrip("-").isdigit() else None,
        )
        posts = await self.client.posts(
            channel.id, min(self.settings.discovery_limit, 100),
        )
        observed, collected = _times(self.clock)
        initial = max_batch(
            account=account,
            channel=channel,
            posts=posts,
            observed_at=observed,
            collected_at=collected,
            public_reference=reference,
            sampling_interval_seconds=_interval(self.settings, observed),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
        )
        plan = plan_refresh(
            tracking=self.tracking,
            account=account,
            context=context,
            settings=self.settings,
            observed_at=observed,
            discovered_external_ids={
                publication.external_id for publication in initial.publications
            },
        )
        refreshed: list[Any] = []
        probes: list[RawDeletionProbe] = []
        for chunk in by_chunks(plan.publications, 100):
            request_ids = [publication.external_id for publication in chunk]
            try:
                values = await self.client.posts_by_ids(channel.id, request_ids)
            except Exception as error:
                probes.extend(
                    transient_probe(
                        publication,
                        observed,
                        self.settings,
                        "max",
                        error,
                    )
                    for publication in chunk
                )
                continue
            refreshed.extend(values)
            returned_ids = {str(post.id) for post in values}
            probes.extend(
                missing_probe(
                    publication,
                    observed,
                    self.settings,
                    "max_get_messages_not_found_or_deleted",
                )
                for publication in chunk
                if publication.external_id not in returned_ids
            )
        final_collected = utc(self.clock.now(), "gateway.collected_at")
        if final_collected < observed:
            raise ValueError("gateway clock moved backwards")
        final = max_batch(
            account=account,
            channel=channel,
            posts=_deduplicate([*posts, *refreshed], lambda post: str(post.id)),
            observed_at=observed,
            collected_at=final_collected,
            public_reference=reference,
            sampling_interval_seconds=_interval(self.settings, observed),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
        )
        return replace(
            final,
            deletion_probes=tuple(probes),
            refresh_cursor=plan.next_cursor,
        )

    async def close(self) -> None:
        await self.client.close()


class RutubeGatewayCollector:
    platform = Platform.RUTUBE

    def __init__(
        self,
        settings: Settings,
        clock: UtcClock,
        client: RutubeClient | None = None,
        *,
        tracking: PublicationTrackingReader | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.tracking = tracking
        self.client = client or RutubeClient(settings.rutube_api_base)
        self._request_semaphore = asyncio.Semaphore(
            max(1, settings.rutube_request_concurrency),
        )

    async def collect(
        self, account: AccountRef, context: CollectionContext,
    ) -> RawCollectionBatch:
        reference = account.native_external_id or account.canonical_external_id
        native_id = (
            int(reference)
            if reference.isdigit()
            else await self.client.resolve_channel(reference, account.current_url)
        )
        (channel, videos), subscriber_count = await asyncio.gather(
            self.client.videos(native_id, min(self.settings.discovery_limit, 100)),
            self.client.subscriber_count(native_id, account.current_url),
        )

        async def metrics(video_id: str) -> RutubeVideoMetrics:
            async with self._request_semaphore:
                return await self.client.video_metrics(video_id)

        values = await asyncio.gather(
            *(metrics(video.id) for video in videos),
            return_exceptions=True,
        )
        metrics_by_id = {
            video.id: value if isinstance(value, RutubeVideoMetrics) else None
            for video, value in zip(videos, values)
        }
        observed, collected = _times(self.clock)
        initial = rutube_batch(
            account=account,
            channel=channel,
            videos=videos,
            metrics=metrics_by_id,
            observed_at=observed,
            collected_at=collected,
            subscriber_count=subscriber_count,
            sampling_interval_seconds=_interval(
                self.settings, observed, platform="rutube",
            ),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
        )
        plan = plan_refresh(
            tracking=self.tracking,
            account=account,
            context=context,
            settings=self.settings,
            observed_at=observed,
            discovered_external_ids={video.id for video in videos},
        )

        async def point_lookup(
            publication: TrackedPublication,
        ) -> tuple[Any | None, RawDeletionProbe | None]:
            try:
                async with self._request_semaphore:
                    video = await self.client.video(publication.external_id)
                return video, None
            except Exception as error:
                status = getattr(getattr(error, "response", None), "status_code", None)
                if status in {404, 410}:
                    return None, missing_probe(
                        publication,
                        observed,
                        self.settings,
                        f"rutube_video_http_{status}",
                    )
                return None, transient_probe(
                    publication,
                    observed,
                    self.settings,
                    "rutube",
                    error,
                )

        lookups = await asyncio.gather(*(
            point_lookup(publication) for publication in plan.publications
        ))
        refreshed = [video for video, probe in lookups if video is not None and probe is None]
        probes = tuple(probe for _video, probe in lookups if probe is not None)
        refreshed_metrics = await asyncio.gather(
            *(metrics(video.id) for video in refreshed),
            return_exceptions=True,
        )
        metrics_by_id.update({
            video.id: value if isinstance(value, RutubeVideoMetrics) else None
            for video, value in zip(refreshed, refreshed_metrics)
        })
        final_collected = utc(self.clock.now(), "gateway.collected_at")
        if final_collected < observed:
            raise ValueError("gateway clock moved backwards")
        final = rutube_batch(
            account=account,
            channel=channel,
            videos=_deduplicate([*videos, *refreshed], lambda video: video.id),
            metrics=metrics_by_id,
            observed_at=observed,
            collected_at=final_collected,
            subscriber_count=subscriber_count,
            sampling_interval_seconds=_interval(
                self.settings, observed, platform="rutube",
            ),
            complete_history_max_first_age_seconds=(
                self.settings.complete_history_max_first_age_minutes * 60
            ),
        )
        return replace(
            final,
            deletion_probes=probes,
            refresh_cursor=plan.next_cursor,
        )

    async def close(self) -> None:
        await self.client.close()


def build_runtime_adapter(
    platform: Platform,
    settings: Settings,
    clock: UtcClock,
    history: MetricHistoryReader,
) -> Any:
    if platform == Platform.TELEGRAM:
        if settings.data_source == "mtproto":
            return TelegramMtprotoCollector(
                settings, clock, tracking=_tracking_reader(history),
            )
        comments_reader = (
            TelegramWebSession(
                settings.telegram_web_profile_path,
                concurrency=settings.telegram_web_concurrency,
            )
            if settings.data_source == "telegram_web" else None
        )
        return TelegramPublicWebCollector(
            settings,
            clock,
            comments_reader=comments_reader,
            tracking=_tracking_reader(history),
        )
    if platform == Platform.VK:
        return VkGatewayCollector(settings, clock, history)
    if platform == Platform.MAX:
        return MaxGatewayCollector(
            settings, clock, tracking=_tracking_reader(history),
        )
    if platform == Platform.RUTUBE:
        return RutubeGatewayCollector(
            settings, clock, tracking=_tracking_reader(history),
        )
    raise ValueError(f"unsupported platform: {platform.value}")
