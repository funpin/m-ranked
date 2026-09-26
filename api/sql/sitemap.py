"""Адреса для карты сайта: только то, что открывается у читателя.

Страница поста или аккаунта отвечает 404, если аккаунт скрыт, поэтому
выборка идёт по видимым аккаунтам — как в запросах самих страниц."""

# Сколько постов в одном файле карты: у поисковиков предел 50 тысяч, а
# 20 тысяч — это ~2 МБ XML, который собирается и отдаётся без спешки.
PUBLICATIONS_PER_PAGE = 20_000

SUMMARY = """
SELECT count(*)::integer AS publications
  FROM ingest.visible_publication publication
  JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
"""

# lastmod поста — последний замер: у поста с законченным сбором он больше не
# меняется, и роботу незачем открывать страницу снова. Порядок — по времени
# публикации, чтобы номер файла у поста не менялся от новых постов.
PUBLICATIONS = """
SELECT publication.id AS publication_id,
       greatest(publication.published_at, coalesce(latest.observed_at, publication.published_at)) AS last_modified
  FROM ingest.visible_publication publication
  JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
  LEFT JOIN analytics.publication_latest latest ON latest.publication_id = publication.id
 ORDER BY publication.published_at, publication.id
 OFFSET %(offset)s LIMIT %(limit)s
"""

ACCOUNTS = """
SELECT account.id AS account_id, max(latest.observed_at) AS last_modified
  FROM catalog.visible_platform_account account
  LEFT JOIN ingest.visible_publication publication ON publication.primary_account_id = account.id
  LEFT JOIN analytics.publication_latest latest ON latest.publication_id = publication.id
 GROUP BY account.id
 ORDER BY account.id
"""

INSTITUTIONS = """
SELECT alias.legacy_id
  FROM catalog.visible_institution institution
  JOIN catalog.legacy_entity_alias alias ON alias.target_uuid = institution.id AND alias.entity_type = 'institutions'
 ORDER BY alias.legacy_id
"""
