"""Читатели истории отвечают одинаково до и после упаковки (0059).

Каждый запрос веб-пути и пакетных заданий выполняется на горячих строках,
затем вся история упаковывается, и тот же запрос с теми же параметрами
обязан вернуть ровно то же. Нужна одноразовая база со схемой:

    MRANKED_TEST_PACKED_ADMIN_DSN=postgresql://postgres:…@127.0.0.1:…/mranked
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from uuid import UUID, uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

from api import findings as findings_rules  # noqa: E402
from api.sql import compare, details, findings  # noqa: E402
from anomaly_analysis.v2 import store as anomaly_store  # noqa: E402

ADMIN = os.environ.get("MRANKED_TEST_PACKED_ADMIN_DSN", "")
pytestmark = pytest.mark.skipif(not ADMIN, reason="disposable PostgreSQL DSN is required")

POSTS = 60
ACCOUNTS = 3

LOAD = """
SET session_replication_role = replica;
INSERT INTO catalog.institution(id, canonical_name, short_name) VALUES (%(institution)s, 'Readers fixture', 'RF');
INSERT INTO catalog.platform_account(id, institution_id, platform, canonical_external_id, access_mode, current_username)
SELECT a.id, %(institution)s, 'telegram', 'readers-' || a.id, 'public_web', 'readers' || a.n
  FROM unnest(%(accounts)s::uuid[]) WITH ORDINALITY AS a(id, n);
INSERT INTO ingest.collection_run(id, platform, partition_key, collector_version, started_at, status, correlation_id)
SELECT r, 'telegram', 'readers', 'test', %(now)s, 'succeeded', gen_random_uuid() FROM unnest(%(runs)s::uuid[]) r;
INSERT INTO ingest.publication(id, primary_account_id, published_at, discovered_at, publication_type,
                               history_completeness)
SELECT p.id, (%(accounts)s::uuid[])[1 + (p.n %% %(account_count)s)], %(now)s - p.n * interval '13 hours',
       %(now)s - p.n * interval '13 hours', 'post', 'complete'
  FROM unnest(%(posts)s::uuid[]) WITH ORDINALITY AS p(id, n);
INSERT INTO catalog.legacy_entity_alias(entity_type, legacy_id, target_uuid, legacy_route)
SELECT 'channels', %(alias_base)s + a.n, a.id, '/channels/' || (%(alias_base)s + a.n)
  FROM unnest(%(accounts)s::uuid[]) WITH ORDINALITY AS a(id, n);
INSERT INTO catalog.legacy_entity_alias(entity_type, legacy_id, target_uuid, legacy_route)
SELECT 'platform_posts', %(alias_base)s + p.n, p.id, '/platform-posts/' || (%(alias_base)s + p.n)
  FROM unnest(%(posts)s::uuid[]) WITH ORDINALITY AS p(id, n);
WITH offs AS (
  SELECT k, CASE WHEN k <= 180 THEN k * 480 WHEN k <= 330 THEN 86400 + (k-180) * 1150
                 WHEN k <= 456 THEN 259200 + (k-330) * 2740 ELSE 604800 + (k-456) * 15300 END AS age
    FROM generate_series(1, 590) k)
INSERT INTO ingest.publication_metric_snapshot(published_month, id, publication_id, collection_run_id, observed_at,
  age_seconds, sampling_bucket, views_count, reactions_count, comments_count, shares_count, quality, views_quality,
  reactions_quality, comments_quality, shares_quality, interval_uncertain, source_fingerprint, collected_at,
  created_at, metric_evidence)
SELECT date_trunc('month', p.published_at AT TIME ZONE 'UTC')::date, nextval(pg_get_serial_sequence('ingest.publication_metric_snapshot', 'id')),
       p.id, (%(runs)s::uuid[])[1 + (o.k %% 7)], p.published_at + o.age * interval '1 second' + (o.k %% 5) * interval '1 millisecond',
       o.age, floor(extract(epoch FROM p.published_at + o.age * interval '1 second') / 300)::bigint,
       o.k * 37 + o.age / 60, o.k / 3, CASE WHEN o.k %% 4 = 0 THEN NULL ELSE o.k / 9 END, o.k / 40,
       CASE WHEN o.k %% 97 = 0 THEN 'invalid' ELSE 'exact' END::ingest.observation_quality,
       CASE WHEN o.k %% 61 = 0 THEN 'suspected_reset' ELSE 'exact' END::ingest.observation_quality,
       CASE WHEN o.k %% 7 = 0 THEN 'rounded' ELSE 'exact' END::ingest.observation_quality,
       'unknown', 'exact', o.k %% 11 = 0, md5(p.id::text || o.k),
       p.published_at + o.age * interval '1 second' + interval '2 seconds',
       p.published_at + o.age * interval '1 second' + interval '20 seconds',
       jsonb_build_object('views', jsonb_build_object('quality', 'exact', 'k', o.k %% 3))
  FROM ingest.publication p JOIN offs o ON p.published_at + o.age * interval '1 second' < %(now)s
 WHERE p.id = ANY (%(posts)s::uuid[]);
-- Исправления: тот же бакет, следующая версия.
INSERT INTO ingest.publication_metric_snapshot(published_month, id, publication_id, collection_run_id, observed_at,
  age_seconds, sampling_bucket, views_count, reactions_count, comments_count, shares_count, quality, views_quality,
  reactions_quality, comments_quality, shares_quality, source_fingerprint, collected_at, created_at,
  correction_sequence, supersedes_snapshot_id, correction_reason, metric_evidence)
SELECT s.published_month, nextval(pg_get_serial_sequence('ingest.publication_metric_snapshot', 'id')), s.publication_id,
       s.collection_run_id, s.observed_at + interval '40 seconds', s.age_seconds + 40, s.sampling_bucket,
       s.views_count + 5, s.reactions_count + 1, s.comments_count, s.shares_count, s.quality, s.views_quality,
       s.reactions_quality, s.comments_quality, s.shares_quality, md5(s.source_fingerprint),
       s.collected_at + interval '40 seconds', s.created_at + interval '40 seconds', 1, s.id,
       'provider_payload_changed', s.metric_evidence
  FROM ingest.publication_metric_snapshot s
 WHERE s.publication_id = ANY (%(posts)s::uuid[]) AND s.id %% 23 = 0;
INSERT INTO ingest.reaction_breakdown(snapshot_published_month, snapshot_id, reaction_key, reaction_count)
SELECT s.published_month, s.id, key, s.reactions_count / k
  FROM ingest.publication_metric_snapshot s CROSS JOIN (VALUES ('👍', 1), ('❤️', 2), ('🔥', 3)) AS r(key, k)
 WHERE s.publication_id = ANY (%(posts)s::uuid[]) AND s.id %% 3 = 0 AND s.reactions_count IS NOT NULL;
SET session_replication_role = origin;
"""


def connect():
    if not any(host in ADMIN for host in ("127.0.0.1", "localhost")):
        raise AssertionError("readers tests write and delete observations: local disposable database only")
    return psycopg.connect(ADMIN, autocommit=True, row_factory=dict_row)


@pytest.fixture(scope="module")
def fixture():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    ids = {"institution": uuid4(), "accounts": [uuid4() for _ in range(ACCOUNTS)],
           "posts": [uuid4() for _ in range(POSTS)], "runs": [uuid4() for _ in range(7)],
           "now": now, "account_count": ACCOUNTS,
           # Повторный прогон на той же базе: свои номера алиасов.
           "alias_base": 900_000_000 + uuid4().int % 1_000_000 * 1000}
    with connect() as connection:
        connection.execute("INSERT INTO analytics.dataset_revision(cause, correlation_id) "
                           "VALUES ('ingestion', gen_random_uuid())")
        for month in sorted({(now - timedelta(hours=13 * n)).date().replace(day=1) for n in range(POSTS + 2)}):
            connection.execute("SELECT ops_and_admin.ensure_publication_metric_partition(%s)", (month,))
        for statement in filter(str.strip, LOAD.split(";\n")):
            if not statement.strip().startswith("--") or "\n" in statement.strip():
                connection.execute(statement, ids if "%(" in statement else None)
        connection.execute("ANALYZE ingest.publication_metric_snapshot")
    return ids


def publication(connection, post: UUID) -> dict:
    return connection.execute("SELECT id, primary_account_id, published_at, "
                              "date_trunc('month', published_at AT TIME ZONE 'UTC')::date AS published_month "
                              "FROM ingest.publication WHERE id = %s", (post,)).fetchone()


def answers(connection, ids) -> dict[str, list]:
    """Ответы всех читателей на одном и том же наборе параметров."""
    result: dict[str, list] = {}
    as_of = ids["now"]
    for index in (1, 5, 20, 45):
        post = publication(connection, ids["posts"][index])
        base = {"publication_id": post["id"], "published_month": post["published_month"], "as_of": as_of}
        result[f"history:{index}"] = connection.execute(details.HISTORY, {
            **base, "after_snapshot_id": None, "fetch_limit": 3000}).fetchall()
        result[f"history-page:{index}"] = connection.execute(details.HISTORY, {
            **base, "after_snapshot_id": None, "fetch_limit": 40}).fetchall()
        result[f"fingerprint:{index}"] = connection.execute(details.HISTORY_FINGERPRINT, base).fetchall()
    for account in ids["accounts"]:
        result[f"stats:{account}"] = connection.execute(details.ACCOUNT_STATS, {
            "account_id": account, "as_of": as_of, "days": 30, "institution_id": ids["institution"],
            "platform": "telegram"}).fetchall()
        result[f"daily:{account}"] = connection.execute(details.ACCOUNT_DAILY, {
            "account_id": account, "as_of": as_of}).fetchall()
        for day in (as_of.date() - timedelta(days=1), as_of.date() - timedelta(days=9)):
            result[f"publications:{account}:{day}"] = connection.execute(details.ACCOUNT_PUBLICATIONS, {
                "account_id": account, "after_id": None, "as_of": as_of, "fetch_limit": 200,
                "growth_day": day, "publication_legacy_type": "platform_posts"}).fetchall()
    # Разбивка реакций одной точки по номеру снимка (топ реакций в «Находках»).
    rows = connection.execute("""SELECT s.publication_id, s.published_month, s.id FROM ingest.publication_metric_point s
                                  WHERE s.publication_id = ANY (%s) AND s.reaction_breakdown <> '{}'
                                  ORDER BY s.id LIMIT 25""", (ids["posts"],)).fetchall()
    for item in rows:
        result[f"point:{item['id']}"] = connection.execute(
            "SELECT * FROM ingest.publication_point_by_id(%s, %s, %s)",
            (item["publication_id"], item["published_month"], item["id"])).fetchall()
    # Пакетные читатели анализа аномалий.
    posts = [publication(connection, post) for post in ids["posts"]]
    months = sorted({post["published_month"] for post in posts})
    result["series"] = connection.execute(anomaly_store.SERIES, {
        "ids": [post["id"] for post in posts], "months": months}).fetchall()
    for back in (timedelta(hours=1), timedelta(days=3), timedelta(days=12)):
        result[f"progress:{back}"] = connection.execute(anomaly_store.PROGRESS, {
            "ids": [post["id"] for post in posts], "published": [post["published_at"] for post in posts],
            "last": [max(post["published_at"], as_of - back) for post in posts]}).fetchall()
    for since in (as_of - timedelta(hours=20), as_of - timedelta(days=6)):
        result[f"activity:{since}"] = connection.execute(anomaly_store.ACTIVITY, {
            "accounts": ids["accounts"], "published_since": as_of - timedelta(days=40), "months": months,
            "since": since, "until": as_of}).fetchall()
    for horizon in (6, 48):
        result[f"comparison:{horizon}"] = connection.execute(compare.COMPARISON, {
            "aggregation": "median", "as_of": as_of, "horizon_hours": horizon, "hot_days": 70,
            "include_partial": True, "metric": "views", "platform": "telegram", "revision": 1,
            "selection_ids": json.dumps([ids["alias_base"] + n for n in range(1, ACCOUNTS + 1)])}).fetchall()
    return result


HOT_ONLY = ("source_fingerprint", "semantic_fingerprint", "ingested_xid", "packed")


def normalized(rows: list) -> list:
    """Поля только горячего слоя у упакованных точек пустые: из сравнения они
    уходят, а отпечаток источника — и из происхождения точки."""
    def clean(row: dict) -> dict:
        result = {key: value for key, value in row.items() if key not in HOT_ONLY}
        if isinstance(result.get("lineage"), dict):
            result["lineage"] = {key: value for key, value in result["lineage"].items()
                                 if key != "sourceFingerprint"}
        return result
    return json.loads(json.dumps([clean(row) for row in rows], default=str, sort_keys=True))


def test_readers_answer_the_same_before_and_after_packing(fixture):
    with connect() as connection:
        before = answers(connection, fixture)
        for post in fixture["posts"]:
            connection.execute("SELECT ingest.compact_publication_history(%s, %s)",
                               (post, fixture["now"] - timedelta(days=2)))
        packed = connection.execute("SELECT count(*) AS n FROM ingest.publication_metric_history "
                                    "WHERE publication_id = ANY (%s)", (fixture["posts"],)).fetchone()["n"]
        after = answers(connection, fixture)
    assert packed >= POSTS - 4  # самым свежим постам упаковывать ещё нечего
    empty = [name for name, rows in before.items() if not rows]
    assert not empty, f"fixture gives these readers nothing to compare: {empty}"
    for name in before:
        assert normalized(after[name]) == normalized(before[name]), name


def test_point_by_id_reads_the_same_breakdown_as_the_reaction_table(fixture):
    with connect() as connection:
        pairs = connection.execute("""
            SELECT s.publication_id, s.published_month, s.id,
                   (SELECT jsonb_object_agg(r.reaction_key, r.reaction_count) FROM ingest.reaction_breakdown r
                     WHERE r.snapshot_published_month = s.published_month AND r.snapshot_id = s.id) AS table_breakdown
              FROM ingest.publication_metric_snapshot s
             WHERE s.publication_id = ANY (%s) AND s.id %% 3 = 0 ORDER BY s.id LIMIT 40""",
            (fixture["posts"],)).fetchall()
        for pair in pairs:
            point = connection.execute("SELECT reaction_breakdown FROM ingest.publication_point_by_id(%s, %s, %s)",
                                       (pair["publication_id"], pair["published_month"], pair["id"])).fetchone()
            assert point["reaction_breakdown"] == (pair["table_breakdown"] or {})


def test_findings_sql_runs_with_route_parameters(fixture):
    rules = findings_rules
    with connect() as connection:
        connection.execute(findings.FINDINGS, {
            "as_of": fixture["now"], "period_days": 7, "norms": psycopg.types.json.Jsonb([]),
            "platform": "all", "institution_legacy_id": None, "types": [], "q": "", "search_pattern": "%",
            "username_pattern": "%", "min_sample": rules.MIN_NORM_SAMPLE,
            "interaction_floor": rules.INTERACTION_NORM_FLOOR, "view_floor": rules.VIEW_NORM_FLOOR,
            "mode": "all", "min_index": rules.FINDING_MIN_INDEX, "min_interactions": rules.FINDING_MIN_INTERACTIONS,
            "sort": "index", "direction": "desc", "exclude_anomalies": False, "group": "none", "cap": 50,
            "comment_floor": rules.COMMENT_NORM_FLOOR, "share_floor": rules.SHARE_NORM_FLOOR,
            "min_comments": rules.FINDING_MIN_COMMENTS, "min_shares": rules.FINDING_MIN_SHARES,
            "top_reactions": 3}).fetchall()
