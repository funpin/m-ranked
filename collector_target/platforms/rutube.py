from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable, Mapping

from collector_runtime.config import Settings
from collector_runtime.rutube import (
    RutubeChannel,
    RutubeClient,
    RutubeVideo,
    RutubeVideoMetrics,
)

from ..model import (
    AccountRef,
    CollectionContext,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawDeletionProbe,
    RawPublication,
    TrackedPublication,
    utc,
)
from ..ports import (
    MetricHistoryReader,
    PlatformCollector,
    PublicationTrackingReader,
    UtcClock,
)
from ..tracking import missing_probe, plan_refresh, transient_probe
from ._shared import (
    Interval,
    deduplicate as _deduplicate,
    history_completeness as _history,
    interval_seconds as _interval_seconds,
    observation_times as _times,
    sampling_interval as _interval,
    tracking_reader as _tracking_reader,
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
        self._closed = False

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
        if self._closed:
            return
        self._closed = True
        await self.client.close()




def build(
    settings: Settings,
    clock: UtcClock,
    history: MetricHistoryReader,
) -> PlatformCollector:
    return RutubeGatewayCollector(
        settings, clock, tracking=_tracking_reader(history),
    )


__all__ = ["RutubeGatewayCollector", "build", "rutube_batch"]
