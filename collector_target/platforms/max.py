from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable

from collector_runtime.config import Settings
from collector_runtime.max_api import MaxChannel, MaxPost, max_post_url
from collector_runtime.max_user_api import MaxUserClient

from ..model import (
    AccountRef,
    CollectionContext,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawDeletionProbe,
    RawPublication,
    utc,
)
from ..ports import (
    MetricHistoryReader,
    PlatformCollector,
    PublicationTrackingReader,
    UtcClock,
)
from ..tracking import by_chunks, missing_probe, plan_refresh, transient_probe
from ._shared import (
    Interval,
    deduplicate as _deduplicate,
    history_completeness as _history,
    interval_seconds as _interval_seconds,
    observation_times as _times,
    reference as _reference,
    sampling_interval as _interval,
    tracking_reader as _tracking_reader,
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
            request_timeout_seconds=settings.max_request_timeout_seconds,
        )
        self._closed = False

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
        if self._closed:
            return
        self._closed = True
        await self.client.close()




def build(
    settings: Settings,
    clock: UtcClock,
    history: MetricHistoryReader,
) -> PlatformCollector:
    return MaxGatewayCollector(
        settings, clock, tracking=_tracking_reader(history),
    )


__all__ = ["MaxGatewayCollector", "build", "max_batch"]
