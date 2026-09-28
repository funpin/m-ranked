"""Публичный анализ аномалий v2 и две append-only команды прежней модели."""
from __future__ import annotations


RESOLVE = """
SELECT publication.id
  FROM ingest.publication publication
 WHERE publication.id=%(entity_uuid)s::uuid
UNION ALL
SELECT alias.target_uuid
  FROM catalog.legacy_entity_alias alias
 WHERE %(entity_uuid)s::uuid IS NULL AND alias.entity_type=%(legacy_type)s
   AND alias.legacy_id=%(legacy_id)s
LIMIT 1
"""

# Вывод анализа v2 — одна строка на пост по первичному ключу. Остальные
# маршруты таблиц анализа не читают.
STATE = """
SELECT coalesce(recheck.effective_level, state.level) AS level,
       state.level AS original_level, recheck.reason AS recheck_reason,
       recheck.method_version AS recheck_method_version,
       recheck.evidence AS recheck_evidence,
       state.signals, state.quality, state.analyzed_at, state.lag_seconds,
       state.norm_version_id, state.detector_versions, state.review_status
  FROM analytics.post_anomaly_state state
  LEFT JOIN analytics.post_anomaly_context_recheck recheck
    ON recheck.publication_id=state.publication_id
   AND recheck.source_analyzed_at=state.analyzed_at
   AND recheck.source_level=state.level
   AND state.review_status='unreviewed'
 WHERE state.publication_id=%(publication)s
"""

# Уровни постов аккаунта для колонки в таблице публикаций: по индексу
# (аккаунт, дата публикации) и первичному ключу состояния, без признаков.
ACCOUNT_LEVELS = """
SELECT publication.id AS publication_id,
       coalesce(recheck.effective_level, state.level) AS level,
       coalesce(state.quality->'codes' ? 'no_precise_metrics', false) AS insufficient_data
  FROM ingest.publication publication
  JOIN analytics.post_anomaly_state state ON state.publication_id=publication.id
  LEFT JOIN analytics.post_anomaly_context_recheck recheck
    ON recheck.publication_id=state.publication_id
   AND recheck.source_analyzed_at=state.analyzed_at
   AND recheck.source_level=state.level
   AND state.review_status='unreviewed'
 WHERE publication.primary_account_id=%(account)s::uuid AND state.analyzed_at IS NOT NULL
 ORDER BY publication.published_at DESC, publication.id DESC
 LIMIT %(limit)s
"""

CREATE_MANUAL = """
SELECT analytics.create_manual_anomaly_signal(
  %(publication)s,%(metric)s,%(severity)s,%(explanation)s,%(start_at)s,%(end_at)s,
  %(evidence)s::jsonb,%(actor)s,%(correlation)s,%(idempotency)s,%(digest)s) AS result
"""

APPEND_REVIEW = """
SELECT analytics.append_anomaly_review(
  %(finding)s,%(decision)s,%(comment)s,%(actor)s,%(correlation)s,%(idempotency)s,%(digest)s) AS result
"""
