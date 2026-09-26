"""Выгрузить реальные ряды публикаций в формат эталона. Только чтение.

Строка подключения берётся из ANOMALY_REFERENCE_DATABASE_URL; адресов в коде
нет. Роли нужен SELECT на `ingest.visible_publication`,
`ingest.publication_metric_snapshot_active`, `ingest.account_metric_snapshot_active`
и `catalog.visible_platform_account` — всё это уже есть у `api_read`. Сессия
открывается read-only, так что даже ошибочный запрос ничего не запишет.

    ANOMALY_REFERENCE_DATABASE_URL=... python -m anomaly_analysis.tools.export_reference \\
        --out /var/lib/m-ranked/anomaly-reference 5f0c... 8a2d...

Каждая публикация становится отдельным случаем с пустой разметкой: уровни и
паттерны оператор проставляет руками после просмотра ряда. Каталог выгрузки —
вне репозитория: это данные вузов, а репозиторий публичный.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from ..v2.store import series_from_rows
from .reference_format import case_payload, dumps

PUBLICATIONS = """
SELECT publication.id, publication.primary_account_id, account.platform::text AS platform,
       publication.published_at, publication.is_repost
  FROM ingest.visible_publication publication
  JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
 WHERE publication.id = ANY(%s)
"""

SNAPSHOTS = """
SELECT DISTINCT ON (publication_id, observed_at)
       publication_id, observed_at,
       views_count, views_quality::text AS views_quality,
       reactions_count, reactions_quality::text AS reactions_quality,
       comments_count, comments_quality::text AS comments_quality,
       shares_count, shares_quality::text AS shares_quality
  FROM ingest.publication_metric_snapshot_active
 WHERE publication_id = ANY(%s) AND NOT synthetic
 ORDER BY publication_id, observed_at, correction_sequence DESC
"""

SUBSCRIBERS = """
SELECT observed_at, subscriber_count
  FROM ingest.account_metric_snapshot_active
 WHERE platform_account_id = %s AND subscriber_count IS NOT NULL
   AND observed_at BETWEEN %s AND %s
 ORDER BY observed_at
"""


def _connect(dsn: str):
    import psycopg
    from psycopg.rows import dict_row

    connection = psycopg.connect(
        dsn, row_factory=dict_row,
        options="-c default_transaction_read_only=on -c statement_timeout=60000 -c timezone=UTC",
    )
    connection.read_only = True
    return connection


def export(connection, publication_ids: tuple[UUID, ...]) -> dict[UUID, dict[str, Any]]:
    publications = {row["id"]: row for row in
                    connection.execute(PUBLICATIONS, (list(publication_ids),)).fetchall()}
    snapshots: dict[UUID, list[dict[str, Any]]] = {}
    for row in connection.execute(SNAPSHOTS, (list(publications),)).fetchall():
        snapshots.setdefault(row["publication_id"], []).append(row)
    cases = {}
    for publication_id, publication in publications.items():
        rows = snapshots.get(publication_id)
        if not rows:
            continue
        series = series_from_rows([{**publication, **row} for row in rows])
        subscribers = tuple(
            (row["observed_at"], int(row["subscriber_count"])) for row in connection.execute(
                SUBSCRIBERS, (series.account_id, series.published_at, series.observed_at[-1])))
        cases[publication_id] = case_payload(
            f"export_{publication_id}", "export",
            "Реальный ряд, выгруженный export_reference; разметку проставляет оператор.",
            series, (), subscribers)
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Выгрузить ряды публикаций в формат эталона")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("publication_ids", nargs="+", type=UUID)
    arguments = parser.parse_args()
    dsn = os.environ.get("ANOMALY_REFERENCE_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("ANOMALY_REFERENCE_DATABASE_URL is required")
    with _connect(dsn) as connection:
        cases = export(connection, tuple(dict.fromkeys(arguments.publication_ids)))
        connection.rollback()
    arguments.out.mkdir(parents=True, exist_ok=True)
    for publication_id, payload in cases.items():
        (arguments.out / f"export_{publication_id}.json").write_text(dumps(payload), encoding="utf-8")
    missing = set(arguments.publication_ids) - set(cases)
    if missing:
        print("нет видимой публикации или замеров:", *sorted(map(str, missing)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
