"""Хранилище v2 без базы: граница миграции 0036 и чистая логика записи."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from uuid import UUID

import pytest

from anomaly_analysis.v2.domain import DataQuality, Level, Metric, PostVerdict
from anomaly_analysis.v2.norms import DecayFit, Norm, NormCell, NormSet, Robust, norm_to_payload
from anomaly_analysis.v2.store import (
    SERIES_BATCH, PostgresAnomalyStore, SeriesTarget, StateWrite, StoredState, change_kind,
    norm_from_rows, norm_rows, series_from_rows,
)

MIGRATION = Path(__file__).resolve().parents[1] / "db/migrations/0036_anomaly_analysis_v2.sql"
NEW_TABLES = ("analytics.anomaly_norm_version", "analytics.anomaly_norm",
              "analytics.post_anomaly_state", "analytics.post_anomaly_log")
OLD_ANALYSIS_TABLES = ("anomaly_analysis_revision", "anomaly_event", "anomaly_review",
                       "anomaly_source_revision", "publication_analysis_attempt",
                       "publication_analysis_state", "publication_anomaly_finding",
                       "publication_anomaly_review")
MOMENT = datetime(2026, 3, 2, 12, tzinfo=timezone.utc)


def _statements() -> list[str]:
    code = re.sub(r"--[^\n]*", "", MIGRATION.read_text(encoding="utf-8"))
    return [" ".join(item.split()) for item in code.split(";") if item.strip()]


def test_migration_creates_objects_only_in_analytics():
    statements = _statements()
    for statement in statements:
        verb = statement.split()[0].upper()
        assert verb in {"CREATE", "COMMENT", "REVOKE", "GRANT"}, statement
        if statement.upper().startswith("CREATE TABLE"):
            assert statement.split()[2].startswith("analytics."), statement
        if statement.upper().startswith("CREATE INDEX"):
            assert re.search(r"\bON analytics\.", statement), statement
        if verb == "COMMENT":
            assert statement.startswith("COMMENT ON TABLE analytics."), statement
    created = {statement.split()[2] for statement in statements if statement.startswith("CREATE TABLE")}
    assert created == set(NEW_TABLES)
    code = " ".join(statements)
    assert "schema_contract" not in code
    for table in OLD_ANALYSIS_TABLES:
        assert f"analytics.{table}" not in code, table


def test_migration_grants_exactly_the_listed_rights():
    grants = set()
    for statement in _statements():
        match = re.fullmatch(r"GRANT (.+) ON TABLE (.+) TO (\w+)", statement)
        if match:
            privileges, tables, role = match.groups()
            for table in tables.split(","):
                for privilege in privileges.split(","):
                    grants.add((role, table.strip(), privilege.strip()))
    write = {("analytics_worker", table, privilege)
             for table in NEW_TABLES[:3] for privilege in ("SELECT", "INSERT", "UPDATE")}
    read_views = {("analytics_worker", view, "SELECT") for view in (
        "ingest.visible_publication", "ingest.publication_metric_snapshot_active",
        "ingest.account_metric_snapshot_active", "catalog.visible_platform_account")}
    assert grants == write | read_views | {
        ("analytics_worker", "analytics.post_anomaly_log", "INSERT"),
        ("api_read", "analytics.post_anomaly_state", "SELECT"),
    }


def test_change_kind_logs_only_real_changes():
    keys = frozenset({(1, "views")})
    assert change_kind(None, 0, frozenset()) is None
    assert change_kind(None, 2, keys) == "appeared"
    stored = StoredState(UUID(int=1), 2, keys, 0)
    assert change_kind(stored, 2, keys) is None
    assert change_kind(stored, 3, keys | {(6, "reactions")}) == "level_changed"
    assert change_kind(stored, 2, keys | {(6, "reactions")}) == "sign_added"
    assert change_kind(StoredState(UUID(int=1), 2, keys | {(9, "views")}, 0), 2, keys) == "sign_removed"


def test_state_write_carries_a_verdict_or_an_error():
    verdict = PostVerdict(UUID(int=1), Level.NONE, (), DataQuality(1.0), {})
    StateWrite(UUID(int=1), MOMENT, MOMENT, MOMENT, verdict=verdict)
    StateWrite(UUID(int=1), MOMENT, MOMENT, MOMENT, error_code="series_unavailable")
    with pytest.raises(ValueError):
        StateWrite(UUID(int=1), MOMENT, MOMENT, MOMENT)


def test_series_rows_drop_failed_quality_and_absent_metrics():
    rows = [{"id": UUID(int=1), "primary_account_id": UUID(int=2), "platform": "telegram",
             "published_at": MOMENT, "is_repost": False,
             "observed_at": MOMENT + timedelta(minutes=5 * index),
             "views_count": 100 + index, "views_quality": "exact",
             "reactions_count": 5, "reactions_quality": "invalid" if index == 1 else "exact",
             "comments_count": 0, "comments_quality": "exact",
             "shares_count": None, "shares_quality": "unknown"} for index in range(3)]
    series = series_from_rows(rows)
    # Репостов площадка не отдала ни в одном замере — метрики нет, а не ноль.
    assert set(series.values) == {Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS}
    assert series.values[Metric.VIEWS] == (100, 101, 102)
    assert series.values[Metric.REACTIONS] == (5, None, 5)


def test_norm_rows_round_trip():
    norm = Norm("vk", UUID(int=7), "account", 24, 0.48, {"views": DecayFit(0.4, 1.1, 2.5)}, {
        ("views", 0): NormCell("views", 0, 24, Robust(-3.1, 0.4), (0.5, 0.7, 0.8)),
        ("erv", 1): NormCell("erv", 1, 20, log_erv=Robust(-3.5, 0.3)),
    })
    rows = norm_rows(norm)
    assert {row["age_band"] for row in rows} == {None, 0, 1}
    assert norm_to_payload(norm_from_rows(rows)) == norm_to_payload(norm)


class _Connection:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, parameters):
        self.calls.append(parameters)
        return self

    def fetchall(self):
        return []


def test_series_are_read_fifty_posts_per_query_with_month_pruning():
    connection = _Connection()
    store = PostgresAnomalyStore("", connection_factory=lambda: connection)
    targets = [SeriesTarget(UUID(int=index + 1), datetime(2026, 1 + index % 3, 28, 23, tzinfo=timezone.utc))
               for index in range(120)]
    store.read_series(targets)
    assert [len(call["ids"]) for call in connection.calls] == [SERIES_BATCH, SERIES_BATCH, 20]
    assert connection.calls[0]["months"] == [datetime(2026, month, 1).date() for month in (1, 2, 3)]


def test_norm_set_rows_cover_platform_and_accounts():
    platform = Norm("vk", None, "platform", 400, 1.0, {"views": DecayFit(0.4, 1.0, 2.0)}, {})
    account = Norm("vk", UUID(int=3), "account", 30, 0.6, {"views": DecayFit(0.5, 1.2, 2.0)}, {})
    norms = NormSet(platform, {UUID(int=3): account})
    rows = [row for norm in (norms.platform, *norms.accounts.values()) for row in norm_rows(norm)]
    assert {row["account_id"] for row in rows} == {None, UUID(int=3)}
    assert norm_from_rows([row for row in rows if row["account_id"] is None]).basis == "platform"


REMOVAL = Path(__file__).resolve().parents[1] / "db/migrations/pending/0039_remove_anomaly_analysis_v1.sql"
V1_TABLES = OLD_ANALYSIS_TABLES + ("anomaly_analysis_candidate", "anomaly_command_receipt")
# Админские команды ручных пометок v1 по решению не развиваются и уходят тем же
# релизом, что применяет удаление; до тех пор это единственные вызовы v1.
V1_ADMIN_CALLS = {"api/sql/analysis.py": ("create_manual_anomaly_signal", "append_anomaly_review")}


def test_removal_of_v1_waits_outside_the_applied_migrations():
    root = REMOVAL.parents[1]
    assert not list(root.glob("0039_*.sql")), "удаление v1 не должно применяться обычным прогоном"
    text = REMOVAL.read_text(encoding="utf-8")
    assert "ПРИМЕНЯТЬ ТОЛЬКО ПОСЛЕ ПРОВЕРКИ V2 НА РЕАЛЬНЫХ ДАННЫХ" in text
    code = re.sub(r"--[^\n]*", "", text)
    assert "CASCADE" not in code.upper() and "schema_contract" not in code
    dropped = set(re.findall(r"DROP TABLE IF EXISTS (\w+\.\w+);", code))
    assert {name.split(".")[1] for name in dropped} == set(V1_TABLES)
    assert all(name.startswith(("analytics.", "ops_and_admin.")) for name in dropped)
    assert not any(table in code for table in NEW_TABLES)


def test_no_branch_code_reads_the_v1_tables():
    root = MIGRATION.parents[2]
    offenders = []
    for directory in ("api", "anomaly_analysis", "operations", "collector_target", "collector_runtime",
                      "transfer_ingest", "frontend/lib", "frontend/app", "frontend/components"):
        for path in (root / directory).rglob("*"):
            if path.suffix not in {".py", ".sh", ".ts", ".tsx", ".sql"} or "node_modules" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            offenders += [f"{path.relative_to(root)}: {table}" for table in V1_TABLES
                          if re.search(rf"\b{table}\b", text)]
    assert not offenders, offenders
    for relative, calls in V1_ADMIN_CALLS.items():
        text = (root / relative).read_text(encoding="utf-8")
        assert all(call in text for call in calls), relative
