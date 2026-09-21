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


def test_profile_b_refuses_to_start_without_its_transport_material(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unusable profile B must fail at startup, not at first delivery.

    By the time a batch is ready the cycle has already spent its provider
    budget; discovering there is no certificate then leaves data with nowhere
    to go.
    """
    monkeypatch.setenv("COLLECTOR_DEPLOYMENT_PROFILE", "b")
    monkeypatch.setenv("COLLECTOR_TRANSFER_MODE", "https-mtls")
    for name in (
        "COLLECTOR_TRANSFER_HTTPS_ENDPOINT",
        "COLLECTOR_TRANSFER_CLIENT_CERTIFICATE",
        "COLLECTOR_TRANSFER_PRIVATE_KEY",
        "COLLECTOR_TRANSFER_CA_BUNDLE",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="profile b requires"):
        Settings.load()


def test_profile_b_requires_the_mtls_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLECTOR_DEPLOYMENT_PROFILE", "b")
    monkeypatch.setenv("COLLECTOR_TRANSFER_MODE", "in-process")
    with pytest.raises(ValueError, match="https-mtls"):
        Settings.load()


def test_mtls_transport_requires_profile_b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLECTOR_DEPLOYMENT_PROFILE", "a")
    monkeypatch.setenv("COLLECTOR_TRANSFER_MODE", "https-mtls")
    with pytest.raises(ValueError, match="COLLECTOR_DEPLOYMENT_PROFILE=b"):
        Settings.load()


def test_unknown_deployment_profile_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COLLECTOR_DEPLOYMENT_PROFILE", "c")
    with pytest.raises(ValueError, match="must be a or b"):
        Settings.load()


def test_profile_a_is_the_default_and_keeps_the_in_process_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("COLLECTOR_DEPLOYMENT_PROFILE", "COLLECTOR_TRANSFER_MODE"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.load()
    assert settings.collector_deployment_profile == "a"
    assert settings.collector_transfer_mode == "in-process"


def test_retention_requires_profile_b(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trimming in profile A would delete exactly what the API serves."""
    monkeypatch.setenv("COLLECTOR_DEPLOYMENT_PROFILE", "a")
    monkeypatch.setenv("COLLECTOR_WORKING_SET_RETENTION", "on")
    with pytest.raises(ValueError, match="COLLECTOR_DEPLOYMENT_PROFILE=b"):
        Settings.load()


@pytest.mark.parametrize("mode", ["yes", "enabled", "true"])
def test_unknown_retention_mode_is_rejected(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    monkeypatch.setenv("COLLECTOR_WORKING_SET_RETENTION", mode)
    with pytest.raises(ValueError, match="off, dry-run or on"):
        Settings.load()


def test_retention_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The one irreversible step in the plan must never start by accident."""
    monkeypatch.delenv("COLLECTOR_WORKING_SET_RETENTION", raising=False)
    assert Settings.load().collector_working_set_retention == "off"
