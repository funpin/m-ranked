from __future__ import annotations

import asyncio
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import httpx

from app.config import Settings
from app.max_api import MaxChannel, MaxPost
from app.public_web import PublicChannel
from app.rutube import RutubeChannel, RutubeVideo, RutubeVideoMetrics
from app.vk import VkCommunity, VkPost
from collector_target.__main__ import _parser, _run, _scheduled_slot
from collector_target.adapters import (
    max_batch,
    rutube_batch,
    telegram_batch,
    telegram_public_batch,
    vk_batch,
)
from collector_target.auth import (
    PlatformAuthFileError,
    apply_platform_auth_file,
    parse_platform_auth_file,
)
from collector_target.coordinator import PlatformSupervisor, PollCycleCoordinator
from collector_target.lease import InMemoryLeaseProvider, advisory_lock_key, lease_name
from collector_target.model import (
    AccountRef,
    CollectionContext,
    HistoryCompleteness,
    DeletionProbeOutcome,
    ObservationQuality,
    Platform,
    RawAccountObservation,
    RawCollectionBatch,
    RawDeletionProbe,
    RawPublication,
    RunStatus,
    RunSummary,
    TrackedPublication,
)
from collector_target.normalize import (
    CanonicalNormalizer,
    canonical_json,
    sanitize_error_code,
    sanitize_evidence,
)
from collector_target.ports import CollectorRepository, PlatformCollector
from collector_target.repository import PostgresCollectorRepository
from collector_target.runtime_adapters import (
    MaxGatewayCollector,
    RutubeGatewayCollector,
    TelegramMtprotoCollector,
    TelegramPublicWebCollector,
    VkGatewayCollector,
    _telegram_ids,
)
from collector_target.tracking import plan_refresh, validate_tracking_policy


NOW = datetime(2026, 9, 3, 9, 0, tzinfo=timezone.utc)
INSTITUTION_ID = UUID("10000000-0000-4000-8000-000000000001")


def test_tracked_telegram_ids_accept_only_canonical_message_identities() -> None:
    publication = TrackedPublication(
        UUID("30000000-0000-4000-8000-000000000001"),
        "g:77",
        None,
        None,
        NOW,
        ("m:10", "m:0011", "m:0", "g:77", "m:12"),
        None,
        None,
    )

    assert _telegram_ids(publication) == (10, 12)


def account(platform: Platform, suffix: int = 1) -> AccountRef:
    return AccountRef(
        UUID(f"20000000-0000-4000-8000-{suffix:012d}"),
        INSTITUTION_ID,
        platform,
        f"account-{suffix}",
        "official_api" if platform != Platform.TELEGRAM else "mtproto",
        current_username=f"channel_{suffix}",
    )


def context(platform: Platform = Platform.TELEGRAM) -> CollectionContext:
    return CollectionContext.create(platform, "default", "test-v1", NOW, NOW)


def target_settings(tmp_path: Path, **overrides: Any) -> Settings:
    settings = Settings(
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_session_path=tmp_path / "telegram.session",
        database_path=tmp_path / "legacy.db",
        initial_channels=(),
        poll_interval_minutes=5,
        track_post_for_hours=960,
        complete_history_max_first_age_minutes=6,
        jump_min_abs=15,
        jump_min_ratio=2.0,
        web_host="127.0.0.1",
        web_port=8080,
        display_timezone="UTC",
        log_path=tmp_path / "collector.log",
        discovery_limit=100,
        discovery_overlap=20,
    )
    return replace(settings, **overrides)


def auth_file(tmp_path: Path, payload: str, *, mode: int = 0o600) -> Path:
    path = tmp_path / "platform-auth"
    path.write_text(payload, encoding="utf-8")
    path.chmod(mode)
    return path


def raw_batch(
    target: AccountRef,
    run_context: CollectionContext,
    *,
    external_id: str = "post-1",
    source: dict[str, Any] | None = None,
) -> RawCollectionBatch:
    return RawCollectionBatch(
        target,
        RawAccountObservation(
            NOW,
            NOW,
            0,
            "0",
            source=source or {"gateway": "fake"},
        ),
        (
            RawPublication(
                external_id,
                NOW - timedelta(minutes=1),
                NOW,
                NOW,
                NOW,
                "text",
                {"views": 0, "reactions": None, "comments": 0, "shares": None},
                source or {"gateway": "fake"},
                public_url="https://example.test/post-1",
                history_completeness=HistoryCompleteness.COMPLETE,
            ),
        ),
        "fake_gateway",
        "1",
        "cursor-1",
    )


def test_context_ids_are_deterministic_and_utc_is_mandatory() -> None:
    first = context()
    second = context()
    assert first.run_id == second.run_id
    assert first.correlation_id == second.correlation_id
    assert first.partition_scope_id == second.partition_scope_id

    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        CollectionContext.create(Platform.VK, "default", "v1", naive, NOW)
    with pytest.raises(ValueError, match="must not precede"):
        CollectionContext.create(
            Platform.VK, "default", "v1", NOW, NOW - timedelta(seconds=1),
        )


def test_normalization_preserves_zero_null_and_marks_invalid_and_resets() -> None:
    target = account(Platform.VK)
    run_context = context(Platform.VK)
    raw = raw_batch(
        target,
        run_context,
        source={
            "access_token": "top-secret",
            "nested": {"password": "another-secret"},
            "header": "Bearer abc.def",
            "dsn": "postgresql://collector:hunter2@db/mranked",
        },
    )
    publication = replace(
        raw.publications[0],
        metrics={"views": 0, "reactions": -2, "comments": 0, "shares": None},
        suspected_reset_metrics=frozenset({"comments"}),
    )
    canonical = CanonicalNormalizer().normalize(
        replace(raw, publications=(publication,)), run_context,
    )
    snapshot = canonical.publications[0].snapshot
    assert snapshot.views_count == 0
    assert snapshot.reactions_count is None
    assert snapshot.comments_count is None
    assert snapshot.shares_count is None
    assert snapshot.metric_quality["reactions"] == ObservationQuality.INVALID
    assert snapshot.metric_quality["comments"] == ObservationQuality.SUSPECTED_RESET
    assert snapshot.quality == ObservationQuality.INVALID
    assert len(snapshot.source_fingerprint) == 64
    serialized = canonical_json(snapshot.sanitized_source)
    assert "top-secret" not in serialized
    assert "another-secret" not in serialized
    assert "hunter2" not in serialized
    assert "abc.def" not in serialized
    assert serialized.count("[REDACTED]") >= 4
    assert (
        CanonicalNormalizer().normalize(
            replace(raw, publications=(publication,)), run_context,
        ).publications[0].snapshot.source_fingerprint
        == snapshot.source_fingerprint
    )
    changed_quality = CanonicalNormalizer().normalize(
        replace(
            raw,
            publications=(replace(
                publication,
                quality=ObservationQuality.ROUNDED,
                suspected_reset_metrics=frozenset(),
                metrics={"views": 0, "reactions": 2, "comments": 0, "shares": None},
            ),),
        ),
        run_context,
    )
    assert (
        changed_quality.publications[0].snapshot.source_fingerprint
        != snapshot.source_fingerprint
    )


def test_normalizer_rejects_impossible_collection_time() -> None:
    target = account(Platform.MAX)
    run_context = context(Platform.MAX)
    invalid = replace(
        raw_batch(target, run_context),
        account_observation=RawAccountObservation(
            NOW, NOW - timedelta(seconds=1), 1,
        ),
    )
    with pytest.raises(ValueError, match="collected_at"):
        CanonicalNormalizer().normalize(invalid, run_context)


def test_evidence_and_error_codes_never_include_exception_messages_or_secrets() -> None:
    class GatewayError(RuntimeError):
        code = "access_token=secret-value"

    error = GatewayError("password=hunter2 Bearer abc.def")
    assert sanitize_error_code(error) == "GatewayError"
    result = sanitize_evidence({
        "authorization": "Bearer abc.def",
        "note": "password=hunter2",
    })
    serialized = canonical_json(result)
    assert "abc.def" not in serialized
    assert "hunter2" not in serialized


def test_platform_auth_file_populates_mtproto_without_mutating_settings(
    tmp_path: Path,
) -> None:
    settings = target_settings(tmp_path)
    path = auth_file(
        tmp_path,
        "# platform-scoped bundle\nTELEGRAM_API_ID=123456\n"
        "TELEGRAM_API_HASH=private-hash\n",
    )

    loaded = apply_platform_auth_file(settings, Platform.TELEGRAM, path)

    assert loaded.telegram_api_id == 123456
    assert loaded.telegram_api_hash == "private-hash"
    assert settings.telegram_api_id is None
    assert settings.telegram_api_hash is None


@pytest.mark.parametrize(
    ("platform", "payload", "attribute", "expected"),
    (
        (Platform.VK, "VK_ACCESS_TOKEN=vk-private\n", "vk_access_token", "vk-private"),
        (Platform.MAX, "MAX_USER_PHONE=+79990000000\n", "max_user_phone", "+79990000000"),
    ),
)
def test_platform_auth_file_uses_strict_platform_allowlist(
    tmp_path: Path,
    platform: Platform,
    payload: str,
    attribute: str,
    expected: str,
) -> None:
    loaded = apply_platform_auth_file(
        target_settings(tmp_path), platform, auth_file(tmp_path, payload),
    )
    assert getattr(loaded, attribute) == expected


def test_public_platform_modes_require_an_empty_credential_bundle(
    tmp_path: Path,
) -> None:
    path = auth_file(
        tmp_path, "\n  # no platform secret is required\n", mode=0o400,
    )
    public_settings = target_settings(tmp_path, data_source="public_web")

    assert (
        apply_platform_auth_file(public_settings, Platform.TELEGRAM, path)
        is public_settings
    )
    assert (
        apply_platform_auth_file(target_settings(tmp_path), Platform.RUTUBE, path)
        .rutube_public_api_enabled
        is True
    )


@pytest.mark.parametrize(
    ("platform", "payload"),
    (
        (Platform.VK, "TELEGRAM_API_HASH=do-not-leak\n"),
        (Platform.VK, "VK_ACCESS_TOKEN=first\nVK_ACCESS_TOKEN=do-not-leak\n"),
        (Platform.VK, " VK_ACCESS_TOKEN=do-not-leak\n"),
        (Platform.VK, "VK_ACCESS_TOKEN=do-not-leak \n"),
        (Platform.VK, "VK_ACCESS_TOKEN=\n"),
        (Platform.VK, "VK_ACCESS_TOKEN\n"),
        (Platform.VK, "\n"),
        (Platform.TELEGRAM, "TELEGRAM_API_ID=123\n"),
        (Platform.TELEGRAM, "TELEGRAM_API_ID=zero\nTELEGRAM_API_HASH=do-not-leak\n"),
        (Platform.RUTUBE, "RUTUBE_TOKEN=do-not-leak\n"),
    ),
)
def test_platform_auth_file_rejects_malformed_or_incomplete_bundles_safely(
    tmp_path: Path,
    platform: Platform,
    payload: str,
) -> None:
    with pytest.raises(PlatformAuthFileError) as raised:
        apply_platform_auth_file(
            target_settings(tmp_path), platform, auth_file(tmp_path, payload),
        )
    assert "do-not-leak" not in str(raised.value)


def test_platform_auth_file_rejects_direct_value_conflicts_without_leaking(
    tmp_path: Path,
) -> None:
    settings = target_settings(tmp_path, vk_access_token="direct-do-not-leak")
    path = auth_file(tmp_path, "VK_ACCESS_TOKEN=file-do-not-leak\n")

    with pytest.raises(
        PlatformAuthFileError,
        match="direct and file credentials cannot be combined",
    ) as raised:
        apply_platform_auth_file(settings, Platform.VK, path)
    assert "do-not-leak" not in str(raised.value)


def test_platform_auth_file_rejects_unsafe_files(
    tmp_path: Path,
) -> None:
    permissive = auth_file(tmp_path, "VK_ACCESS_TOKEN=do-not-leak\n", mode=0o644)
    with pytest.raises(PlatformAuthFileError, match="permissions"):
        parse_platform_auth_file(Platform.VK, permissive)

    permissive.chmod(0o600)
    link = tmp_path / "platform-auth-link"
    link.symlink_to(permissive)
    with pytest.raises(PlatformAuthFileError, match="regular file"):
        parse_platform_auth_file(Platform.VK, link)

    missing = tmp_path / "missing-do-not-leak"
    with pytest.raises(PlatformAuthFileError) as raised:
        parse_platform_auth_file(Platform.VK, missing)
    assert "do-not-leak" not in str(raised.value)


def test_cli_auth_failure_logs_only_a_safe_error_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = auth_file(tmp_path, "UNEXPECTED_KEY=do-not-leak\n")
    monkeypatch.setenv("COLLECTOR_PLATFORM_AUTH_FILE", str(path))
    for key in ("VK_ACCESS_TOKEN", "COLLECTOR_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    args = _parser().parse_args([
        "--platform", "vk", "--env-file", str(tmp_path / "missing.env"), "--once",
    ])

    with caplog.at_level(logging.ERROR, logger="collector_target"):
        result = asyncio.run(_run(args))

    assert result == 1
    assert "code=PlatformAuthFileError" in caplog.text
    assert "do-not-leak" not in caplog.text


def _telegram_message(
    message_id: int,
    *,
    grouped_id: int,
    views: int,
    comments: int,
    reactions: int,
) -> Any:
    reaction = SimpleNamespace(emoticon="👍")
    item = SimpleNamespace(reaction=reaction, count=reactions)
    return SimpleNamespace(
        id=message_id,
        date=NOW - timedelta(minutes=2),
        grouped_id=grouped_id,
        media=SimpleNamespace(__class__=SimpleNamespace(__name__="MessageMediaPhoto")),
        reactions=SimpleNamespace(results=[item]),
        replies=SimpleNamespace(replies=comments),
        views=views,
        action=None,
        fwd_from=None,
        peer_id=SimpleNamespace(channel_id=10),
    )


def test_telegram_album_converter_keeps_logical_counter_semantics() -> None:
    target = account(Platform.TELEGRAM)
    batch = telegram_batch(
        account=target,
        messages=(
            _telegram_message(10, grouped_id=77, views=100, comments=2, reactions=3),
            _telegram_message(11, grouped_id=77, views=120, comments=4, reactions=5),
        ),
        observed_at=NOW,
        collected_at=NOW,
        subscriber_count=0,
        channel_id=10,
        channel_username="channel_1",
    )
    assert batch.cursor == "11"
    assert batch.account_observation is not None
    assert batch.account_observation.subscriber_count == 0
    publication = batch.publications[0]
    assert publication.external_id == "g:77"
    assert publication.metrics == {
        "views": 120,
        "reactions": 5,
        "comments": 4,
        "shares": None,
    }
    assert {identity.external_id for identity in publication.identities} == {
        "m:10", "m:11",
    }
    assert publication.quality_flags["ambiguous_reactions"] is True
    assert all(not item.synthetic for item in batch.publications)
    canonical = CanonicalNormalizer().normalize(
        batch, context(Platform.TELEGRAM),
    )
    assert all(
        not item.snapshot.synthetic
        and not item.synthetic_baseline_allowed
        for item in canonical.publications
    )


def test_telegram_public_timely_discovery_emits_synthetic_baseline_and_actual() -> None:
    target = account(Platform.TELEGRAM)
    published = NOW - timedelta(minutes=4)
    post = SimpleNamespace(
        message_id=42,
        published_at=published,
        post_type="text",
        views_count=370,
        reactions=SimpleNamespace(total=173, raw="173", reactions={"👍": 173}),
        is_repost=False,
    )

    batch = telegram_public_batch(
        account=target,
        channel=PublicChannel("Example", 100, "100", [post]),
        observed_at=NOW,
        collected_at=NOW,
        username="channel_1",
        comments={42: 12},
        complete_history_max_first_age_seconds=360,
    )

    assert len(batch.publications) == 2
    baseline, actual = batch.publications
    assert baseline.external_id == actual.external_id == "m:42"
    assert baseline.synthetic is True
    assert baseline.observed_at == published
    assert baseline.metrics == {
        "views": 0,
        "reactions": 0,
        "comments": 0,
        "shares": None,
    }
    assert baseline.reaction_breakdown == {}
    assert actual.synthetic is False
    assert actual.metrics["views"] == 370
    assert actual.metrics["reactions"] == 173
    assert actual.metrics["comments"] == 12
    assert baseline.history_completeness == HistoryCompleteness.COMPLETE
    assert actual.history_completeness == HistoryCompleteness.COMPLETE

    canonical = CanonicalNormalizer().normalize(batch, context(Platform.TELEGRAM))
    canonical_baseline, canonical_actual = canonical.publications
    assert canonical_baseline.snapshot.synthetic is True
    assert canonical_baseline.snapshot.age_seconds == 0
    assert canonical_baseline.snapshot.sampling_bucket == -1
    assert canonical_baseline.synthetic_baseline_allowed is True
    assert canonical_actual.snapshot.synthetic is False
    assert canonical_actual.synthetic_baseline_allowed is False


def test_telegram_public_late_discovery_stays_incomplete_without_baseline() -> None:
    post = SimpleNamespace(
        message_id=43,
        published_at=NOW - timedelta(minutes=7),
        post_type="text",
        views_count=10,
        reactions=SimpleNamespace(total=2, raw="2", reactions={"👍": 2}),
        is_repost=False,
    )

    batch = telegram_public_batch(
        account=account(Platform.TELEGRAM),
        channel=PublicChannel("Example", 100, "100", [post]),
        observed_at=NOW,
        collected_at=NOW,
        username="channel_1",
        complete_history_max_first_age_seconds=360,
    )

    assert len(batch.publications) == 1
    assert batch.publications[0].synthetic is False
    assert batch.publications[0].history_completeness == HistoryCompleteness.INCOMPLETE


def test_vk_joint_identity_and_positive_to_zero_reset_are_preserved() -> None:
    target = account(Platform.VK)
    community = VkCommunity(123, "uni", "University", 500)
    post = VkPost(
        owner_id=-999,
        post_id=5,
        published_at=NOW - timedelta(hours=1),
        post_type="text",
        views=100,
        likes=0,
        comments=2,
        reposts=1,
        raw={
            "coowners": {
                "coowner_post_id": {"owner_id": -123, "post_id": 77},
                "list": [
                    {"owner_id": -999, "post_id": 5},
                    {"owner_id": -123, "post_id": 77},
                ],
            },
        },
    )
    batch = vk_batch(
        account=target,
        community=community,
        posts=(post,),
        observed_at=NOW,
        collected_at=NOW,
        high_watermarks={"-123_77": {"reactions": 9}},
    )
    publication = batch.publications[0]
    assert publication.external_id == "-123_77"
    assert publication.source_external_id == "-999_5"
    assert publication.metrics["reactions"] is None
    assert publication.suspected_reset_metrics == frozenset({"reactions"})
    assert publication.quality_flags == {
        "joint_post": True,
        "additional_author_count": 1,
    }


def test_max_and_rutube_unsupported_values_remain_null() -> None:
    max_target = account(Platform.MAX)
    max_result = max_batch(
        account=max_target,
        channel=MaxChannel(9, "MAX", 0, "https://max.ru/channel"),
        posts=(MaxPost("10", NOW - timedelta(minutes=5), 0, 2, None, None, None, {}),),
        observed_at=NOW,
        collected_at=NOW,
        public_reference="channel",
    )
    max_publication = max_result.publications[0]
    assert max_publication.metrics["views"] == 0
    assert max_publication.metrics["comments"] is None
    assert max_publication.metrics["shares"] is None

    rutube_target = account(Platform.RUTUBE)
    video = RutubeVideo(
        "video-1", "Video", NOW - timedelta(minutes=5), 0,
        "https://rutube.ru/video/video-1/", {},
    )
    rutube_result = rutube_batch(
        account=rutube_target,
        channel=RutubeChannel(5, "RUTUBE", "https://rutube.ru/channel/5/"),
        videos=(video,),
        metrics={"video-1": RutubeVideoMetrics(None, 0, {})},
        observed_at=NOW,
        collected_at=NOW,
        subscriber_count=None,
    )
    rutube_publication = rutube_result.publications[0]
    assert rutube_publication.metrics == {
        "views": 0,
        "reactions": None,
        "comments": 0,
        "shares": None,
    }
    assert (
        rutube_publication.metric_quality["reactions"]
        == ObservationQuality.DEGRADED
    )


def test_rutube_gateway_keeps_other_videos_when_one_metric_request_fails() -> None:
    class Client:
        async def resolve_channel(self, reference: str, url: str | None) -> int:
            return 5

        async def videos(self, channel_id: int, limit: int):
            channel = RutubeChannel(5, "RUTUBE", "https://rutube.ru/channel/5/")
            videos = [
                RutubeVideo(
                    "ok", "OK", NOW - timedelta(minutes=5), 10,
                    "https://rutube.ru/video/ok/", {},
                ),
                RutubeVideo(
                    "failed", "Failed", NOW - timedelta(minutes=5), 20,
                    "https://rutube.ru/video/failed/", {},
                ),
            ]
            return channel, videos

        async def subscriber_count(self, channel_id: int, url: str | None) -> int:
            return 4

        async def video_metrics(self, video_id: str) -> RutubeVideoMetrics:
            if video_id == "failed":
                raise ConnectionError("gateway secret")
            return RutubeVideoMetrics(2, 1, {"likes": 2, "comments": 1})

        async def close(self) -> None:
            return None

    settings = SimpleNamespace(
        rutube_api_base="https://rutube.ru/api",
        rutube_request_concurrency=2,
        discovery_limit=100,
        rutube_first_three_days_poll_interval_minutes=60,
        complete_history_max_first_age_minutes=6,
    )
    adapter = RutubeGatewayCollector(  # type: ignore[arg-type]
        settings, _FixedClock(), Client(),  # type: ignore[arg-type]
    )
    result = asyncio.run(
        adapter.collect(account(Platform.RUTUBE), context(Platform.RUTUBE)),
    )
    assert len(result.publications) == 2
    by_id = {publication.external_id: publication for publication in result.publications}
    assert by_id["ok"].quality == ObservationQuality.EXACT
    assert by_id["failed"].quality == ObservationQuality.DEGRADED
    assert by_id["failed"].metrics["reactions"] is None


class _FixedClock:
    def now(self) -> datetime:
        return NOW


class _Tracking:
    def __init__(self, publications: tuple[TrackedPublication, ...]) -> None:
        self.publications = publications
        self.calls: list[tuple[datetime, int]] = []

    def tracked_publications(
        self,
        target: AccountRef,
        *,
        published_after: datetime,
        limit: int,
    ) -> tuple[TrackedPublication, ...]:
        self.calls.append((published_after, limit))
        return self.publications[:limit]


def _tracked(
    suffix: int,
    external_id: str,
    *,
    latest_observed_at: datetime | None = None,
    source_external_id: str | None = None,
    identities: tuple[str, ...] = (),
) -> TrackedPublication:
    return TrackedPublication(
        UUID(f"30000000-0000-4000-8000-{suffix:012d}"),
        external_id,
        source_external_id,
        f"https://example.test/{external_id}",
        NOW - timedelta(hours=2),
        identities or (external_id,),
        latest_observed_at,
        None,
    )


def test_refresh_plan_keeps_discovery_budget_and_stops_cursor_at_refresh_limit(
    tmp_path: Path,
) -> None:
    tracked = tuple(_tracked(index, f"post-{index}") for index in range(1, 5))
    reader = _Tracking(tracked)
    settings = target_settings(
        tmp_path,
        collector_refresh_limit=2,
        collector_refresh_scan_limit=4,
    )

    plan = plan_refresh(
        tracking=reader,
        account=account(Platform.MAX),
        context=context(Platform.MAX),
        settings=settings,
        observed_at=NOW,
        discovered_external_ids={"post-1"},
    )

    assert [item.external_id for item in plan.publications] == ["post-2", "post-3"]
    assert plan.next_cursor == str(tracked[2].id)
    assert reader.calls == [(NOW - timedelta(hours=960), 4)]


def test_tracking_policy_rejects_single_check_deletion_and_inverted_limits(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="at least two"):
        validate_tracking_policy(target_settings(
            tmp_path, deletion_confirmation_checks=1,
        ))
    with pytest.raises(ValueError, match="must not be below"):
        validate_tracking_policy(target_settings(
            tmp_path,
            collector_refresh_limit=5,
            collector_refresh_scan_limit=4,
        ))


def test_normalizer_rejects_adapter_claimed_confirmed_deletion() -> None:
    target = account(Platform.TELEGRAM)
    raw = replace(
        raw_batch(target, context()),
        publications=(),
        deletion_probes=(RawDeletionProbe(
            _tracked(99, "m:99").id,
            NOW,
            DeletionProbeOutcome.CONFIRMED_DELETED,
            "telegram_invalid_claim",
            2,
        ),),
    )

    with pytest.raises(ValueError, match="derived by the repository"):
        CanonicalNormalizer().normalize(raw, context())

    non_authoritative = replace(
        raw,
        deletion_probes=(RawDeletionProbe(
            _tracked(99, "m:99").id,
            NOW,
            DeletionProbeOutcome.MISSING,
            "telegram_feed_omission",
            2,
        ),),
    )
    with pytest.raises(ValueError, match="not authoritative"):
        CanonicalNormalizer().normalize(non_authoritative, context())


class _MaxPointClient:
    def __init__(self, result: list[MaxPost] | BaseException) -> None:
        self.result = result
        self.requested: list[str] = []

    async def resolve_channel(self, reference: str, native_id: int | None) -> MaxChannel:
        return MaxChannel(9, "MAX", 10, "https://max.ru/channel")

    async def posts(self, chat_id: int, count: int) -> list[MaxPost]:
        return []

    async def posts_by_ids(self, chat_id: int, message_ids: list[str]) -> list[MaxPost]:
        self.requested.extend(message_ids)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    async def close(self) -> None:
        return None


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://provider.test/object")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("provider detail must not escape", request=request, response=response)


def test_max_exact_lookup_omission_is_missing_but_auth_is_transient(
    tmp_path: Path,
) -> None:
    publication = _tracked(10, "10")
    settings = target_settings(tmp_path)
    missing_client = _MaxPointClient([])
    missing = asyncio.run(MaxGatewayCollector(
        settings,
        _FixedClock(),
        missing_client,
        tracking=_Tracking((publication,)),
    ).collect(account(Platform.MAX), context(Platform.MAX)))
    assert missing_client.requested == ["10"]
    assert missing.deletion_probes[0].outcome == DeletionProbeOutcome.MISSING

    auth = asyncio.run(MaxGatewayCollector(
        settings,
        _FixedClock(),
        _MaxPointClient(_http_error(403)),
        tracking=_Tracking((publication,)),
    ).collect(account(Platform.MAX), context(Platform.MAX)))
    assert auth.deletion_probes[0].outcome == DeletionProbeOutcome.TRANSIENT_ERROR
    assert auth.deletion_probes[0].reason_code == "max_auth_error"


def test_telegram_mtproto_exact_omission_is_missing_but_auth_is_transient(
    tmp_path: Path,
) -> None:
    class Client:
        def __init__(self, result: list[Any] | BaseException) -> None:
            self.result = result

        async def get_entity(self, reference: str) -> Any:
            return SimpleNamespace(
                broadcast=True,
                id=7,
                title="Telegram",
                username="channel_1",
                participants_count=10,
            )

        async def iter_messages(self, entity: Any, limit: int):
            if False:
                yield None

        async def get_messages(self, entity: Any, ids: list[int]) -> list[Any]:
            if isinstance(self.result, BaseException):
                raise self.result
            return self.result

    async def collect(result: list[Any] | BaseException) -> RawCollectionBatch:
        settings = target_settings(
            tmp_path, telegram_api_id=1, telegram_api_hash="hash",
        )
        adapter = TelegramMtprotoCollector(
            settings,
            _FixedClock(),
            tracking=_Tracking((_tracked(11, "m:42"),)),
        )
        adapter.reader = SimpleNamespace(client=Client(result))
        adapter._connected = True
        return await adapter.collect(
            account(Platform.TELEGRAM), context(Platform.TELEGRAM),
        )

    missing = asyncio.run(collect([]))
    assert missing.deletion_probes[0].outcome == DeletionProbeOutcome.MISSING
    auth = asyncio.run(collect(type("AuthKeyError", (RuntimeError,), {})("secret")))
    assert auth.deletion_probes[0].outcome == DeletionProbeOutcome.TRANSIENT_ERROR
    assert auth.deletion_probes[0].reason_code == "telegram_mtproto_auth_error"


def test_vk_exact_lookup_omission_is_missing_but_auth_is_transient(
    tmp_path: Path,
) -> None:
    class History(_Tracking):
        def metric_high_watermarks(
            self, target: AccountRef, external_ids: list[str],
        ) -> dict[str, dict[str, int | None]]:
            return {}

    class Client:
        def __init__(self, result: list[VkPost] | BaseException) -> None:
            self.result = result

        async def community(self, reference: str) -> VkCommunity:
            return VkCommunity(123, "uni", "University", 10)

        async def wall(self, community_id: int, count: int) -> list[VkPost]:
            return []

        async def posts(self, post_ids: list[str]) -> list[VkPost]:
            if isinstance(self.result, BaseException):
                raise self.result
            return self.result

        async def close(self) -> None:
            return None

    publication = _tracked(12, "-123_42")
    settings = target_settings(tmp_path)
    missing = asyncio.run(VkGatewayCollector(
        settings,
        _FixedClock(),
        History((publication,)),
        Client([]),  # type: ignore[arg-type]
    ).collect(account(Platform.VK), context(Platform.VK)))
    assert missing.deletion_probes[0].outcome == DeletionProbeOutcome.MISSING

    auth = asyncio.run(VkGatewayCollector(
        settings,
        _FixedClock(),
        History((publication,)),
        Client(_http_error(401)),  # type: ignore[arg-type]
    ).collect(account(Platform.VK), context(Platform.VK)))
    assert auth.deletion_probes[0].outcome == DeletionProbeOutcome.TRANSIENT_ERROR
    assert auth.deletion_probes[0].reason_code == "vk_auth_error"


@pytest.mark.parametrize(
    ("status", "outcome", "reason"),
    (
        (404, DeletionProbeOutcome.MISSING, "rutube_video_http_404"),
        (403, DeletionProbeOutcome.TRANSIENT_ERROR, "rutube_auth_error"),
        (429, DeletionProbeOutcome.TRANSIENT_ERROR, "rutube_rate_limited"),
    ),
)
def test_rutube_point_status_contract_never_turns_auth_or_rate_into_deletion(
    tmp_path: Path,
    status: int,
    outcome: DeletionProbeOutcome,
    reason: str,
    ) -> None:
    class Client:
        async def resolve_channel(self, reference: str, url: str | None) -> int:
            return 5

        async def videos(self, channel_id: int, limit: int):
            return RutubeChannel(5, "RUTUBE", "https://rutube.ru/channel/5/"), []

        async def subscriber_count(self, channel_id: int, url: str | None) -> int:
            return 1

        async def video(self, video_id: str) -> RutubeVideo:
            raise _http_error(status)

        async def video_metrics(self, video_id: str) -> RutubeVideoMetrics:
            raise AssertionError("metrics are not requested for unavailable video")

        async def close(self) -> None:
            return None

    publication = _tracked(20, "0123456789abcdef0123456789abcdef")
    result = asyncio.run(RutubeGatewayCollector(
        target_settings(tmp_path),
        _FixedClock(),
        Client(),  # type: ignore[arg-type]
        tracking=_Tracking((publication,)),
    ).collect(account(Platform.RUTUBE), context(Platform.RUTUBE)))

    assert result.deletion_probes[0].outcome == outcome
    assert result.deletion_probes[0].reason_code == reason


@pytest.mark.parametrize(
    ("point_status", "point_body", "outcome", "reason"),
    (
        (
            200,
            '<div class="tgme_widget_message_error">Post not found</div>',
            DeletionProbeOutcome.MISSING,
            "telegram_public_deleted_marker",
        ),
        (
            403,
            "forbidden",
            DeletionProbeOutcome.TRANSIENT_ERROR,
            "telegram_public_auth_error",
        ),
    ),
)
def test_telegram_public_deleted_marker_is_authoritative_but_auth_is_not(
    tmp_path: Path,
    point_status: int,
    point_body: str,
    outcome: DeletionProbeOutcome,
    reason: str,
) -> None:
    feed = f"""
    <div class="tgme_channel_info_header_title">Example</div>
    <div class="tgme_widget_message" data-post="channel_1/43">
      <time datetime="{(NOW - timedelta(minutes=2)).isoformat()}"></time>
      <span class="tgme_widget_message_views">10</span>
    </div>
    """

    class Client:
        async def get(self, url: str) -> httpx.Response:
            request = httpx.Request("GET", url)
            if "/s/channel_1" in url:
                return httpx.Response(200, text=feed, request=request)
            if "42?embed" in url:
                return httpx.Response(
                    point_status, text=point_body, request=request,
                )
            return httpx.Response(
                200,
                text='<div class="tgme_page_extra">100 subscribers</div>',
                request=request,
            )

    publication = _tracked(30, "m:42", identities=("m:42",))
    result = asyncio.run(TelegramPublicWebCollector(
        target_settings(tmp_path),
        _FixedClock(),
        client=Client(),  # type: ignore[arg-type]
        tracking=_Tracking((publication,)),
    ).collect(account(Platform.TELEGRAM), context(Platform.TELEGRAM)))

    assert result.deletion_probes[0].outcome == outcome
    assert result.deletion_probes[0].reason_code == reason


class _MemoryRepository:
    def __init__(self, accounts: tuple[AccountRef, ...]) -> None:
        self.accounts = accounts
        self.states: dict[tuple[UUID, UUID], RunStatus] = {}
        self.started: list[UUID] = []

    def start_run(self, run_context: CollectionContext) -> None:
        self.started.append(run_context.run_id)

    def record_skipped_run(self, run_context: CollectionContext) -> RunSummary:
        return RunSummary(
            run_context.run_id, run_context.platform, RunStatus.SKIPPED,
            0, 0, NOW, NOW,
        )

    def resumable_scheduled_at(
        self,
        platform: Platform,
        partition_key: str,
        collector_version: str,
    ) -> datetime | None:
        return None

    def enabled_accounts(self, platform: Platform, partition_key: str) -> tuple[AccountRef, ...]:
        return self.accounts

    def begin_account(
        self, run_context: CollectionContext, target: AccountRef, started_at: datetime,
    ) -> bool:
        key = (run_context.run_id, target.id)
        if self.states.get(key) == RunStatus.SUCCEEDED:
            return False
        self.states[key] = RunStatus.RUNNING
        return True

    def persist_account_batch(self, batch: Any) -> Any:
        self.states[(batch.context.run_id, batch.account.id)] = RunStatus.SUCCEEDED
        return None

    def record_account_failure(
        self,
        run_context: CollectionContext,
        target: AccountRef,
        completed_at: datetime,
        error_code: str,
    ) -> None:
        assert "secret" not in error_code
        self.states[(run_context.run_id, target.id)] = RunStatus.FAILED

    def finish_run(self, run_context: CollectionContext, completed_at: datetime) -> RunSummary:
        values = [
            self.states[(run_context.run_id, target.id)] for target in self.accounts
        ]
        errors = values.count(RunStatus.FAILED)
        successes = values.count(RunStatus.SUCCEEDED)
        status = (
            RunStatus.SUCCEEDED if errors == 0 else
            RunStatus.FAILED if successes == 0 else RunStatus.PARTIAL
        )
        return RunSummary(
            run_context.run_id, run_context.platform, status,
            len(values), errors, NOW, completed_at,
        )

    def fail_run(self, run_context: CollectionContext, completed_at: datetime) -> RunSummary:
        return RunSummary(
            run_context.run_id, run_context.platform, RunStatus.FAILED,
            len(self.accounts), 1, NOW, completed_at,
        )


class _RetryAdapter:
    platform = Platform.TELEGRAM

    def __init__(self, failing_id: UUID) -> None:
        self.failing_id = failing_id
        self.attempts: dict[UUID, int] = {}

    async def collect(
        self, target: AccountRef, run_context: CollectionContext,
    ) -> RawCollectionBatch:
        attempt = self.attempts.get(target.id, 0) + 1
        self.attempts[target.id] = attempt
        if target.id == self.failing_id and attempt == 1:
            raise RuntimeError("password=secret should never be persisted")
        return replace(raw_batch(target, run_context), publications=())


def test_coordinator_resumes_failed_accounts_without_replaying_successes() -> None:
    first, second = account(Platform.TELEGRAM, 1), account(Platform.TELEGRAM, 2)
    repository = _MemoryRepository((first, second))
    adapter = _RetryAdapter(second.id)
    coordinator = PollCycleCoordinator(
        platform=Platform.TELEGRAM,
        adapter=adapter,
        repository=repository,
        lease_provider=InMemoryLeaseProvider(),
        collector_version="test-v1",
        account_concurrency=2,
        clock=_FixedClock(),
    )

    first_run = asyncio.run(coordinator.run(NOW))
    second_run = asyncio.run(coordinator.run(NOW))

    assert first_run.status == RunStatus.PARTIAL
    assert second_run.status == RunStatus.SUCCEEDED
    assert first_run.run_id == second_run.run_id
    assert adapter.attempts[first.id] == 1
    assert adapter.attempts[second.id] == 2


class _OutcomeCoordinator:
    def __init__(self, platform: Platform, fails: bool = False) -> None:
        self.platform = platform
        self.fails = fails
        self.called = False

    async def run(self, scheduled_at: datetime | None = None) -> RunSummary:
        self.called = True
        if self.fails:
            raise ConnectionError("secret gateway detail")
        return RunSummary(
            context(self.platform).run_id,
            self.platform,
            RunStatus.SUCCEEDED,
            1,
            0,
            NOW,
            NOW,
        )


def test_supervisor_isolates_max_failure_from_other_platforms() -> None:
    coordinators = (
        _OutcomeCoordinator(Platform.TELEGRAM),
        _OutcomeCoordinator(Platform.VK),
        _OutcomeCoordinator(Platform.MAX, fails=True),
        _OutcomeCoordinator(Platform.RUTUBE),
    )
    outcomes = asyncio.run(PlatformSupervisor(coordinators).run_all(NOW))  # type: ignore[arg-type]
    assert all(coordinator.called for coordinator in coordinators)
    assert outcomes[Platform.MAX].summary is None
    assert outcomes[Platform.MAX].error_code == "ConnectionError"
    assert outcomes[Platform.TELEGRAM].summary is not None
    assert outcomes[Platform.VK].summary is not None
    assert outcomes[Platform.RUTUBE].summary is not None


def test_platform_partition_leases_are_independent_and_deterministic() -> None:
    leases = InMemoryLeaseProvider()
    telegram = leases.acquire(Platform.TELEGRAM, "default")
    assert telegram is not None
    assert leases.acquire(Platform.TELEGRAM, "default") is None
    max_lease = leases.acquire(Platform.MAX, "default")
    assert max_lease is not None
    assert lease_name(Platform.MAX, "default") == "collector:max:default"
    assert advisory_lock_key("collector:max:default") == advisory_lock_key(
        "collector:max:default",
    )
    telegram.release()
    assert leases.acquire(Platform.TELEGRAM, "default") is not None
    max_lease.release()


class _Transaction(AbstractContextManager[None]):
    def __init__(self, connection: "_ScriptedConnection") -> None:
        self.connection = connection

    def __enter__(self) -> None:
        self.connection.transaction_entries += 1
        return None

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        if exc_type is not None:
            self.connection.rollbacks += 1
        else:
            self.connection.commits += 1
        return False


class _Cursor:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self.row = row
        self.rows = rows or []

    def fetchone(self) -> Any:
        return self.row

    def fetchall(self) -> list[Any]:
        return self.rows


class _ScriptedConnection:
    def __init__(self, *, fail_on_outbox: bool = False) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.transaction_entries = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail_on_outbox = fail_on_outbox

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def execute(self, sql: str, params: Any = None) -> _Cursor:
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        if self.fail_on_outbox and "INSERT INTO ops_and_admin.outbox_event" in normalized:
            raise RuntimeError("outbox unavailable")
        if "INSERT INTO ingest.account_metric_snapshot" in normalized:
            return _Cursor({"id": 1})
        if "FROM ingest.publication_identity" in normalized:
            return _Cursor(None)
        if "INSERT INTO ingest.publication AS current" in normalized:
            return _Cursor({"id": UUID("30000000-0000-4000-8000-000000000001")})
        if "INSERT INTO ingest.publication_identity" in normalized:
            return _Cursor({"publication_id": UUID("30000000-0000-4000-8000-000000000001")})
        if "INSERT INTO ingest.publication_metric_snapshot" in normalized:
            return _Cursor({"id": 10})
        if "SELECT id, deleted_at FROM ingest.publication" in normalized:
            return _Cursor({"id": UUID("30000000-0000-4000-8000-000000000001"), "deleted_at": None})
        if "SELECT id FROM ingest.deletion_observation" in normalized:
            return _Cursor(None)
        if "SELECT outcome::text AS outcome" in normalized:
            return _Cursor(None)
        if "INSERT INTO ingest.deletion_observation" in normalized:
            return _Cursor({"id": 11})
        if "UPDATE ingest.collection_account_result" in normalized:
            return _Cursor({"id": 20})
        if "INSERT INTO analytics.dataset_revision" in normalized:
            return _Cursor({"id": 30})
        return _Cursor(None)

    def close(self) -> None:
        self.closed = True


def test_repository_commits_observation_lineage_revision_and_outbox_atomically() -> None:
    connection = _ScriptedConnection()
    repository = PostgresCollectorRepository(connection_factory=lambda: connection)
    target = account(Platform.TELEGRAM)
    raw = raw_batch(target, context())
    raw = replace(
        raw,
        account_observation=replace(
            raw.account_observation,
            username="observed_channel",
            title="Observed channel",
            url="https://t.me/observed_channel",
            native_external_id="12345",
        ),
    )
    canonical = CanonicalNormalizer().normalize(raw, context())

    result = repository.persist_account_batch(canonical)

    sql = "\n".join(statement for statement, _ in connection.calls)
    assert result.discovered_count == 1
    assert result.snapshot_count == 1
    assert result.revision_id == 30
    assert connection.transaction_entries == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed
    assert "INSERT INTO ingest.raw_payload" in sql
    assert "INSERT INTO ingest.deletion_observation" in sql
    assert "INSERT INTO catalog.account_identity_history" in sql
    assert "INSERT INTO catalog.account_external_identity" in sql
    assert "INSERT INTO analytics.dataset_revision" in sql
    assert "INSERT INTO ops_and_admin.outbox_event" in sql
    assert "projection.rebuild.requested" in sql
    assert "dataset.revision.changed" not in sql
    assert "UPDATE ingest.collection_account_result" in sql


def test_repository_rolls_back_whole_account_when_outbox_fails() -> None:
    connection = _ScriptedConnection(fail_on_outbox=True)
    repository = PostgresCollectorRepository(connection_factory=lambda: connection)
    target = account(Platform.TELEGRAM)
    canonical = CanonicalNormalizer().normalize(raw_batch(target, context()), context())

    with pytest.raises(RuntimeError, match="outbox unavailable"):
        repository.persist_account_batch(canonical)

    assert connection.transaction_entries == 1
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.closed


def test_runtime_protocols_and_cli_contract_are_explicit() -> None:
    adapter = _RetryAdapter(account(Platform.TELEGRAM, 2).id)
    repository = _MemoryRepository((account(Platform.TELEGRAM),))
    assert isinstance(adapter, PlatformCollector)
    assert isinstance(repository, CollectorRepository)
    args = _parser().parse_args(["--platform", "rutube", "--once"])
    assert args.platform == "rutube"
    assert args.once is True
    assert args.partition == "default"
    assert _scheduled_slot(
        NOW + timedelta(seconds=299), 300,
    ) == NOW
