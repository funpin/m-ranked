"""Сводка главной страницы (миграция 0044): одна готовая строка."""

SUMMARY = """
SELECT institutions, accounts, accounts_by_platform, publications, snapshots, computed_at
  FROM analytics.site_summary
 WHERE id = 1
"""
