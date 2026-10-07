# tests/test_findings_postgres.py
"""SQL «Находок» на одноразовой базе со всеми миграциями; без неё пропускается.

База создаётся по шагам из плана (mranked_findings_it). Каждый тест строит
свой вуз и аккаунт, поэтому тесты независимы и не чистят за собой.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from uuid import uuid4

import pytest

from api.findings import (
    COMMENT_NORM_FLOOR, FINDING_MIN_COMMENTS, FINDING_MIN_INDEX, FINDING_MIN_INTERACTIONS,
    FINDING_MIN_SHARES, INTERACTION_NORM_FLOOR, MIN_NORM_SAMPLE, NORM_WINDOW_DAYS, PAGE_CAP,
    SHARE_NORM_FLOOR, TOP_REACTIONS, VIEW_NORM_FLOOR, index, norm,
)
from api.findings_norms import serializable
from api.routes.statistics import _like_pattern
from api.sql import findings as sql

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

AS_OF = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ.get("MRANKED_FINDINGS_TEST_DSN", "")
    if not value:
        pytest.skip("MRANKED_FINDINGS_TEST_DSN is required")
    if "findings_it" not in value or not any(host in value for host in ("127.0.0.1", "localhost")):
        raise AssertionError("findings integration test requires the disposable local findings_it database")
    return value


def _connect(dsn: str):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


class World:
    """Вуз с одним аккаунтом и постами, у которых заданы точки по часам."""

    def __init__(self, dsn: str, platform: str = "vk", name: str | None = None) -> None:
        self.dsn, self.platform = dsn, platform
        self.institution, self.account = uuid4(), uuid4()
        with _connect(dsn) as connection:
            self.legacy_id = connection.execute(
                "SELECT coalesce(max(legacy_id),0)+1 AS id FROM catalog.legacy_entity_alias "
                "WHERE entity_type='institutions'").fetchone()["id"]
            connection.execute("INSERT INTO catalog.institution(id,canonical_name,short_name) VALUES (%s,%s,%s)",
                               (self.institution, name or f"Вуз {self.legacy_id}", f"В{self.legacy_id}"))
            connection.execute("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) "
                               "VALUES ('institutions',%s,%s)", (self.legacy_id, self.institution))
            connection.execute("""
                INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                VALUES (%s,%s,%s,%s,'public_web')""",
                (self.account, self.institution, platform, f"findings-{self.account}"))

    def post(self, published_at: datetime, points: dict[int, tuple[int | None, ...]],
             *, level: int | None = None, recheck_to: int | None = None,
             publication_type: str = "photo", external_id: str | None = None):
        """points: час -> (просмотры, реакции[, комментарии[, репосты]])."""
        publication = uuid4()
        with _connect(self.dsn) as connection:
            connection.execute("""
                INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
                VALUES (%s,%s,%s,%s,%s,'complete')""",
                (publication, self.account, published_at, published_at, publication_type))
            if external_id:
                connection.execute("""
                    INSERT INTO ingest.publication_identity(publication_id,platform_account_id,role,external_id,public_url)
                    VALUES (%s,%s,'primary',%s,%s)""", (publication, self.account, external_id, f"https://vk.com/wall{external_id}"))
            for hour, values in points.items():
                views, reactions, comments, shares = (tuple(values) + (None, None))[:4]
                connection.execute("""
                    INSERT INTO analytics.publication_checkpoint(
                      publication_id,hour_offset,observed_at,views_count,reactions_count,comments_count,shares_count)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (publication, hour, published_at + timedelta(hours=hour), views, reactions, comments, shares))
            if level is not None:
                analyzed = published_at + timedelta(hours=30)
                connection.execute("""
                    INSERT INTO analytics.post_anomaly_state(publication_id,published_at,level,analyzed_at,next_due_at)
                    VALUES (%s,%s,%s,%s,%s)""", (publication, published_at, level, analyzed, analyzed))
                if recheck_to is not None:
                    connection.execute("""
                        INSERT INTO analytics.post_anomaly_context_recheck(
                          publication_id,source_analyzed_at,source_level,effective_level,method_version,reason,evidence)
                        VALUES (%s,%s,%s,%s,'test','fixture','{}')""", (publication, analyzed, level, recheck_to))
        return publication

    def reaction_breakdown(self, publication, published_at: datetime, breakdown: dict[str, int]) -> None:
        """Снимок поста с разбивкой реакций; publication_latest заполняет триггер."""
        observed = published_at + timedelta(hours=30)
        month = published_at.astimezone(timezone.utc).date().replace(day=1)
        with _connect(self.dsn) as connection:
            if connection.execute("SELECT max(id) AS id FROM analytics.dataset_revision").fetchone()["id"] is None:
                connection.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id) "
                                   "VALUES ('ingestion',gen_random_uuid())")
            run_id = uuid4()
            connection.execute("""
                INSERT INTO ingest.collection_run(id,platform,partition_key,collector_version,started_at,status,correlation_id)
                VALUES (%s,%s,'findings','integration',%s,'succeeded',gen_random_uuid())""",
                (run_id, self.platform, observed - timedelta(minutes=1)))
            connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
            # Разбивка принимается только вместе со своим снимком: одна транзакция.
            with connection.transaction():
                snapshot = connection.execute("""
                    INSERT INTO ingest.publication_metric_snapshot(
                      published_month,publication_id,collection_run_id,observed_at,age_seconds,sampling_bucket,
                      views_count,reactions_count,quality,source_fingerprint,collected_at,views_quality,reactions_quality)
                    VALUES (%s,%s,%s,%s,%s,0,1000,%s,'exact',%s,%s,'exact','exact') RETURNING id""",
                    (month, publication, run_id, observed, 30 * 3600, sum(breakdown.values()),
                     uuid4().hex, observed)).fetchone()["id"]
                for key, count in breakdown.items():
                    connection.execute("""
                        INSERT INTO ingest.reaction_breakdown(snapshot_published_month,snapshot_id,reaction_key,reaction_count)
                        VALUES (%s,%s,%s,%s)""", (month, snapshot, key, count))

    def baseline(self, count: int = MIN_NORM_SAMPLE, views: int = 1000, reactions: int = 20,
                 days_ago: int = 20) -> None:
        for number in range(count):
            self.post(AS_OF - timedelta(days=days_ago, minutes=number), {24: (views, reactions)})


def run(dsn: str, world: World | None = None, **overrides) -> list[dict]:
    params = {
        "as_of": AS_OF, "period_days": 7,
        "platform": "all", "institution_legacy_id": world.legacy_id if world else None,
        "types": [], "q": "", "search_pattern": "%", "username_pattern": "%",
        "min_sample": MIN_NORM_SAMPLE, "interaction_floor": INTERACTION_NORM_FLOOR,
        "view_floor": VIEW_NORM_FLOOR, "mode": "institution" if world else "all",
        "min_index": FINDING_MIN_INDEX, "min_interactions": FINDING_MIN_INTERACTIONS,
        "sort": "interaction_index", "direction": "desc", "exclude_anomalies": True,
        "group": "none", "cap": PAGE_CAP, "comment_floor": COMMENT_NORM_FLOOR,
        "share_floor": SHARE_NORM_FLOOR, "min_comments": FINDING_MIN_COMMENTS,
        "min_shares": FINDING_MIN_SHARES, "top_reactions": TOP_REACTIONS,
    }
    params.update(overrides)
    with _connect(dsn) as connection:
        # Как в маршруте: нормы — отдельным запросом, в FINDINGS — параметром.
        norms = serializable(connection.execute(sql.NORMS, {
            "as_of": params["as_of"], "norm_days": NORM_WINDOW_DAYS}).fetchall())
        return connection.execute(sql.FINDINGS, params | {"norms": Jsonb(norms)}).fetchall()


def posts(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["publication_id"] is not None]


def test_index_matches_reference_on_24h_point(dsn) -> None:
    world = World(dsn)
    world.baseline(views=1000, reactions=20)
    target = world.post(AS_OF - timedelta(days=2), {24: (3000, 90)}, external_id="-1_7")
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    interaction_norm, sample = norm([20] * MIN_NORM_SAMPLE + [90])
    assert row["age_hours"] == 24 and row["preliminary"] is False
    assert row["interactions"] == 90 and row["views"] == 3000
    assert Decimal(str(row["interaction_norm"])) == interaction_norm
    assert row["interaction_index"] == index(90, interaction_norm, sample, INTERACTION_NORM_FLOOR)
    assert row["erv"] == Decimal(90) * 100 / Decimal(3000)
    assert row["external_id"] == "-1_7"


def test_young_post_uses_latest_point_and_is_preliminary(dsn) -> None:
    world = World(dsn)
    for number in range(MIN_NORM_SAMPLE):
        world.post(AS_OF - timedelta(days=10, minutes=number), {6: (400, 10), 24: (900, 20)})
    young = world.post(AS_OF - timedelta(hours=7), {1: (50, 1), 6: (800, 30)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == young)
    assert row["age_hours"] == 6 and row["preliminary"] is True
    assert row["interaction_index"] == Decimal(30) / Decimal(10)


def test_gap_at_24h_falls_back_without_preliminary(dsn) -> None:
    world = World(dsn)
    for number in range(MIN_NORM_SAMPLE):
        world.post(AS_OF - timedelta(days=10, minutes=number), {12: (500, 10), 24: (900, 20)})
    gapped = world.post(AS_OF - timedelta(days=3), {12: (700, 25), 24: (None, None)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == gapped)
    assert row["age_hours"] == 12 and row["preliminary"] is False


def test_norm_excludes_level_two_and_three_but_recheck_restores(dsn) -> None:
    world = World(dsn)
    world.baseline(reactions=20)
    for number in range(MIN_NORM_SAMPLE + 2):  # more level-3 posts than baseline: inclusion would shift the median
        world.post(AS_OF - timedelta(days=15, minutes=number), {24: (1000, 900)}, level=3)
    restored = world.post(AS_OF - timedelta(days=1), {24: (1000, 60)}, level=2, recheck_to=1)
    hidden = world.post(AS_OF - timedelta(days=1, hours=1), {24: (1000, 80)}, level=2)
    rows = run(dsn, world, mode="all")
    mine = posts(rows)
    assert {row["publication_id"] for row in mine} == {restored}
    assert Decimal(str(mine[0]["interaction_norm"])) == Decimal(20)
    assert mine[0]["norm_sample"] == MIN_NORM_SAMPLE + 1  # baseline + restored; level 2/3 excluded
    assert rows[0]["hidden_anomalous"] == 1
    included = posts(run(dsn, world, exclude_anomalies=False))
    assert hidden in {row["publication_id"] for row in included}
    assert included[0]["hidden_anomalous"] == 0


def test_small_history_has_no_index_and_sorts_last(dsn) -> None:
    world = World(dsn)
    world.baseline(count=MIN_NORM_SAMPLE - 2)
    world.post(AS_OF - timedelta(days=1), {24: (1000, 500)})
    rows = posts(run(dsn, world))
    assert rows and all(row["interaction_index"] is None for row in rows[-1:])
    assert not posts(run(dsn, world, mode="all", institution_legacy_id=None, platform="vk",
                         q=f"В{world.legacy_id}", search_pattern=f"%в{world.legacy_id}%",
                         username_pattern=f"%в{world.legacy_id}%"))


def test_floors_prevent_noise_on_tiny_norms(dsn) -> None:
    world = World(dsn)
    world.baseline(views=10, reactions=1)
    target = world.post(AS_OF - timedelta(days=1), {24: (100, 10)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    assert row["interaction_index"] == Decimal(10) / Decimal(INTERACTION_NORM_FLOOR)
    assert row["view_index"] == Decimal(100) / Decimal(VIEW_NORM_FLOOR)


def test_max_counts_only_reactions(dsn) -> None:
    world = World(dsn, platform="max")
    world.baseline(reactions=10)
    target = world.post(AS_OF - timedelta(days=1), {24: (1000, 40)})
    with _connect(dsn) as connection:
        connection.execute("UPDATE analytics.publication_checkpoint SET comments_count=500, shares_count=500 "
                           "WHERE publication_id=%s", (target,))
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    assert row["interactions"] == 40


def test_type_filter_folds_rare_types_into_other(dsn) -> None:
    world = World(dsn)
    world.baseline()
    poll = world.post(AS_OF - timedelta(days=1), {24: (1000, 30)}, publication_type="poll")
    video = world.post(AS_OF - timedelta(days=1), {24: (1000, 30)}, publication_type="video")
    assert {row["publication_id"] for row in posts(run(dsn, world, types=["other"]))} == {poll}
    assert {row["publication_id"] for row in posts(run(dsn, world, types=["video"]))} == {video}


def test_search_treats_wildcards_literally(dsn) -> None:
    world = World(dsn, name="Институт 50%_проверки")
    world.baseline()
    world.post(AS_OF - timedelta(days=1), {24: (1000, 60)})
    pattern = _like_pattern("50%_")
    found = posts(run(dsn, world, q="50%_", search_pattern=pattern, username_pattern=pattern))
    assert found
    other = _like_pattern("50xx")
    assert not posts(run(dsn, world, q="50xx", search_pattern=other, username_pattern=other))


def test_group_mode_returns_top_three_per_institution(dsn) -> None:
    world = World(dsn)
    world.baseline()
    for reactions in (40, 50, 60, 70):
        world.post(AS_OF - timedelta(days=1, minutes=reactions), {24: (1000, reactions)})
    rows = [row for row in posts(run(dsn, None, group="institution"))
            if row["institution_legacy_id"] == world.legacy_id]
    assert [row["interactions"] for row in rows] == [70, 60, 50]
    assert {row["institution_finding_count"] for row in rows} == {4}


def test_empty_result_still_returns_summary_row(dsn) -> None:
    world = World(dsn)
    rows = run(dsn, world, period_days=1)
    assert len(rows) == 1 and rows[0]["publication_id"] is None
    assert rows[0]["hidden_anomalous"] == 0


def test_institutions_list_has_legacy_ids(dsn) -> None:
    world = World(dsn)
    with _connect(dsn) as connection:
        rows = connection.execute(sql.INSTITUTIONS).fetchall()
    assert any(row["legacy_id"] == world.legacy_id for row in rows)


def test_checkpoint_after_as_of_is_ignored(dsn) -> None:
    world = World(dsn)
    for number in range(MIN_NORM_SAMPLE):
        world.post(AS_OF - timedelta(days=10, minutes=number), {6: (400, 10), 24: (900, 20)})
    # Пост восьмичасовой на момент as_of: точка 24-го часа ещё не наступила.
    young = world.post(AS_OF - timedelta(hours=8), {6: (800, 30), 24: (5000, 400)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == young)
    assert row["age_hours"] == 6 and row["interactions"] == 30 and row["preliminary"] is True


def test_norm_sample_counts_interaction_norm_posts(dsn) -> None:
    world = World(dsn)
    world.baseline(reactions=20)
    # Без просмотров: в норму взаимодействий пост входит, в норму просмотров — нет.
    for number in range(3):
        world.post(AS_OF - timedelta(days=12, minutes=number), {24: (None, 20)})
    target = world.post(AS_OF - timedelta(days=1), {24: (1000, 60)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    assert row["norm_sample"] == MIN_NORM_SAMPLE + 3 + 1


def test_comment_and_share_indexes_drive_their_own_feed(dsn) -> None:
    world = World(dsn, platform="vk")
    for number in range(MIN_NORM_SAMPLE):
        world.post(AS_OF - timedelta(days=12, minutes=number), {24: (1000, 20, 4, 3)})
    discussed = world.post(AS_OF - timedelta(days=1), {24: (1000, 20, 12, 3)})
    shared = world.post(AS_OF - timedelta(days=1, hours=2), {24: (1000, 20, 4, 15)})
    rows = {row["publication_id"]: row for row in posts(run(dsn, world))}
    assert rows[discussed]["comment_index"] == Decimal(12) / Decimal(4)
    assert rows[shared]["share_index"] == Decimal(15) / Decimal(3)
    feed = lambda sort: {row["publication_id"] for row in posts(run(
        dsn, None, sort=sort, q=f"В{world.legacy_id}", search_pattern=f"%в{world.legacy_id}%",
        username_pattern=f"%в{world.legacy_id}%"))}
    # Лайков у обоих как обычно: в ленту взаимодействий не попадают,
    # а по своему индексу — попадают.
    assert feed("interaction_index") == set()
    assert feed("comment_index") == {discussed}
    assert feed("share_index") == {shared}


def test_comment_index_ignores_platforms_without_comments(dsn) -> None:
    world = World(dsn, platform="max")
    for number in range(MIN_NORM_SAMPLE):
        world.post(AS_OF - timedelta(days=12, minutes=number), {24: (1000, 20, 4, 3)})
    target = world.post(AS_OF - timedelta(days=1), {24: (1000, 20, 40, 30)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    assert row["comment_index"] is None and row["share_index"] is None
    assert row["comments"] is None and row["shares"] is None


def test_curve_has_post_and_norm_values_by_hour(dsn) -> None:
    world = World(dsn)
    for number in range(MIN_NORM_SAMPLE):
        world.post(AS_OF - timedelta(days=12, minutes=number), {1: (100, 2), 6: (400, 8), 24: (900, 20)})
    target = world.post(AS_OF - timedelta(days=1, hours=2), {1: (300, 10), 6: (900, 30), 24: (2000, 60)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    assert row["post_curve"] == {"1": 10, "6": 30, "24": 60}
    assert {hour: float(value) for hour, value in row["norm_curve"].items()} == {"1": 2.0, "6": 8.0, "24": 20.0}


def test_top_reactions_come_from_latest_snapshot(dsn) -> None:
    world = World(dsn, platform="telegram")
    world.baseline()
    published = AS_OF - timedelta(days=1, hours=3)
    target = world.post(published, {24: (1000, 60)})
    other = world.post(AS_OF - timedelta(days=2), {24: (1000, 60)})
    world.reaction_breakdown(target, published, {"👍": 5, "🔥": 30, "custom:5064709487953183440": 12, "❤": 20})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    assert row["top_reactions"] == [
        {"reaction": "🔥", "count": 30}, {"reaction": "❤", "count": 20},
        {"reaction": "custom:5064709487953183440", "count": 12}][:TOP_REACTIONS]
    plain = next(row for row in posts(run(dsn, world)) if row["publication_id"] == other)
    assert plain["top_reactions"] is None
