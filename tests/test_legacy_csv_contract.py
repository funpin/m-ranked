from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.web.app import create_app


UTC = timezone.utc


def _settings(root: Path) -> Settings:
    return Settings(
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_session_path=root / "telegram.session",
        database_path=root / "legacy-csv.sqlite",
        initial_channels=(),
        poll_interval_minutes=60,
        track_post_for_hours=336,
        complete_history_max_first_age_minutes=90,
        jump_min_abs=15,
        jump_min_ratio=2.0,
        web_host="127.0.0.1",
        web_port=8080,
        display_timezone="Europe/Moscow",
        log_path=root / "legacy-csv.log",
        discovery_limit=200,
        discovery_overlap=20,
    )


def _client(tmp_path: Path) -> tuple[Database, TestClient]:
    settings = _settings(tmp_path)
    database = Database(settings.database_path)
    database.migrate()
    return database, TestClient(create_app(settings, database))


def _assert_download(response, filename: str) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{filename}"'
    )
    assert not response.content.startswith(b"\xef\xbb\xbf")


def test_telegram_exports_are_byte_exact_and_keep_null_distinct_from_zero(tmp_path):
    database, client = _client(tmp_path)
    channel_id = database.add_channel("alpha")
    published = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    post_id = database.add_post(
        channel_id,
        "m:20",
        [20],
        None,
        published,
        published,
        0,
        True,
        "text",
        False,
    )
    database.insert_snapshot(
        post_id,
        datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
        3_600,
        5,
        {"👍": 5},
        {"source": "first"},
        60,
        15,
        2.0,
        comments_count=0,
        views_count=None,
    )
    database.insert_snapshot(
        post_id,
        datetime(2026, 9, 1, 2, 0, tzinfo=UTC),
        7_200,
        5,
        {"👍": 5},
        {"source": "second"},
        60,
        15,
        2.0,
        comments_count=None,
        views_count=0,
    )
    database.add_post(
        channel_id,
        "m:21",
        [21],
        None,
        datetime(2026, 9, 1, 3, 0, tzinfo=UTC),
        datetime(2026, 9, 1, 3, 0, tzinfo=UTC),
        0,
        False,
        "text",
        False,
    )

    posts = client.get("/export/posts.csv")
    _assert_download(posts, "posts.csv")
    assert posts.content == (
        "канал,id_публикации,опубликовано,полная_история,"
        "последнее_число_реакций,последнее_число_просмотров,"
        "последнее_число_комментариев,максимальный_скачок,"
        "возраст_скачка_часов\r\n"
        "alpha,20,2026-09-01T00:00:00+00:00,1,5,0,,0,2.0\r\n"
        "alpha,21,2026-09-01T03:00:00+00:00,0,,,,,\r\n"
    ).encode()

    snapshots = client.get("/export/snapshots.csv")
    _assert_download(snapshots, "snapshots.csv")
    assert snapshots.content == (
        "канал,id_публикации,опубликовано,измерено,возраст_часов,"
        "реакций_всего,изменение_реакций,просмотры,изменение_просмотров,"
        "комментарии,изменение_комментариев,реакции_json\r\n"
        'alpha,20,2026-09-01T00:00:00+00:00,2026-09-01T01:00:00+00:00,'
        '1.0,5,,,,0,,"{""👍"": 5}"\r\n'
        'alpha,20,2026-09-01T00:00:00+00:00,2026-09-01T02:00:00+00:00,'
        '2.0,5,0,0,,,,"{""👍"": 5}"\r\n'
    ).encode()


def test_generic_exports_use_the_latest_whole_snapshot_and_excel_escaping(tmp_path):
    database, client = _client(tmp_path)
    institution_id = database.add_institution(
        "University North", 'Uni, "North"'
    )
    account_id = database.add_platform_account(
        institution_id,
        "vk",
        "wall,-10",
        url="https://vk.com/wall,-10",
    )
    published = datetime(2026, 9, 2, 0, 0, tzinfo=UTC)
    post_id = database.upsert_platform_post(
        account_id,
        "-10_20",
        published,
        published,
        "post",
        "https://vk.com/wall-10_20?from=a,b",
        {"caption": "Привет, мир"},
        history_complete=True,
    )
    database.insert_platform_snapshot(
        post_id,
        datetime(2026, 9, 2, 1, 0, tzinfo=UTC),
        3_600,
        60,
        views_count=100,
        reactions_count=9,
        comments_count=None,
        shares_count=3,
        raw={"ordinal": 1},
    )
    database.insert_platform_snapshot(
        post_id,
        datetime(2026, 9, 2, 2, 0, tzinfo=UTC),
        7_200,
        60,
        views_count=0,
        reactions_count=None,
        comments_count=2,
        shares_count=None,
        raw={"caption": "Привет, мир", "ordinal": 2},
    )

    posts = client.get("/export/posts.csv?platform=vk")
    _assert_download(posts, "posts-vk.csv")
    assert posts.content == (
        "площадка,вуз,аккаунт,id_публикации,опубликовано,тип,ссылка,"
        "последние_просмотры,последние_реакции,последние_комментарии,"
        "последние_репосты\r\n"
        'vk,"Uni, ""North""","wall,-10",-10_20,2026-09-02T00:00:00+00:00,'
        'post,"https://vk.com/wall-10_20?from=a,b",0,,2,\r\n'
    ).encode()

    snapshots = client.get("/export/snapshots.csv?platform=vk")
    _assert_download(snapshots, "snapshots-vk.csv")
    assert snapshots.content == (
        "площадка,вуз,аккаунт,id_публикации,опубликовано,измерено,"
        "возраст_часов,просмотры,реакции,комментарии,репосты,сырой_json\r\n"
        'vk,"Uni, ""North""","wall,-10",-10_20,2026-09-02T00:00:00+00:00,'
        '2026-09-02T01:00:00+00:00,1.0,100,9,,3,"{""ordinal"": 1}"\r\n'
        'vk,"Uni, ""North""","wall,-10",-10_20,2026-09-02T00:00:00+00:00,'
        '2026-09-02T02:00:00+00:00,2.0,0,,2,,"{""caption"": '
        '""Привет, мир"", ""ordinal"": 2}"\r\n'
    ).encode()

    all_posts = client.get("/export/posts.csv?platform=all")
    _assert_download(all_posts, "posts-all.csv")
    assert all_posts.content == posts.content


def test_platform_query_normalization_preserves_legacy_aliases_and_fallback(tmp_path):
    _database, client = _client(tmp_path)
    telegram_header = client.get("/export/posts.csv").content
    generic_header = client.get("/export/posts.csv?platform=all").content

    for value in ("", "unknown", "TELEGRAM", " TG "):
        response = client.get("/export/posts.csv", params={"platform": value})
        _assert_download(response, "posts.csv")
        assert response.content == telegram_header

    response = client.get("/export/posts.csv", params={"platform": " ОБЩИЙ "})
    _assert_download(response, "posts-all.csv")
    assert response.content == generic_header


def test_strangler_phases_keep_unaccepted_legacy_csv_urls_on_legacy():
    route_root = Path(__file__).resolve().parents[1] / "operations" / "nginx" / "routes"

    for name in (
        "phase-1-overview.conf",
        "phase-2-public-read.conf",
        "phase-3-writer-freeze.conf",
    ):
        config = (route_root / name).read_text(encoding="utf-8")
        assert re.search(
            r"location\s+/\s*\{\s*proxy_pass\s+http://m_ranked_legacy;",
            config,
        ), name
        assert not re.search(r"location[^\{]*?/export(?:/|\s|\$)", config), name
