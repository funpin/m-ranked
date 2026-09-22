from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
import logging
from typing import Any, Iterable, Mapping

import httpx

from collector_runtime.collector import (
    group_logical_posts,
    logical_comments,
    logical_views,
    normalize_channel_ref,
)
from collector_runtime.config import Settings
from collector_runtime.public_web import (
    PublicChannel,
    older_page_before,
    parse_exact_subscriber_count,
    parse_public_channel,
    parse_public_page,
    public_post_is_deleted,
)
from collector_runtime.telegram_client import TelegramReader
from collector_runtime.telegram_identity import (
    parse_telegram_external_id,
    telegram_message_external_id,
    telegram_publication_external_id,
)
from collector_runtime.telegram_web import TelegramWebSession

from ..model import (
    AccountRef,
    CollectionContext,
    DeletionProbeOutcome,
    HistoryCompleteness,
    IdentityCandidate,
    IdentityRole,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawDeletionProbe,
    RawPublication,
    TrackedPublication,
    utc,
)
from ..normalize import sanitize_error_code
from ..ports import (
    MetricHistoryReader,
    PlatformCollector,
    PublicationTrackingReader,
    UtcClock,
)
from ..tracking import (
    by_chunks,
    deletion_confirmation_threshold,
    missing_probe,
    plan_refresh,
    transient_probe,
    unsupported_probe,
)
from ._shared import (
    Interval,
    deduplicate as _deduplicate,
    history_completeness as _history,
    interval_seconds as _interval_seconds,
    observation_times as _times,
    sampling_interval as _interval,
    tracking_reader as _tracking_reader,
)


logger = logging.getLogger(__name__)


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
        self._closed = False

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
        if self._closed:
            return
        self._closed = True
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
        self._closed = False
        # Каналы, чью историю уже дочитали в этом процессе.
        self._history_walked: set[str] = set()

    async def _with_history(self, channel: Any, username: str, html: str) -> Any:
        """Дочитать страницы назад, если обход просят вести вглубь.

        Публичный предпросмотр отдаёт горсть сообщений за раз, остальное — за
        ссылкой «ещё». Пока её не разбирали, история канала обрывалась на том,
        что попало на первую страницу в день подключения: у каналов, пишущих
        альбомами, это семь постов за месяц при живой ленте за годы.

        По умолчанию страница одна — прежнее поведение и прежняя цена обхода.
        Глубину поднимают разово, чтобы дочитать пропущенное.
        """
        budget = max(1, int(getattr(self.settings, "telegram_history_pages", 1)))
        if budget == 1 or username in self._history_walked:
            return channel
        # Обход идёт один раз на канал за жизнь процесса. Без этого он
        # повторялся каждые пять минут и съедал весь бюджет цикла: замер на
        # проде — 5175 запросов истории против трёх замеров постов за двадцать
        # минут, цикл растянулся с пяти минут до двенадцати, и публикации
        # старше двух недель переставали измеряться вовсе.
        self._history_walked.add(username)
        posts = list(channel.posts)
        seen = {post.message_id for post in posts}
        before = older_page_before(html)
        for _ in range(budget - 1):
            if before is None:
                break
            response = await self.client.get(f"https://t.me/s/{username}?before={before}")
            response.raise_for_status()
            page = parse_public_channel(response.text, username)
            fresh = [post for post in page.posts if post.message_id not in seen]
            # Страница без новых номеров означает, что дальше сервер ничего не
            # отдаёт: продолжать незачем.
            if not fresh:
                break
            posts.extend(fresh)
            seen.update(post.message_id for post in fresh)
            before = older_page_before(response.text)
        return replace(channel, posts=sorted(posts, key=lambda post: post.message_id))

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
        channel = await self._with_history(channel, username, feed_response.text)
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
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self.client.aclose()
        if self.comments_reader is not None:
            await self.comments_reader.close()




def build(
    settings: Settings,
    clock: UtcClock,
    history: MetricHistoryReader,
) -> PlatformCollector:
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


__all__ = [
    "TelegramMtprotoCollector",
    "TelegramPublicWebCollector",
    "_telegram_ids",
    "build",
    "telegram_batch",
    "telegram_public_batch",
]
