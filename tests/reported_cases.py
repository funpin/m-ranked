"""Ряды постов из разбора владельца 07.10.2026 (фикстура anomaly_reported_cases_2026_10.json).

Точка — [секунды от публикации, просмотры, реакции] и, если счётчики не
точные, ещё [качество просмотров, качество реакций, интервал неопределён].
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from uuid import UUID

from anomaly_analysis.v2.domain import Metric, PostSeries

CASES = {case["name"]: case for case in json.loads(
    (Path(__file__).parent / "fixtures/anomaly_reported_cases_2026_10.json").read_text())}


def reported(name: str, account: UUID = UUID(int=7)) -> PostSeries:
    case = CASES[name]
    meta, points = case["publication"], case["points"]
    published = datetime.fromisoformat(meta["publishedAt"])
    quality = [(row[3], row[4], row[5]) if len(row) > 3 else ("exact", "exact", False) for row in points]
    return PostSeries(UUID(meta["publicationId"]), account, meta["platform"], published, meta["repost"],
                      tuple(published + timedelta(seconds=row[0]) for row in points),
                      {Metric.VIEWS: tuple(row[1] for row in points), Metric.REACTIONS: tuple(row[2] for row in points)},
                      qualities={Metric.VIEWS: tuple(item[0] for item in quality),
                                 Metric.REACTIONS: tuple(item[1] for item in quality)},
                      interval_uncertain=tuple(item[2] for item in quality))
