"""Сводка главной: суточный пересчёт за проверкой возраста и права ролей."""
from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = (ROOT / "db/migrations/0044_site_summary.sql").read_text()
REFRESH = (ROOT / "db/tools/refresh-site-summary.sql").read_text()
MAINTENANCE = (ROOT / "operations/scripts/run-maintenance.sh").read_text()


def test_the_table_holds_one_row_readable_by_the_api_and_written_by_maintenance():
    assert "CHECK (id = 1)" in MIGRATION
    assert "GRANT SELECT ON TABLE analytics.site_summary TO api_read;" in MIGRATION
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE analytics.site_summary TO maintenance;" in MIGRATION


def test_counting_happens_only_when_the_row_is_older_than_the_limit():
    # Подсчёт миллионов замеров не должен идти каждый час.
    assert "WHERE NOT EXISTS" in REFRESH and ":'max_age_hours'" in REFRESH
    assert "count(*) FROM ingest.publication_metric_snapshot" in REFRESH
    # Площадки берутся из данных, а не перечисляются.
    assert "jsonb_object_agg" in REFRESH and "'telegram'" not in REFRESH


def test_maintenance_runs_the_refresh_by_default():
    assert 'MAINTENANCE_ENABLE_SITE_SUMMARY="${MAINTENANCE_ENABLE_SITE_SUMMARY:-true}"' in MAINTENANCE
    assert "db/tools/refresh-site-summary.sql" in MAINTENANCE
