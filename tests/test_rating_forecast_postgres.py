"""Снимки прогноза М-Рейтинга на одноразовой базе «Находок»; без неё пропускается.

Применить 0084 к базе перед запуском: psql -f db/migrations/0084_rating_forecast.sql.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from api import rating_forecast as rf
from api.sql import rating as sql
from test_findings_postgres import World, _connect, dsn  # noqa: F401 — фикстура dsn

START = datetime(2026, 9, 30, 21, tzinfo=timezone.utc)   # 1 октября по Москве
END = datetime(2026, 10, 31, 21, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean(dsn):
    # Тесты не видят чужих снимков. Официальные импорты и наблюдения append-only:
    # тесты берут свой период или свой вуз и не мешают друг другу.
    with _connect(dsn) as connection:
        connection.execute("DELETE FROM rating.rating_run")
        if connection.execute("SELECT max(id) AS id FROM analytics.dataset_revision").fetchone()["id"] is None:
            connection.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id) "
                               "VALUES ('ingestion',gen_random_uuid())")


def payload(institution, as_of, status="running", window_start=START, window_end=None, score=50.0):
    window_end = window_end or min(END, as_of)
    return {"formulaKey": rf.FORMULA_KEY, "version": 1, "windowStart": window_start.isoformat(),
            "windowEnd": window_end.isoformat(), "asOf": as_of.isoformat(), "startedAt": as_of.isoformat(),
            "inputHash": hashlib.sha256(f"{status}{as_of}{window_start}".encode()).hexdigest(),
            "parameters": {"status": status, "basePeriod": "Сентябрь 2026"},
            "results": [{"institutionId": str(institution), "score": score, "rank": 8,
                         "explanation": {"code": "37", "categories": {}}}]}


def record(dsn, body):
    with _connect(dsn) as connection:
        return connection.execute("SELECT ops_and_admin.record_rating_forecast(%s) AS result",
                                  (Jsonb(body),)).fetchone()["result"]


def runs(dsn):
    with _connect(dsn) as connection:
        return connection.execute("SELECT id, as_of, parameters->>'status' AS status, window_start FROM rating.rating_run "
                                  "ORDER BY as_of").fetchall()


def test_formula_v1_matches_the_python_definition(dsn):
    with _connect(dsn) as connection:
        row = connection.execute("SELECT definition, status, source_hash FROM rating.formula_definition "
                                 "WHERE formula_key=%s AND version=1", (rf.FORMULA_KEY,)).fetchone()
    assert row["status"] == "published"
    assert row["definition"] == rf.FORMULA_V1
    canonical = json.dumps(rf.FORMULA_V1, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert row["source_hash"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_record_accepts_a_running_snapshot_minutes_after_month_start(dsn):
    world = World(dsn, "vk")
    result = record(dsn, payload(world.institution, START + timedelta(minutes=30)))
    assert result["replaced"] == 0 and result["runId"]
    with _connect(dsn) as connection:
        stored = connection.execute("SELECT r.score, r.rank, r.quality::text AS quality, run.window_end, run.as_of "
                                    "FROM rating.rating_result r JOIN rating.rating_run run ON run.id=r.rating_run_id").fetchone()
    assert (float(stored["score"]), stored["rank"], stored["quality"]) == (50.0, 8, "estimated")
    assert stored["window_end"] == stored["as_of"]


def test_record_replaces_the_same_moscow_day(dsn):
    world = World(dsn, "vk")
    record(dsn, payload(world.institution, datetime(2026, 10, 15, 22, 10, tzinfo=timezone.utc)))  # 16.10 01:10 МСК
    second = record(dsn, payload(world.institution, datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc), score=51))
    assert second["replaced"] == 1 and len(runs(dsn)) == 1
    record(dsn, payload(world.institution, datetime(2026, 10, 16, 22, 10, tzinfo=timezone.utc)))  # 17.10 МСК
    assert len(runs(dsn)) == 2


def test_record_never_touches_a_published_run(dsn):
    world = World(dsn, "vk")
    as_of = datetime(2026, 10, 16, 22, 10, tzinfo=timezone.utc)
    record(dsn, payload(world.institution, as_of))
    with _connect(dsn) as connection:
        connection.execute("SELECT ops_and_admin.finalize_rating_forecast(%s, %s)", (rf.FORMULA_KEY, START))
    assert record(dsn, payload(world.institution, as_of + timedelta(hours=1)))["replaced"] == 0
    assert [row["status"] for row in runs(dsn)] == ["published", "running"]


def test_finalize_keeps_the_latest_snapshot_and_removes_the_rest(dsn):
    world = World(dsn, "vk")
    for day in (10, 11, 12):
        record(dsn, payload(world.institution, datetime(2026, 11, day, 22, tzinfo=timezone.utc), status="final"))
    with _connect(dsn) as connection:
        result = connection.execute("SELECT ops_and_admin.finalize_rating_forecast(%s, %s) AS result",
                                    (rf.FORMULA_KEY, START)).fetchone()["result"]
        events = connection.execute("SELECT affected_tags FROM ops_and_admin.outbox_event "
                                    "WHERE event_type='rating_forecast.finalized' ORDER BY id DESC LIMIT 1").fetchone()
    assert result["removed"] == 2
    assert [(row["as_of"].day, row["status"]) for row in runs(dsn)] == [(12, "published")]
    assert events["affected_tags"] == ["rating-forecast"]


def test_retrospective_is_one_per_month_and_survives_finalize(dsn):
    world = World(dsn, "vk")
    september = datetime(2026, 8, 31, 21, tzinfo=timezone.utc)
    october_end = datetime(2026, 9, 30, 21, tzinfo=timezone.utc)
    as_of = datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
    for _ in range(2):
        record(dsn, payload(world.institution, as_of, status="retrospective", window_start=september,
                            window_end=october_end))
    with _connect(dsn) as connection:
        connection.execute("SELECT ops_and_admin.finalize_rating_forecast(%s, %s)", (rf.FORMULA_KEY, september))
    assert [row["status"] for row in runs(dsn)] == ["retrospective"]


def test_record_rejects_unknown_status_and_formula(dsn):
    world = World(dsn, "vk")
    body = payload(world.institution, START + timedelta(hours=1), status="published")
    with pytest.raises(Exception, match="invalid rating forecast"):
        record(dsn, body)
    body = payload(world.institution, START + timedelta(hours=1))
    body["version"] = 99
    with pytest.raises(Exception, match="unknown rating formula"):
        record(dsn, body)


def test_official_period_scores_read_the_latest_import(dsn):
    period = f"Тест {uuid4().hex[:8]}"
    with _connect(dsn) as connection:
        for fetched, social in (("2026-10-10T00:00:00Z", 40.0), ("2026-10-12T00:00:00Z", 46.9)):
            evidence = {"year": 2026, "month": "Сентябрь", "items": [
                {"code": "37", "name": "Вуз 37", "scores": {"social": social, "ok": 60.4, "vk": 56.7, "rt": 19.2,
                                                         "consolidated": 22.0}},
                {"code": "", "name": "без кода", "scores": {"social": 1.0}}]}
            connection.execute("""
                INSERT INTO rating.official_import(actor,correlation_id,period,source_url,source_hash,fetched_at,
                  evidence,evidence_sha256)
                VALUES ('test',gen_random_uuid(),%s,'https://www.m-rating.ru/r.json',%s,%s,%s,%s)""",
                (period, hashlib.sha256(fetched.encode()).hexdigest(), fetched, Jsonb(evidence),
                 hashlib.sha256(fetched.encode()).hexdigest()))
        rows = connection.execute("SELECT * FROM rating.official_period_scores(%s)", (period,)).fetchall()
        periods = connection.execute("SELECT period FROM rating.official_periods()").fetchall()
    assert [(row["code"], float(row["social_score"]), float(row["max_score"]), float(row["rutube_score"]),
             float(row["consolidated_score"])) for row in rows] == [("37", 46.9, 60.4, 19.2, 22.0)]
    assert {"period": period} in periods


def test_grants_follow_the_roles(dsn):
    with _connect(dsn) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='api_write_admin'").fetchone():
            pytest.skip("роли не созданы")
        check = connection.execute("""
            SELECT has_function_privilege('api_write_admin','ops_and_admin.record_rating_forecast(jsonb)','EXECUTE') AS writer,
                   has_function_privilege('api_read','ops_and_admin.record_rating_forecast(jsonb)','EXECUTE') AS reader,
                   has_function_privilege('api_write_admin','rating.official_period_scores(text)','EXECUTE') AS scores,
                   has_table_privilege('api_write_admin','rating.rating_run','DELETE') AS direct_delete,
                   has_table_privilege('api_read','rating.rating_run','SELECT') AS read_runs""").fetchone()
    assert check == {"writer": True, "reader": False, "scores": True, "direct_delete": False, "read_runs": True}

def _platform_month(dsn, window_start, window_end, mature_before, role=None):
    with _connect(dsn) as connection:
        if role:
            connection.execute(f"SET ROLE {role}")
        return connection.execute(sql.PLATFORM_MONTH, {"window_start": window_start, "window_end": window_end,
                                                       "mature_before": mature_before}).fetchall()


def coded(dsn, world, code):
    with _connect(dsn) as connection:
        connection.execute("INSERT INTO catalog.institution_external_id(institution_id,namespace,external_id,valid_from) "
                           "VALUES (%s,'m-rating',%s,'2026-01-01')", (world.institution, code))


def latest(dsn, publication, views, reactions, comments=0, shares=0):
    with _connect(dsn) as connection:
        connection.execute("""
            INSERT INTO analytics.publication_latest(publication_id,institution_id,platform_account_id,platform,observed_at,
              views_count,views_observed_at,views_quality,reactions_count,reactions_observed_at,reactions_quality,
              comments_count,comments_observed_at,comments_quality,shares_count,shares_observed_at,shares_quality,
              quality,history_completeness,dataset_revision_id)
            SELECT p.id,a.institution_id,a.id,a.platform,now(),%s,now(),'exact',%s,now(),'exact',%s,now(),'exact',%s,now(),'exact',
                   'exact','complete',(SELECT max(id) FROM analytics.dataset_revision)
              FROM ingest.publication p JOIN catalog.platform_account a ON a.id=p.primary_account_id WHERE p.id=%s""",
            (views, reactions, comments, shares, publication))


SEPT = (datetime(2026, 8, 31, 21, tzinfo=timezone.utc), datetime(2026, 9, 30, 21, tzinfo=timezone.utc))


def test_platform_month_sums_moscow_month_and_mature_posts(dsn):
    world = World(dsn, "vk")
    code = f"t{world.legacy_id}"
    coded(dsn, world, code)
    with _connect(dsn) as connection:
        connection.execute("UPDATE catalog.platform_account SET created_at='2026-08-01' WHERE id=%s", (world.account,))
    inside = world.post(datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc), {})   # 1 сентября 00:30 МСК
    young = world.post(datetime(2026, 9, 29, 12, tzinfo=timezone.utc), {})
    world.post(datetime(2026, 8, 31, 20, 59, tzinfo=timezone.utc), {})            # 31 августа МСК
    latest(dsn, inside, 1000, 30, 5, 5)
    latest(dsn, young, 10, 1)
    rows = [row for row in _platform_month(dsn, *SEPT, datetime(2026, 9, 27, tzinfo=timezone.utc))
            if row["code"] == code]
    assert len(rows) == 1
    row = rows[0]
    assert (row["platform"], row["posts"], row["mature_posts"], row["mature_views"], row["mature_interactions"]) == \
        ("vk", 2, 1, 1000, 40)
    assert (row["viewed_posts"], row["views"], row["interactions"], row["covered"]) == (2, 1010, 41, True)


def test_platform_month_marks_accounts_added_mid_month_uncovered(dsn):
    """Нижневартовский ГУ: VK добавлен 15.09, самая ранняя публикация 02.09."""
    world = World(dsn, "vk")
    code = f"t{world.legacy_id}"
    coded(dsn, world, code)
    with _connect(dsn) as connection:
        connection.execute("UPDATE catalog.platform_account SET created_at='2026-09-15' WHERE id=%s", (world.account,))
    world.post(datetime(2026, 9, 2, 9, tzinfo=timezone.utc), {})
    row = next(row for row in _platform_month(dsn, *SEPT, SEPT[1]) if row["code"] == code)
    assert row["covered"] is False
    # История, догруженная до начала месяца, делает месяц покрытым.
    world.post(datetime(2026, 7, 1, 9, tzinfo=timezone.utc), {})
    row = next(row for row in _platform_month(dsn, *SEPT, SEPT[1]) if row["code"] == code)
    assert row["covered"] is True


def test_platform_month_lists_coded_institutions_without_accounts_and_runs_as_api_read(dsn):
    world = World(dsn, "telegram")       # Telegram в прогноз не входит
    code = f"t{world.legacy_id}"
    coded(dsn, world, code)
    with _connect(dsn) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='api_read'").fetchone():
            pytest.skip("роль api_read не создана")
    rows = [row for row in _platform_month(dsn, *SEPT, SEPT[1], role="api_read") if row["code"] == code]
    assert [(row["platform"], row["posts"]) for row in rows] == [(None, None)]


def test_months_and_rows_prefer_the_real_forecast_over_retrospective(dsn):
    world = World(dsn, "vk")
    as_of = datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
    record(dsn, payload(world.institution, as_of, status="retrospective", window_start=SEPT[0], window_end=SEPT[1]))
    record(dsn, payload(world.institution, as_of, status="final", window_start=SEPT[0], window_end=SEPT[1], score=60))
    with _connect(dsn) as connection:
        months = connection.execute(sql.FORECAST_MONTHS, {"formula_key": rf.FORMULA_KEY}).fetchall()
        run = connection.execute(sql.FORECAST_RUN, {"formula_key": rf.FORMULA_KEY, "window_start": SEPT[0]}).fetchone()
        rows = connection.execute(sql.FORECAST_ROWS, {"run_id": run["id"], "period": "Сентябрь 2026"}).fetchall()
    assert [(item["month"], item["status"]) for item in months] == [("2026-09", "final")]
    assert run["parameters"]["status"] == "final" and run["version"] == 1
    assert (float(rows[0]["score"]), rows[0]["legacy_id"], rows[0]["actual"]) == (60.0, world.legacy_id, None)


def test_rows_join_the_official_actual_for_the_period(dsn):
    world = World(dsn, "vk")
    as_of = datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
    record(dsn, payload(world.institution, as_of, status="retrospective", window_start=SEPT[0], window_end=SEPT[1]))
    with _connect(dsn) as connection:
        for category, rank, score in (("social", 8, 65.9), ("vk", 38, 70.2)):
            connection.execute("""
                INSERT INTO rating.official_rating_observation(institution_id,category,period,rank,score,source_url,
                  source_hash,fetched_at) VALUES (%s,%s,'Сентябрь 2026',%s,%s,'https://www.m-rating.ru/r.json',%s,now())""",
                (world.institution, category, rank, score, hashlib.sha256(category.encode()).hexdigest()))
        run = connection.execute(sql.FORECAST_RUN, {"formula_key": rf.FORMULA_KEY, "window_start": SEPT[0]}).fetchone()
        connection.execute("SET ROLE api_read")
        row = connection.execute(sql.FORECAST_ROWS, {"run_id": run["id"], "period": "Сентябрь 2026"}).fetchone()
    assert row["actual"]["social"] == {"rank": 8, "score": 65.9}
    assert row["actual"]["vk"]["rank"] == 38
