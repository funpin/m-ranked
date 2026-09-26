"""Формат эталонного случая: один JSON на случай, общий для синтетики и выгрузки.

Время замера хранится возрастом поста в секундах, а метрики — столбцами: так
ряд в тридцать суток остаётся читаемым в диффе. Метрика, которой площадка не
отдаёт, в `values` отсутствует; null в столбце — значение в замере не получено.

Ожидания (`expected_*`) размечает человек; у выгрузки они null, пока оператор
не заполнит их. `expected_patterns` — паттерны, которые обязаны найтись;
остальные допустимы, если уровень в границах.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from typing import Any, Mapping
from uuid import UUID

from ..v2.domain import SIGN_PATTERNS, Level, Metric, PostSeries

FORMAT_VERSION = 1
SOURCES = frozenset({"synthetic", "owner_screenshot", "export"})


@dataclass(frozen=True, slots=True)
class ReferenceCase:
    case_id: str
    source: str
    description: str
    subject: PostSeries
    # Другие посты того же аккаунта: фон нормы и синхронных подъёмов.
    siblings: tuple[PostSeries, ...]
    subscribers: tuple[tuple[datetime, int], ...]
    expected_min_level: Level | None
    expected_max_level: Level | None
    expected_patterns: frozenset[int]


def post_payload(series: PostSeries) -> dict[str, Any]:
    return {
        "publication_id": str(series.publication_id),
        "account_id": str(series.account_id),
        "platform": series.platform,
        "published_at": series.published_at.isoformat(),
        "is_repost": series.is_repost,
        "age_seconds": [_age(series.published_at, item) for item in series.observed_at],
        "values": {metric.value: list(series.values[metric])
                   for metric in Metric if metric in series.values},
    }


def case_payload(case_id: str, source: str, description: str, subject: PostSeries,
                 siblings: tuple[PostSeries, ...] = (),
                 subscribers: tuple[tuple[datetime, int], ...] = (), *,
                 expected_min_level: int | None = None, expected_max_level: int | None = None,
                 expected_patterns: tuple[int, ...] = ()) -> dict[str, Any]:
    payload = {
        "format_version": FORMAT_VERSION,
        "case_id": case_id,
        "source": source,
        "description": description,
        "expected_min_level": expected_min_level,
        "expected_max_level": expected_max_level,
        "expected_patterns": sorted(expected_patterns),
        "subject": str(subject.publication_id),
        "subscribers": {
            "age_seconds": [_age(subject.published_at, at) for at, _ in subscribers],
            "count": [count for _, count in subscribers],
        },
        "posts": [post_payload(item) for item in (subject, *siblings)],
    }
    parse_case(payload)
    return payload


def parse_case(payload: Mapping[str, Any]) -> ReferenceCase:
    if payload.get("format_version") != FORMAT_VERSION:
        raise ValueError("unsupported reference format version")
    if payload["source"] not in SOURCES:
        raise ValueError("unknown reference source")
    posts = {item.publication_id: item for item in map(_series, payload["posts"])}
    if len(posts) != len(payload["posts"]):
        raise ValueError("duplicate publication in a reference case")
    subject = posts.pop(UUID(payload["subject"]))
    siblings = tuple(posts.values())
    if any(item.account_id != subject.account_id for item in siblings):
        raise ValueError("sibling posts must belong to the subject account")
    low, high = (None if payload[key] is None else Level(payload[key])
                 for key in ("expected_min_level", "expected_max_level"))
    if low is not None and high is not None and low > high:
        raise ValueError("expected level bounds are inverted")
    patterns = frozenset(int(item) for item in payload["expected_patterns"])
    if not patterns <= SIGN_PATTERNS:
        raise ValueError("expected_patterns contains an unknown pattern")
    ages, counts = payload["subscribers"]["age_seconds"], payload["subscribers"]["count"]
    if len(ages) != len(counts):
        raise ValueError("subscriber columns are not aligned")
    subscribers = tuple((subject.published_at + timedelta(seconds=age), int(count))
                        for age, count in zip(ages, counts))
    return ReferenceCase(payload["case_id"], payload["source"], payload["description"],
                         subject, siblings, subscribers, low, high, patterns)


def dumps(payload: Mapping[str, Any]) -> str:
    """JSON с отступами для структуры и одной строкой на столбец значений."""
    return _dump(payload, 0) + "\n"


def _dump(value: Any, depth: int) -> str:
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        pad = " " * (depth + 1)
        items = (f"{pad}{json.dumps(key, ensure_ascii=False)}: {_dump(item, depth + 1)}"
                 for key, item in value.items())
        return "{\n" + ",\n".join(items) + "\n" + " " * depth + "}"
    if isinstance(value, list) and any(isinstance(item, (Mapping, list)) for item in value):
        pad = " " * (depth + 1)
        return "[\n" + ",\n".join(pad + _dump(item, depth + 1) for item in value) + "\n" + " " * depth + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _series(payload: Mapping[str, Any]) -> PostSeries:
    published_at = datetime.fromisoformat(payload["published_at"])
    return PostSeries(
        UUID(payload["publication_id"]), UUID(payload["account_id"]), payload["platform"],
        published_at, bool(payload["is_repost"]),
        tuple(published_at + timedelta(seconds=age) for age in payload["age_seconds"]),
        {Metric(name): tuple(column) for name, column in payload["values"].items()},
    )


def _age(published_at: datetime, at: datetime) -> int:
    return round((at - published_at).total_seconds())
