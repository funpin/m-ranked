from collector_runtime.config import Settings
import pytest


def test_storage_retention_does_not_extend_post_tracking(monkeypatch, tmp_path):
    monkeypatch.delenv("RETENTION_DAYS", raising=False)
    monkeypatch.delenv("TRACK_POST_FOR_HOURS", raising=False)
    monkeypatch.delenv("COLLECTOR_REFRESH_LIMIT", raising=False)
    monkeypatch.delenv("COLLECTOR_REFRESH_SCAN_LIMIT", raising=False)
    monkeypatch.delenv("PUBLICATION_SNAPSHOT_HEARTBEAT_HOURS", raising=False)

    settings = Settings.load(tmp_path / "missing.env")

    assert settings.retention_days == 70
    assert settings.track_post_for_hours == 960
    assert settings.collector_refresh_limit == 100
    assert settings.collector_refresh_scan_limit == 400
    assert settings.publication_snapshot_heartbeat_hours == 24
    assert settings.max_request_timeout_seconds == 30.0
    assert settings.collector_schedule_mode == "phased"
    assert settings.collector_phase_max_wait_seconds == 900
    assert settings.collector_transfer_mode == "in-process"
    assert settings.collector_transfer_producer_id == "local"


def test_phase_configuration_is_strict(monkeypatch, tmp_path):
    monkeypatch.setenv("COLLECTOR_SCHEDULE_MODE", "phased")
    monkeypatch.setenv("COLLECTOR_PHASE_RETRY_SECONDS", "0")

    with pytest.raises(ValueError, match="COLLECTOR_PHASE_RETRY_SECONDS"):
        Settings.load(tmp_path / "missing.env")

    monkeypatch.setenv("COLLECTOR_PHASE_RETRY_SECONDS", "1.5")
    settings = Settings.load(tmp_path / "missing.env")
    assert settings.collector_schedule_mode == "phased"
    assert settings.collector_phase_retry_seconds == 1.5


def test_legacy_schedule_mode_is_an_explicit_rollback(monkeypatch, tmp_path):
    monkeypatch.setenv("COLLECTOR_SCHEDULE_MODE", "legacy")
    assert Settings.load(tmp_path / "missing.env").collector_schedule_mode == "legacy"


def test_invalid_schedule_mode_has_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("COLLECTOR_SCHEDULE_MODE", "surprise")
    with pytest.raises(ValueError, match="must be legacy, phased or shadow"):
        Settings.load(tmp_path / "missing.env")


def test_transfer_mode_is_strict_and_can_be_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("COLLECTOR_TRANSFER_MODE", "disabled")
    assert Settings.load(tmp_path / "missing.env").collector_transfer_mode == "disabled"
    monkeypatch.setenv("COLLECTOR_TRANSFER_MODE", "socket")
    with pytest.raises(ValueError, match="disabled, in-process or https-mtls"):
        Settings.load(tmp_path / "missing.env")
