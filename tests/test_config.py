from app.config import Settings


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
