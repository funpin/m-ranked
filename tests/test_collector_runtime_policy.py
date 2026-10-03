from __future__ import annotations

from dataclasses import dataclass
import json
import os

import pytest

from collector_target.runtime_policy import RuntimeOverlay, RuntimeSettings, validate_collection_policy


@dataclass(frozen=True)
class Base:
    track_post_for_hours: int = 720
    poll_interval_minutes: int = 5
    collector_refresh_limit: int = 100
    collector_refresh_scan_limit: int = 400
    collector_membership: str = ""


def write(path, document):
    path.write_text(json.dumps(document), encoding="utf-8")
    # mtime тестового файла может совпасть с прошлым — размер тоже входит в отметку.
    os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns + 1))


def test_policy_overrides_environment_until_the_file_disappears(tmp_path):
    path = tmp_path / "runtime.json"
    settings = RuntimeSettings(Base())
    overlay = RuntimeOverlay(path, Base())
    assert overlay.refresh() is False
    write(path, {"version": "3", "membership": "server-1:telegram,server-3:telegram|vk",
                 "collection": {"trackPostDays": 14, "pollIntervalMinutes": 10, "refreshLimit": 900}})
    assert overlay.refresh() is True
    settings.apply(overlay.state.overrides)
    assert settings.track_post_for_hours == 14 * 24
    assert settings.poll_interval_minutes == 10
    # Лимит обновления не превышает лимит обхода окружения.
    assert settings.collector_refresh_limit == 400
    assert overlay.state.membership.startswith("server-1")
    assert overlay.refresh() is False
    path.unlink()
    assert overlay.refresh() is True and overlay.state is None
    settings.apply({})
    assert settings.track_post_for_hours == 720


def test_broken_file_keeps_the_previous_policy(tmp_path):
    path = tmp_path / "runtime.json"
    overlay = RuntimeOverlay(path, Base())
    write(path, {"collection": {"trackPostDays": 20}})
    overlay.refresh()
    path.write_text("{not json", encoding="utf-8")
    assert overlay.refresh() is False
    assert overlay.state.overrides == {"track_post_for_hours": 480}


@pytest.mark.parametrize("policy", [{"trackPostDays": 0}, {"pollIntervalMinutes": True},
                                    {"unknown": 1}, {"heartbeatMaxAgeDays": -1}])
def test_out_of_range_policy_is_rejected(policy):
    with pytest.raises(ValueError):
        validate_collection_policy(policy)


def test_runtime_settings_are_read_only():
    settings = RuntimeSettings(Base())
    with pytest.raises(AttributeError):
        settings.track_post_for_hours = 1
