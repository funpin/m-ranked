"""Очистка старых ревизий (0042): проверка ссылок по каждой таблице и индексы."""
from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "db/migrations/0042_dataset_revision_retention.sql").read_text()
INDEXES = (ROOT / "operations/sql/storage-indexes.sql").read_text()

# Все внешние ключи на analytics.dataset_revision (сверено с базой Сервера 2).
REFERENCES = {
    "analytics.account_latest": "dataset_revision_id", "analytics.anomaly_event": "dataset_revision_id",
    "analytics.anomaly_source_revision": "dataset_revision_id", "analytics.comparison_cohort": "dataset_revision_id",
    "analytics.institution_daily_metrics": "dataset_revision_id",
    "analytics.institution_metric_aggregate": "dataset_revision_id",
    "analytics.institution_monthly_metrics": "dataset_revision_id",
    "analytics.institution_period_metrics": "dataset_revision_id",
    "analytics.legacy_overview_account": "dataset_revision_id", "analytics.legacy_overview_card": "dataset_revision_id",
    "analytics.publication_analysis_attempt": "source_dataset_revision_id",
    "analytics.publication_analysis_state": "source_dataset_revision_id",
    "analytics.publication_content": "dataset_revision_id", "analytics.publication_history": "dataset_revision_id",
    "analytics.publication_latest": "dataset_revision_id", "ops_and_admin.outbox_event": "dataset_revision_id",
    "rating.rating_run": "dataset_revision_id",
}


def test_every_referencing_table_is_checked_before_delete():
    for table, column in REFERENCES.items():
        assert f"FROM {table} x WHERE x.{column} = r.id" in MIGRATION, table


def test_every_reference_created_in_migrations_is_known():
    found = set()
    for path in sorted((ROOT / "db/migrations").glob("*.sql")):
        text = path.read_text()
        for match in re.finditer(r"ALTER TABLE (?:ONLY )?([a-z_]+\.[a-z_]+)\s+ADD CONSTRAINT [a-z_0-9]+ FOREIGN KEY \(([a-z_]+)\) REFERENCES analytics\.dataset_revision", text):
            found.add(match.group(1))
    assert found == set(REFERENCES), (sorted(found - set(REFERENCES)), sorted(set(REFERENCES) - found))


def test_latest_revision_and_bounds_are_protected():
    assert "r.id < (SELECT max(id) FROM analytics.dataset_revision)" in MIGRATION
    assert "p_older_than < interval '2 days'" in MIGRATION and "FOR UPDATE OF r SKIP LOCKED" in MIGRATION


def test_large_referencing_tables_have_revision_indexes():
    for table in ("institution_daily_metrics", "institution_monthly_metrics", "institution_period_metrics",
                  "publication_latest"):
        assert re.search(rf"CONCURRENTLY IF NOT EXISTS \w+\s+ON analytics\.{table} \(dataset_revision_id\)", INDEXES), table
