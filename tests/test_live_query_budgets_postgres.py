"""Measured live-read budgets on the restored PostgreSQL fixture.

The limits are release guards, not production SLO evidence: they cover one
developer machine and the 2026-09-11 data copy. Every public screen and the
management screen is represented by the SQL it executes.
"""
from __future__ import annotations

from datetime import date
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
import pytest

from api.config import Settings
from api.sql import admin, analysis, compare, details, overview, statistics
from conftest import requires_api_database


pytestmark = requires_api_database

# A plan may regress up to these explicit release limits. Comparison receives
# separate limits because it scans bounded raw history; all other screens share
# a tighter envelope. Buffer counts are root-plan shared hit+read blocks.
DEFAULT_BUDGET = (1_000.0, 100_000)
COMPARISON_24H_BUDGET = (4_000.0, 220_000)
COMPARISON_336H_BUDGET = (5_000.0, 260_000)


def _plan(connection: psycopg.Connection[Any], statement: str,
          parameters: dict[str, Any]) -> tuple[float, int]:
    document = connection.execute(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
        parameters,
    ).fetchone()["QUERY PLAN"][0]
    root = document["Plan"]
    blocks = sum(int(root.get(name, 0)) for name in (
        "Shared Hit Blocks", "Shared Read Blocks", "Shared Dirtied Blocks",
        "Shared Written Blocks",
    ))
    return float(document["Execution Time"]), blocks


def _assert_budget(name: str, measured: tuple[float, int],
                   budget: tuple[float, int]) -> None:
    elapsed_ms, blocks = measured
    limit_ms, limit_blocks = budget
    print(f"{name}: {elapsed_ms:.3f} ms, {blocks} shared blocks")
    assert elapsed_ms <= limit_ms, f"{name}: {elapsed_ms:.3f} ms > {limit_ms} ms"
    assert blocks <= limit_blocks, f"{name}: {blocks} blocks > {limit_blocks}"


def _fixture(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    row = connection.execute(
        """SELECT revision.id AS revision,revision.committed_at AS as_of,
                  institution.id AS institution_id,institution_alias.legacy_id AS institution_legacy_id,
                  account.id AS account_id,account_alias.legacy_id AS account_legacy_id,
                  publication.id AS publication_id,publication.published_at,
                  publication_alias.legacy_id AS publication_legacy_id
             FROM analytics.dataset_revision revision
             CROSS JOIN LATERAL (
               SELECT publication.* FROM ingest.visible_publication publication
               JOIN analytics.publication_latest latest ON latest.publication_id=publication.id
               JOIN catalog.visible_platform_account fixture_account
                 ON fixture_account.id=publication.primary_account_id
                AND fixture_account.platform='telegram'
               ORDER BY publication.published_at DESC LIMIT 1
             ) publication
             JOIN catalog.visible_platform_account account ON account.id=publication.primary_account_id
             JOIN catalog.visible_institution institution ON institution.id=account.institution_id
             JOIN catalog.legacy_entity_alias institution_alias ON institution_alias.target_uuid=institution.id
               AND institution_alias.entity_type='institutions'
             JOIN catalog.legacy_entity_alias account_alias ON account_alias.target_uuid=account.id
               AND account_alias.entity_type=CASE WHEN account.platform='telegram' THEN 'channels' ELSE 'platform_accounts' END
             JOIN catalog.legacy_entity_alias publication_alias ON publication_alias.target_uuid=publication.id
               AND publication_alias.entity_type=CASE WHEN account.platform='telegram' THEN 'posts' ELSE 'platform_posts' END
            WHERE revision.id=(SELECT max(id) FROM analytics.dataset_revision)
            LIMIT 1"""
    ).fetchone()
    assert row is not None
    return dict(row)


def _comparison_ids(connection: psycopg.Connection[Any], platform: str,
                    as_of: Any, horizon: int) -> list[int]:
    if platform == "telegram":
        statement = """SELECT alias.legacy_id,count(*) AS publications
             FROM catalog.visible_platform_account account
             JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=account.id
               AND alias.entity_type='channels'
             JOIN ingest.visible_publication publication ON publication.primary_account_id=account.id
            WHERE account.enabled AND account.platform='telegram'
              AND publication.published_at>=%s::timestamptz-interval '70 days'
              AND publication.published_at+make_interval(hours=>%s)<=%s::timestamptz
            GROUP BY alias.legacy_id ORDER BY publications DESC,alias.legacy_id LIMIT 25"""
    else:
        statement = """SELECT alias.legacy_id,count(*) AS publications
             FROM catalog.visible_institution institution
             JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=institution.id
               AND alias.entity_type='institutions'
             JOIN catalog.visible_platform_account account ON account.institution_id=institution.id
             JOIN ingest.visible_publication publication ON publication.primary_account_id=account.id
            WHERE account.enabled AND account.platform::text=%s
              AND publication.published_at>=%s::timestamptz-interval '70 days'
              AND publication.published_at+make_interval(hours=>%s)<=%s::timestamptz
            GROUP BY alias.legacy_id ORDER BY publications DESC,alias.legacy_id LIMIT 25"""
    parameters = ((as_of, horizon, as_of) if platform == "telegram"
                  else (platform, as_of, horizon, as_of))
    rows = connection.execute(statement, parameters).fetchall()
    return [int(row["legacy_id"]) for row in rows]


def test_public_screen_query_budgets() -> None:
    settings = Settings()
    with psycopg.connect(settings.read_dsn, autocommit=True, row_factory=dict_row) as connection:
        connection.execute("SET statement_timeout='15s'")
        connection.execute("SET max_parallel_workers_per_gather=0")
        fixture = _fixture(connection)
        common = {"as_of": fixture["as_of"]}
        checks: list[tuple[str, str, dict[str, Any], tuple[float, int]]] = [
            ("overview", overview.OVERVIEW, common | {
                "period": "30d", "platform": "all", "sort": "median_reactions",
                "direction": "desc", "search": "", "after_id": None, "fetch_limit": 51,
            }, DEFAULT_BUDGET),
            ("statistics-entities", statistics.ENTITIES, common | {
                "period": "30d", "platform": "vk", "q": "", "search_pattern": "%",
                "username_pattern": "%", "entity_sort": "erv", "entity_direction": "desc",
            }, DEFAULT_BUDGET),
            ("statistics-publications", statistics.PUBLICATIONS, common | {
                "period": "30d", "platform": "all", "q": "", "search_pattern": "%",
                "username_pattern": "%", "publication_sort": "erv",
                "publication_direction": "desc",
            }, DEFAULT_BUDGET),
            ("compare-candidates", compare.CANDIDATES, common | {
                "platform": "telegram", "after_id": None, "fetch_limit": 51,
            }, DEFAULT_BUDGET),
            ("institution", details.INSTITUTION, common | {
                "legacy_id": fixture["institution_legacy_id"], "platform": "all",
                "period": "30d", "revision": fixture["revision"],
            }, DEFAULT_BUDGET),
            ("account", details.ACCOUNT, common | {
                "entity_uuid": None, "legacy_id": fixture["account_legacy_id"],
                "legacy_type": "channels",
            }, DEFAULT_BUDGET),
            ("account-stats", details.ACCOUNT_STATS, common | {
                "account_id": fixture["account_id"], "institution_id": fixture["institution_id"],
                "platform": "telegram", "days": 70,
            }, DEFAULT_BUDGET),
            ("institution-accounts", details.INSTITUTION_ACCOUNTS, common | {
                "legacy_id": fixture["institution_legacy_id"], "platform": "all",
                "after_id": None, "fetch_limit": 51,
            }, DEFAULT_BUDGET),
            ("institution-account-count", details.INSTITUTION_ACCOUNT_COUNT, {
                "legacy_id": fixture["institution_legacy_id"], "platform": "all",
            }, DEFAULT_BUDGET),
            ("account-publications", details.ACCOUNT_PUBLICATIONS, common | {
                "account_id": fixture["account_id"], "publication_legacy_type": "posts",
                "after_id": None, "fetch_limit": 51, "days": 70, "growth_day": None,
            }, DEFAULT_BUDGET),
            ("publication", details.PUBLICATION, common | {
                "entity_uuid": None, "legacy_id": fixture["publication_legacy_id"],
                "legacy_type": "posts",
            }, DEFAULT_BUDGET),
            ("publication-history", details.HISTORY, common | {
                "publication_id": fixture["publication_id"],
                "published_month": date(fixture["published_at"].year, fixture["published_at"].month, 1),
                "after_snapshot_id": None, "fetch_limit": 2001,
            }, DEFAULT_BUDGET),
            ("publication-collector-coverage", details.COLLECTOR_COVERAGE, common | {
                "publication_id": fixture["publication_id"],
                "from_at": fixture["published_at"], "expected_interval_seconds": 300,
            }, DEFAULT_BUDGET),
            ("publication-neighbours", details.NEIGHBOURS, {
                "publication_id": fixture["publication_id"], "legacy_type": "posts",
            }, DEFAULT_BUDGET),
            ("anomaly-resolve", analysis.RESOLVE, {
                "entity_uuid": None, "legacy_id": fixture["publication_legacy_id"],
                "legacy_type": "posts",
            }, DEFAULT_BUDGET),
            ("anomaly-load", analysis.LOAD, {
                "publication": fixture["publication_id"], "after": None,
                "fetch_limit": 51, "limit": 50,
            }, DEFAULT_BUDGET),
        ]
        for name, statement, parameters, budget in checks:
            _assert_budget(name, _plan(connection, statement, parameters), budget)

        for platform in ("telegram", "vk", "max", "rutube"):
            for horizon in ((24, 336) if platform in ("telegram", "vk") else (24,)):
                selected = _comparison_ids(connection, platform, fixture["as_of"], horizon)
                assert selected, f"representative {platform}/{horizon}h cohort is empty"
                parameters = common | {
                    "revision": fixture["revision"], "platform": platform,
                    "horizon_hours": horizon, "include_partial": True,
                    "metric": "reactions", "aggregation": "median",
                    "selection_ids": json.dumps(selected), "hot_days": 70,
                }
                budget = COMPARISON_336H_BUDGET if horizon == 336 else COMPARISON_24H_BUDGET
                _assert_budget(
                    f"comparison-{platform}-{horizon}h",
                    _plan(connection, compare.COMPARISON, parameters), budget,
                )


def test_management_screen_query_budgets() -> None:
    settings = Settings()
    if not settings.admin_dsn:
        pytest.skip("API_WRITE_ADMIN_DB_* is not configured")
    with psycopg.connect(settings.admin_dsn, autocommit=True, row_factory=dict_row) as connection:
        connection.execute("SET statement_timeout='15s'")
        connection.execute("SET max_parallel_workers_per_gather=0")
        fixture = _fixture(connection)
        checks = (
            ("manage-catalog", admin.CATALOG, {"after": 0, "limit": 51}),
            ("manage-accounts", admin.CATALOG_ACCOUNTS, {
                "institution": fixture["institution_id"], "after": 0, "limit": 51,
            }),
            ("manage-status", admin.CATALOG_STATUS, {}),
        )
        for name, statement, parameters in checks:
            _assert_budget(name, _plan(connection, statement, parameters), DEFAULT_BUDGET)
