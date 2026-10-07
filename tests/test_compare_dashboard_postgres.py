"""SQL панели сравнения на одноразовой базе «Находок»; без неё пропускается.

Окно, московское время и корзины форматов догрузки по вузу должны совпадать с
панелью: на одной ревизии числа вуза складываются в общие.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from api.sql import compare as sql
from test_findings_postgres import World, _connect, dsn  # noqa: F401 — фикстура dsn

AS_OF = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


def _timing(dsn: str, institution, days: int = 7) -> dict:
    with _connect(dsn) as connection:
        return connection.execute(sql.INSTITUTION_TIMING,
                                  {"as_of": AS_OF, "days": days, "institution_id": institution}).fetchone()


def _cell(rows: list[dict], platform: str, weekday: int | None, hour: int) -> dict | None:
    return next((row for row in rows if row["platform"] == platform
                 and row["weekday"] == weekday and row["hour"] == hour), None)


def _type(rows: list[dict], platform: str, kind: str) -> dict | None:
    return next((row for row in rows if row["platform"] == platform and row["publication_type"] == kind), None)


def test_institution_timing_buckets_moscow_time_formats_and_window(dsn):
    world = World(dsn, "vk")
    # 21:30 UTC понедельника — 00:30 вторника по Москве.
    world.post(datetime(2026, 9, 21, 21, 30, tzinfo=timezone.utc), {24: (100, 5)})
    world.post(datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc), {24: (300, 9)}, publication_type="poll")
    # Без 24-го часа: пост считается, в медиану не входит.
    world.post(datetime(2026, 9, 23, 9, 10, tzinfo=timezone.utc), {1: (10, 0)})
    world.post(AS_OF - timedelta(days=7), {24: (9999, 0)})            # граница окна не входит
    world.post(AS_OF + timedelta(minutes=1), {24: (9999, 0)})         # после среза
    disabled = uuid4()
    with _connect(dsn) as connection:
        connection.execute("""
            INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode,enabled)
            VALUES (%s,%s,'telegram',%s,'public_web',false)""", (disabled, world.institution, f"compare-{disabled}"))
        connection.execute("""
            INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
            VALUES (%s,%s,%s,%s,'photo','complete')""", (uuid4(), disabled, AS_OF - timedelta(hours=1), AS_OF))
    World(dsn, "vk").post(datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc), {24: (5000, 1)})

    row = _timing(dsn, world.institution)
    assert row["found"] == 1
    timing, types = row["timing"], row["types"]
    assert {(cell["platform"]) for cell in timing} == {"vk", "all"}
    assert _cell(timing, "vk", 1, 0) == {"platform": "vk", "weekday": 1, "hour": 0, "posts": 1, "views24": 100}
    assert _cell(timing, "vk", None, 12) == {"platform": "vk", "weekday": None, "hour": 12, "posts": 2, "views24": 300}
    assert _cell(timing, "all", None, 0)["posts"] == 1
    assert sum(cell["posts"] for cell in timing if cell["platform"] == "all" and cell["weekday"] is None) == 3
    assert _type(types, "vk", "photo") == {"platform": "vk", "publication_type": "photo", "posts": 2,
                                           "views24": 100, "engagement24": 5}
    assert _type(types, "all", "other")["posts"] == 1 and _type(types, "all", "poll") is None


def test_institution_timing_matches_the_dashboard_and_runs_as_api_read(dsn):
    world = World(dsn, "telegram")
    for hours in (2, 5, 30):
        world.post(AS_OF - timedelta(hours=hours), {24: (200 + hours, 3)}, publication_type="sticker")
    with _connect(dsn) as connection:
        dashboard = connection.execute(sql.DASHBOARD, {"as_of": AS_OF, "days": 7}).fetchone()
    stat = next(item for item in dashboard["stats"]
                if item["institution_id"] == str(world.institution) and item["platform"] == "all")
    row = _timing(dsn, world.institution)
    assert stat["posts"] == 3 == sum(cell["posts"] for cell in row["timing"]
                                     if cell["platform"] == "all" and cell["weekday"] is None)
    assert {item["publication_type"] for item in dashboard["types"]} <= {"text", "photo", "album", "video", "other"}

    with _connect(dsn) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='api_read'").fetchone():
            pytest.skip("роль api_read не создана")
        connection.execute("SET ROLE api_read")
        found = connection.execute(sql.INSTITUTION_TIMING, {
            "as_of": AS_OF, "days": 7, "institution_id": world.institution}).fetchone()["found"]
        missing = connection.execute(sql.INSTITUTION_TIMING, {
            "as_of": AS_OF, "days": 7, "institution_id": uuid4()}).fetchone()
    assert found == 1
    assert (missing["found"], missing["timing"], missing["types"]) == (0, [], [])
