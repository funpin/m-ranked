from __future__ import annotations

from datetime import datetime, timezone

from api.dto import account


def _row(platform: str, native_id: str | None) -> dict[str, object]:
    return {
        "account_id": "00000000-0000-4000-8000-000000000001",
        "legacy_id": 1,
        "entity_type": "platform_accounts",
        "channel_legacy_id": None,
        "platform_account_legacy_id": 1,
        "institution_id": "00000000-0000-4000-8000-000000000002",
        "institution_legacy_id": 2,
        "canonical_name": "Университет",
        "short_name": None,
        "platform": platform,
        "canonical_external_id": "channel",
        "current_username": "channel",
        "current_title": "Канал",
        "current_url": "https://example.test/channel",
        "native_external_id": native_id,
        "access_mode": "user_session",
        "enabled": True,
        "publication_count": 1,
        "latest_observed_at": datetime(2026, 9, 21, tzinfo=timezone.utc),
        "as_of": datetime(2026, 9, 21, tzinfo=timezone.utc),
    }


def test_max_account_exposes_maxstat_channel_without_post_text() -> None:
    body = account(_row("max", "-70908719079458"), 1)
    assert body["archiveUrl"] == "https://maxstat.ru/channel/-70908719079458/post"


def test_archive_url_is_absent_without_a_valid_max_native_id() -> None:
    assert account(_row("max", None), 1)["archiveUrl"] is None
    assert account(_row("max", "../../posts"), 1)["archiveUrl"] is None
    assert account(_row("telegram", "-70908719079458"), 1)["archiveUrl"] is None
