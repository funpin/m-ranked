from api.outbox import MARK_BATCH


def test_outbox_marker_is_bounded_and_uses_worker_columns_only() -> None:
    normalized = " ".join(MARK_BATCH.split())
    assert "FOR UPDATE SKIP LOCKED LIMIT 500" in normalized
    assert "published_at=transaction_timestamp()" in normalized
    assert "publish_attempts=event.publish_attempts+1" in normalized
    assert "DELETE" not in normalized
    assert "payload=" not in normalized
