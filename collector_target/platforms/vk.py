from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable, Mapping

from collector_runtime.config import Settings
from collector_runtime.vk import VkClient, VkCommunity, VkPost
from collector_runtime.vk_collector import validated_vk_metrics

from ..model import (
    AccountRef,
    CollectionContext,
    IdentityCandidate,
    IdentityRole,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawDeletionProbe,
    RawPublication,
    utc,
)
from ..ports import MetricHistoryReader, PlatformCollector, UtcClock
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



def vk_batch(
    *,
    account: AccountRef,
    community: VkCommunity,
    posts: Iterable[VkPost],
    observed_at: datetime,
    collected_at: datetime,
    ever_positive: Mapping[str, Mapping[str, bool]] | None = None,
    sampling_interval_seconds: Interval = 300,
    complete_history_max_first_age_seconds: int = 360,
    source_version: str = "5.199",
) -> RawCollectionBatch:
    observed = utc(observed_at, "observed_at")
    collected = utc(collected_at, "collected_at")
    seen_positive = ever_positive or {}
    publications: list[RawPublication] = []
    for post in posts:
        identity = post.identity_for_community(community.id)
        if identity is None:
            continue
        metrics, ignored = validated_vk_metrics(
            post, dict(seen_positive.get(identity.external_key, {})),
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
        self._closed = False

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
        ever_positive = self.history.metric_ever_positive(account, external_ids)
        observed, collected = _times(self.clock)
        initial = vk_batch(
            account=account,
            community=community,
            posts=posts,
            observed_at=observed,
            collected_at=collected,
            ever_positive=ever_positive,
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
        final_ever_positive = self.history.metric_ever_positive(
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
            ever_positive=final_ever_positive,
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
        if self._closed:
            return
        self._closed = True
        await self.client.close()




def build(
    settings: Settings,
    clock: UtcClock,
    history: MetricHistoryReader,
) -> PlatformCollector:
    return VkGatewayCollector(settings, clock, history)


__all__ = ["VkGatewayCollector", "build", "vk_batch"]
