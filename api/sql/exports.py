"""Ограниченные выборки для CSV без полной пересборки проекций."""
from __future__ import annotations


PUBLICATIONS = """
SELECT latest.platform::text AS platform,institution.canonical_name AS institution,
       publication.id AS publication_id,publication.published_at,latest.observed_at,
       latest.views_count,latest.reactions_count,latest.comments_count,latest.shares_count,
       latest.quality::text AS quality
  FROM analytics.publication_latest latest
  JOIN ingest.visible_publication publication ON publication.id=latest.publication_id
  JOIN catalog.visible_institution institution ON institution.id=latest.institution_id
 WHERE (%(platform)s='all' OR latest.platform::text=%(platform)s)
   AND publication.published_at<=%(as_of)s::timestamptz
   AND publication.created_at<=%(as_of)s::timestamptz
   AND latest.observed_at<=%(as_of)s::timestamptz
 ORDER BY publication.published_at,publication.id
 LIMIT 100001
"""


LEGACY_STATUS = """
SELECT CASE
         WHEN EXISTS(SELECT 1 FROM ingest.visible_publication)
           THEN 'LEXEMES_MISSING'
         ELSE NULL
       END AS blocked_reason
"""
