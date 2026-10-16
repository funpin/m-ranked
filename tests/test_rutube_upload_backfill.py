from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import io

import httpx
import pytest

from collector_runtime.rutube import RutubeClient
from collector_target import rutube_upload_backfill as backfill


def test_sql_fills_only_missing_rutube_dates_in_chunks() -> None:
    first = datetime(2026, 7, 31, 21, tzinfo=timezone.utc)
    moscow = timezone(timedelta(hours=3))
    sql = backfill.backfill_sql([
        ("aaa", first),
        ("bbb", datetime(2026, 8, 1, 3, tzinfo=moscow)),
        ("ccc", first),
    ], chunk=2)
    assert sql.startswith("BEGIN;\n") and sql.rstrip().endswith("COMMIT;")
    assert sql.count("UPDATE ingest.publication") == 2
    assert "('aaa', '2026-07-31T21:00:00+00:00'::timestamptz)" in sql
    assert "('bbb', '2026-08-01T00:00:00+00:00'::timestamptz)" in sql
    assert sql.count("AND p.uploaded_at IS NULL") == 2
    assert sql.count("AND a.platform = 'rutube'") == 2


def test_sql_without_rows_changes_nothing() -> None:
    assert "UPDATE" not in backfill.backfill_sql([])


def test_sql_refuses_an_id_that_is_not_a_rutube_video_id() -> None:
    with pytest.raises(ValueError):
        backfill.backfill_sql([("x'); DROP TABLE t; --", datetime.now(timezone.utc))])


def test_fetch_classifies_found_missing_undated_and_failed_videos() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        video_id = request.url.path.rstrip("/").rsplit("/", 1)[-1]
        if video_id == "gone":
            return httpx.Response(404)
        if video_id == "broken":
            return httpx.Response(500)
        if video_id == "removed":
            # Так RUTUBE отвечает на удалённое видео: 403 «Видео удалено».
            return httpx.Response(403, json={"message": "Видео удалено", "code": "2042002"})
        payload = {"id": video_id, "publication_ts": "2026-08-01T08:00:00"}
        if video_id == "dated":
            payload["created_ts"] = "2026-07-31T21:00:00"
        return httpx.Response(200, json=payload)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = RutubeClient("https://rutube.ru/api", http)
            return await backfill.fetch_upload_times(
                client, ["dated", "gone", "removed", "undated", "broken"], concurrency=2,
            )

    rows, counts = asyncio.run(run())
    assert rows == [("dated", datetime(2026, 7, 31, 21, tzinfo=timezone.utc))]
    assert counts == {
        "found": 1, "missing": 1, "forbidden": 1, "no_created_ts": 1, "error": 1,
    }


def test_read_ids_skips_blanks_duplicates_and_invalid_ids() -> None:
    ids, invalid = backfill.read_ids(io.StringIO("aaa\n\n bbb \naaa\nbad id\n"))
    assert ids == ["aaa", "bbb"]
    assert invalid == 1
