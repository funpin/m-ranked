"""М-Рейтинг без накрутки: тот же балл соцсетей, но без замеренной накрутки.

Основа — формула прогноза (api.rating_forecast, версия 2). Для VK и MAX из
месяца вуза вычитаются:

* пакеты по постам — у поста уровня 3 крупнейший эпизод каждой метрики из
  сигналов силы не ниже 0.7 (просмотры и реакции отдельно, один эпизод на
  метрику, без двойного счёта), а по просмотрам ещё и волны по стене и всплески
  без отклика (``discounted_views``), если они больше;
* «умная» накрутка аккаунта — ровный отклик вместе с длинным хвостом: посты
  одного дня получают почти одинаковое число реакций (разброс сверх случайного
  не выше порога площадки) и старые посты добирают реакции на просмотр выше
  90-го перцентиля площадки. Вычитаются только поздние реакции сверх ожидаемых
  при медианном хвосте площадки; ровность сама по себе размера не имеет.

Сдвиг балла площадки — разница формулы на месяце как есть и без накрутки; её
вычитают из основы: официального балла опубликованного месяца или прогноза
неопубликованного. Места — среди всех вузов официального рейтинга, баллы прочих
не меняются. Это статистическая оценка, а не доказательство (ADR-006).
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from . import rating_forecast as rf

CLEAN_KEY = "m-rating-social-clean"

# Совпадает с definition строки rating.formula_definition (миграция 0094); тест
# сверяет их. Правка порогов — новая версия, а не правка этой.
FORMULA_CLEAN_V1: dict[str, Any] = {
    "formulaKey": CLEAN_KEY,
    "version": 1,
    "timezone": "Europe/Moscow",
    "base": {"formulaKey": rf.FORMULA_KEY, "version": 2},
    "platforms": ["max", "vk"],
    "packs": {"level": 3, "minStrength": 0.7, "perPost": "largest_episode_per_metric",
              "excludedKinds": ["gap", "write_off"], "views": "max(pack, discounted_views)"},
    "smart": {"minMedianReactions": 30, "minResiduals": 10, "maxEvenness": {"max": 0.10, "vk": 0.25},
              "tailAbove": "cohort_p90", "expectedTail": "cohort_median"},
}

FORMULA_CLEAN_CURRENT = FORMULA_CLEAN_V1


@dataclass(frozen=True)
class Smart:
    """Признаки «умной» накрутки аккаунтов вуза на площадке за месяц."""
    evenness: float | None
    median_reactions: float | None
    tail_ratio: float | None
    tail_p90: float | None
    reactions: int  # лишние поздние реакции, уже в масштабе месяца


@dataclass(frozen=True)
class Inflation:
    views: int = 0
    reactions: int = 0
    smart: Smart | None = None

    @property
    def smart_reactions(self) -> int:
        return self.smart.reactions if self.smart is not None else 0


def smart_account(row: Mapping[str, Any], platform: str, interactions: int,
                  formula: Mapping[str, Any] = FORMULA_CLEAN_CURRENT) -> Smart | None:
    """Аккаунт с ровным откликом и длинным хвостом; None — признаков нет."""
    rule = formula["smart"]
    evenness, median = row.get("evenness"), row.get("median_reactions")
    ratio, p90 = row.get("tail_ratio"), row.get("tail_p90")
    if (evenness is None or median is None or ratio is None or p90 is None
            or (row.get("residuals") or 0) < rule["minResiduals"] or median < rule["minMedianReactions"]
            or evenness > rule["maxEvenness"][platform] or ratio < p90):
        return None
    late, early = row.get("late_reactions") or 0, row.get("early_reactions") or 0
    expected = (row.get("late_views") or 0) * (row.get("early_rate") or 0) * (row.get("tail_median") or 0)
    share = max(0.0, late - expected) / (late + early) if late + early > 0 else 0.0
    return Smart(evenness=float(evenness), median_reactions=float(median), tail_ratio=float(ratio),
                 tail_p90=float(p90), reactions=int(round(share * interactions)))


def cleaned(month: rf.PlatformMonth, inflation: Inflation) -> rf.PlatformMonth:
    removed = min(month.interactions, inflation.reactions + inflation.smart_reactions)
    return replace(month, views=max(0, month.views - inflation.views), interactions=month.interactions - removed)


def _clip(value: float) -> float:
    return min(100.0, max(0.0, value))


def clean_month(institutions: Iterable[rf.InstitutionMonth], inflation: Mapping[tuple[str, str], Inflation],
                basis: Mapping[str, Mapping[str, float | None]], names: Mapping[str, str], *, basis_kind: str,
                scale: float = 1.0, formula: Mapping[str, Any] = rf.FORMULA_V2) -> list[dict[str, Any]]:
    """Баллы и места без накрутки.

    basis — баллы месяца всех вузов рейтинга (официальные или прогноз) по
    категориям; наши вузы получают основу минус сдвиг формулы.
    """
    weights = formula["weights"]
    shifted: dict[str, dict[str, float]] = {}
    details: dict[str, dict[str, Any]] = {}
    for institution in institutions:
        base = basis.get(institution.code)
        if not base or base.get("social") is None:
            continue
        platforms: dict[str, Any] = {}
        deltas = {platform: 0.0 for platform in rf.PLATFORMS}
        for platform in ("max", "vk"):
            month = institution.platforms.get(platform)
            item = inflation.get((institution.code, platform), Inflation())
            if month is None or not month.covered or base.get(platform) is None:
                continue
            raw = rf.platform_score(platform, month, institution.students, None, scale=scale, formula=formula)
            clean = rf.platform_score(platform, cleaned(month, item), institution.students, None,
                                      scale=scale, formula=formula)
            deltas[platform] = raw.score - clean.score
            platforms[platform] = {
                "views": month.views, "interactions": month.interactions,
                "removedViews": min(month.views, item.views),
                "removedReactions": min(month.interactions, item.reactions),
                "smartReactions": min(month.interactions - min(month.interactions, item.reactions), item.smart_reactions),
                "rawScore": round(raw.score, 2), "cleanScore": round(clean.score, 2),
                "smart": None if item.smart is None else {
                    "evenness": round(item.smart.evenness, 3), "medianReactions": item.smart.median_reactions,
                    "tailRatio": round(item.smart.tail_ratio, 3), "tailP90": round(item.smart.tail_p90, 3)},
            }
        scores = {platform: _clip(base[platform] - deltas[platform]) if base.get(platform) is not None else None
                  for platform in rf.PLATFORMS}
        scores["social"] = base["social"] - sum(weights[platform] * deltas[platform] for platform in rf.PLATFORMS)
        shifted[institution.code] = scores
        details[institution.code] = {"institutionId": institution.institution_id, "platforms": platforms}
    rows: dict[str, dict[str, Any]] = {code: {"categories": {}} for code in shifted}
    for category in rf.CATEGORIES:
        pool = {code: float(value[category]) for code, value in basis.items() if value.get(category) is not None}
        base_ranks = rf.rank_in_pool(pool, names)
        clean_pool = dict(pool)
        clean_pool.update({code: value[category] for code, value in shifted.items() if value[category] is not None})
        clean_ranks = rf.rank_in_pool(clean_pool, names)
        for code, value in shifted.items():
            if value[category] is None:
                continue
            rows[code]["categories"][category] = {
                "score": round(value[category], 2), "rank": clean_ranks[code],
                "baseScore": round(pool[code], 2), "baseRank": base_ranks[code]}
    result = []
    for code, row in rows.items():
        social = row["categories"]["social"]
        result.append({"institutionId": details[code]["institutionId"], "score": social["score"], "rank": social["rank"],
                       "explanation": {"code": code, "basis": basis_kind, "categories": row["categories"],
                                       "platforms": details[code]["platforms"]}})
    return sorted(result, key=lambda item: (item["rank"], item["explanation"]["code"]))


def forecast_basis(results: Iterable[Mapping[str, Any]], base: rf.BaseMonth) -> dict[str, dict[str, float | None]]:
    """Основа неопубликованного месяца: прогноз наших вузов и прошлый балл прочих."""
    basis: dict[str, dict[str, float | None]] = {code: {category: value.get(category) for category in rf.CATEGORIES}
                                                  for code, value in base.scores.items()}
    for row in results:
        explanation = row["explanation"]
        basis[explanation["code"]] = {category: explanation["categories"][category]["score"]
                                      for category in rf.CATEGORIES}
    return basis


def finite(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None
