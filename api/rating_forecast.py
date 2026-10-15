"""Прогноз места вуза в официальном М-Рейтинге по соцсетям.

Модуль считает без базы: на входе метрики площадок наших вузов за месяц и
баллы последнего опубликованного месяца, на выходе — баллы и места.
Формула подобрана 15.10.2026 на сентябре (спек
docs/superpowers/specs/2026-10-16-rating-forecast-design.md): балл площадки —
среднее трёх лог-шкал, соцсети — взвешенная сумма баллов площадок. Места
считаются по сумме баллов, а не по местам на площадках: поэтому ровно сильный
вуз бывает в топ-10 соцсетей, не входя в топ-10 ни одной площадки (СКФУ в
сентябре — 8-й при 27/38/13).
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

FORMULA_KEY = "m-rating-social-forecast"
PLATFORMS = ("max", "vk", "rutube")
CATEGORIES = ("social", "max", "vk", "rutube")

# Совпадает с definition строки rating.formula_definition версии 1 (миграция
# 0084); тест сверяет их. Правка порогов — новая версия, а не правка этой.
FORMULA_V1: dict[str, Any] = {
    "formulaKey": FORMULA_KEY,
    "version": 1,
    "timezone": "Europe/Moscow",
    "weights": {"max": 0.4, "vk": 0.3, "rutube": 0.3},
    "posts": {"low": 20, "high": 100},
    "viewsPerStudent": {"vk": {"low": 0.1, "high": 3}, "max": {"low": 0.03, "high": 0.5}},
    "erv": {"vk": {"low": 0.005, "high": 0.04}, "max": {"low": 0.005, "high": 0.10}},
    "rutube": {"minVideos": 5, "logCoefficient": 12, "officialBlend": 0.5},
    "matureAfterDays": 3,
    "earlyBeforeDay": 7,
    "defaultErrors": {"social": 7, "max": 10, "vk": 9, "rutube": 8},
}


@dataclass(frozen=True)
class PlatformMonth:
    """Площадка вуза за месяц: сумма по всем его аккаунтам на ней."""
    posts: int
    viewed_posts: int
    views: int
    interactions: int
    covered: bool


@dataclass(frozen=True)
class InstitutionMonth:
    institution_id: str
    code: str
    name: str
    students: int | None
    platforms: Mapping[str, PlatformMonth]


@dataclass(frozen=True)
class BaseMonth:
    """Последний опубликованный месяц: баллы всех вузов официального рейтинга."""
    period: str
    scores: Mapping[str, Mapping[str, float | None]]
    names: Mapping[str, str]


@dataclass(frozen=True)
class PlatformScore:
    score: float
    source: str
    subscores: dict[str, float]
    metrics: dict[str, Any]


def subscore(value: float | None, low: float, high: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(100.0, max(0.0, 100.0 * math.log(value / low) / math.log(high / low)))


def platform_score(platform: str, month: PlatformMonth | None, students: int | None,
                   official: float | None, *, scale: float = 1.0,
                   formula: Mapping[str, Any] = FORMULA_V1) -> PlatformScore:
    if month is None:
        return PlatformScore(0.0, "no_account", {}, {})
    if not month.covered:
        # Истории за месяц у нас нет целиком — берём официальный балл
        # базового месяца, а не ноль (Нижневартовский ГУ, август 2026).
        return PlatformScore(float(official or 0.0), "fallback", {}, {"posts": month.posts})
    posts = month.posts * scale
    average = month.views / month.viewed_posts if month.viewed_posts else None
    erv = month.interactions / month.views if month.views else None
    metrics = {"posts": month.posts, "postsExtrapolated": round(posts, 1),
               "avgViews": round(average, 1) if average is not None else None,
               "students": students, "erv": round(erv, 5) if erv is not None else None}
    if platform == "rutube":
        rule = formula["rutube"]
        if posts < rule["minVideos"]:
            return PlatformScore(0.0, "formula", {"videos": 0.0}, metrics)
        own = min(100.0, rule["logCoefficient"] * math.log(posts))
        blend = rule["officialBlend"]
        score = blend * own + (1 - blend) * official if official is not None and official > 0 else own
        return PlatformScore(score, "formula", {"videos": own}, metrics)
    views_rule, erv_rule = formula["viewsPerStudent"][platform], formula["erv"][platform]
    per_student = average / students if average is not None and students else None
    subscores = {"posts": subscore(posts, formula["posts"]["low"], formula["posts"]["high"]),
                 "views": subscore(per_student, views_rule["low"], views_rule["high"]),
                 "erv": subscore(erv, erv_rule["low"], erv_rule["high"])}
    return PlatformScore(sum(subscores.values()) / 3, "formula", subscores, metrics)


def rank_in_pool(pool: Mapping[str, float], names: Mapping[str, str]) -> dict[str, int]:
    order = sorted(pool, key=lambda code: (-pool[code], names.get(code, "").casefold()))
    return {code: index for index, code in enumerate(order, 1)}


def rank_range(code: str, score: float, error: float, pool: Mapping[str, float]) -> tuple[int, int]:
    """Места при балле ± типичная ошибка, баллы прочих неизменны."""
    others = [value for other, value in pool.items() if other != code]
    high, low = min(100.0, score + error), max(0.0, score - error)
    return 1 + sum(value > high for value in others), 1 + sum(value >= low for value in others)


def forecast(institutions: Iterable[InstitutionMonth], base: BaseMonth, errors: Mapping[str, float], *,
             scale: float = 1.0, formula: Mapping[str, Any] = FORMULA_V1) -> list[dict[str, Any]]:
    weights = formula["weights"]
    computed = []
    for institution in institutions:
        official = base.scores.get(institution.code, {})
        platforms = {platform: platform_score(platform, institution.platforms.get(platform),
                                              institution.students, official.get(platform),
                                              scale=scale, formula=formula)
                     for platform in PLATFORMS}
        scores = {platform: platforms[platform].score for platform in PLATFORMS}
        scores["social"] = sum(weights[platform] * scores[platform] for platform in PLATFORMS)
        computed.append((institution, platforms, scores))
    ours = {institution.code for institution, _, _ in computed}
    # Официальные названия первыми: так равные баллы упорядочены как в источнике.
    names = {**{institution.code: institution.name for institution, _, _ in computed}, **base.names}
    pools: dict[str, dict[str, float]] = {}
    ranks: dict[str, dict[str, int]] = {}
    base_ranks: dict[str, dict[str, int]] = {}
    for category in (*CATEGORIES, "consolidated"):
        official_pool = {code: float(value[category]) for code, value in base.scores.items()
                         if value.get(category) is not None}
        base_ranks[category] = rank_in_pool(official_pool, base.names)
        if category == "consolidated":
            continue
        pool = {code: score for code, score in official_pool.items() if code not in ours}
        pool.update({institution.code: scores[category] for institution, _, scores in computed})
        pools[category], ranks[category] = pool, rank_in_pool(pool, names)
    rows = []
    for institution, platforms, scores in computed:
        categories = {}
        for category in CATEGORIES:
            best, worst = rank_range(institution.code, scores[category], errors[category], pools[category])
            if category == "social":
                source = "partial" if any(item.source == "fallback" for item in platforms.values()) else "formula"
            else:
                source = platforms[category].source
            categories[category] = {"score": round(scores[category], 2), "rank": ranks[category][institution.code],
                                    "rankBest": best, "rankWorst": worst,
                                    "baseRank": base_ranks[category].get(institution.code), "source": source}
        rows.append({
            "institutionId": institution.institution_id,
            "score": categories["social"]["score"], "rank": categories["social"]["rank"],
            "explanation": {
                "code": institution.code,
                "baseConsolidatedRank": base_ranks["consolidated"].get(institution.code),
                "categories": categories,
                "platforms": {platform: {"source": item.source,
                                         "subscores": {key: round(value, 2) for key, value in item.subscores.items()},
                                         "metrics": item.metrics}
                              for platform, item in platforms.items()},
            },
        })
    return rows


def typical_errors(predicted: Mapping[str, Mapping[str, float]],
                   actual: Mapping[str, Mapping[str, float | None]],
                   fallback: Mapping[str, float]) -> dict[str, float]:
    """MAE балла по категории; меньше 20 пар — значение по умолчанию."""
    result: dict[str, float] = {}
    for category in CATEGORIES:
        pairs = [(scores[category], actual[key][category]) for key, scores in predicted.items()
                 if category in scores and actual.get(key, {}).get(category) is not None]
        result[category] = (round(sum(abs(left - right) for left, right in pairs) / len(pairs), 2)
                            if len(pairs) >= 20 else fallback[category])
    return result


def _spearman(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = list(left)
    order_left = {key: index for index, key in enumerate(sorted(keys, key=lambda key: left[key]))}
    order_right = {key: index for index, key in enumerate(sorted(keys, key=lambda key: right[key]))}
    count = len(keys)
    if count < 2:
        return float("nan")
    squared = sum((order_left[key] - order_right[key]) ** 2 for key in keys)
    return 1 - 6 * squared / (count * (count * count - 1))


def evaluate(predicted: Mapping[str, float], actual: Mapping[str, float],
             predicted_ranks: Mapping[str, int], actual_ranks: Mapping[str, int]) -> dict[str, float]:
    """Метрики бэктеста по общим ключам: ошибка балла, ошибка места, ρ, топ-20."""
    keys = [key for key in predicted if key in actual and key in predicted_ranks and key in actual_ranks]
    rank_errors = sorted(abs(predicted_ranks[key] - actual_ranks[key]) for key in keys)
    top_actual = {key for key in keys if actual_ranks[key] <= 20}
    top_predicted = {key for key in keys if predicted_ranks[key] <= 20}
    return {
        "mae": round(statistics.fmean(abs(predicted[key] - actual[key]) for key in keys), 2),
        "rankMedian": statistics.median(rank_errors),
        "rankP80": rank_errors[int(0.8 * len(rank_errors))] if rank_errors else 0,
        "spearman": round(_spearman({key: predicted[key] for key in keys}, {key: actual[key] for key in keys}), 3),
        "top20Hits": len(top_actual & top_predicted), "top20Total": len(top_actual),
    }
