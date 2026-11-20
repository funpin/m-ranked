"""«Наш рейтинг» вузов по соцсетям: собственная открытая формула m-ranked.

Модуль считает без базы: на входе месяц площадок наших вузов по аккаунтам, на
выходе баллы и места. Спек: docs/superpowers/specs/2026-11-20-our-rating-design.md.

Балл вуза — среднее четырёх площадок (Telegram, VK, MAX, Rutube, по 25 %). Балл
площадки — среднее трёх частей от 0 до 100:

* регулярность — доля дней с публикациями среди собранных дней, 100 баллов от
  24 дней из 30 (у Rutube — от 8); объём сверх регулярности не засчитывается;
* охват — средние просмотры зрелого поста на студента, логарифмическая шкала
  между p10 и p90 площадки на сентябре–октябре 2026;
* вовлечённость — (реакции + комментарии + репосты) / просмотры, сумма к сумме,
  та же шкала.

Накрутка вычитается до расчёта: пакеты постов уровня 3 и волны просмотров,
избыток поздних реакций аккаунта с уверенно необычным хвостом (берётся большее
из двух, а не сумма) и, при ровном отклике вместе с таким хвостом, вовлечённость
не выше медианы площадки. Это статистическая необычность, а не доказательство
(ADR-006). Тот же расчёт без очистки даёт колонку «Без очистки».
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

FORMULA_KEY = "m-ranked-own-social"
PLATFORMS = ("telegram", "vk", "max", "rutube")

# Совпадает с definition строки rating.formula_definition версии 1 (миграция
# 0095); тест сверяет их. Правка порогов — новая версия, а не правка этой.
# Якоря охвата и вовлечённости — p10 и p90 площадки на сентябре–октябре 2026
# (research/our-rating-2026-11), охват — на фактического студента без минимума
# контингента (решение владельца 20.11.2026).
FORMULA_V1: dict[str, Any] = {
    "formulaKey": FORMULA_KEY,
    "version": 1,
    "timezone": "Europe/Moscow",
    "firstMonth": "2026-11",
    "weights": {"telegram": 0.25, "vk": 0.25, "max": 0.25, "rutube": 0.25},
    "activeDays": {"perDays": 30, "full": {"telegram": 24, "vk": 24, "max": 24, "rutube": 8}},
    "scale": {"kind": "log", "anchors": "p10-p90"},
    "reachPerStudent": {"telegram": {"low": 0.065, "high": 0.42}, "vk": {"low": 0.108, "high": 1.33},
                        "max": {"low": 0.038, "high": 0.27}, "rutube": {"low": 0.0014, "high": 0.14}},
    "erv": {"telegram": {"low": 0.0085, "high": 0.036}, "vk": {"low": 0.009, "high": 0.03},
            "max": {"low": 0.012, "high": 0.05}, "rutube": {"low": 0.0015, "high": 0.038}},
    "minPosts": {"telegram": 8, "vk": 8, "max": 8, "rutube": 4},
    "minCoverageDays": 14,
    "partialBelow": 0.9,
    "minPlatforms": 3,
    "matureAfterDays": 3,
    "closeAfterDay": 7,
    "rutubeBy": "uploaded",
    "packs": {"level": 3, "minStrength": 0.7, "perPost": "largest_episode_per_metric",
              "excludedKinds": ["gap", "write_off"], "views": "max(pack, discounted_views)"},
    "lateExcess": {"tailStatus": 2, "minProfiles": 10, "majority": 0.5, "expectedTail": "cohort_median",
                   "combine": "max(packs, late)"},
    "evenResponse": {"maxEvenness": {"telegram": 0.1, "vk": 0.25, "max": 0.1}, "minMedianReactions": 30,
                     "minResiduals": 10, "needsLateExcess": True, "cap": "platform_median_erv"},
}

FORMULA_CURRENT = FORMULA_V1


@dataclass(frozen=True)
class AccountMonth:
    """Аккаунт вуза за окно месяца. Rutube — видео по дате загрузки.

    viewed_posts/views/interactions/pack_* — по зрелым постам (если они есть;
    иначе по всем — начало месяца), как в прогнозе М-Рейтинга.
    """
    platform: str
    covered_days: float
    posts: int
    active_days: int
    viewed_posts: int
    views: int
    interactions: int
    pack_views: int = 0
    pack_reactions: int = 0
    # Хвост: доля избыточных поздних реакций, если профиль уверенно необычен
    # большую часть месяца; None — правило не выполнено.
    late_share: float | None = None
    # Ровный отклик внутри дня публикации (разброс сверх пуассоновского).
    evenness: float | None = None
    median_reactions: float | None = None
    residuals: int = 0


@dataclass(frozen=True)
class InstitutionMonth:
    institution_id: str
    name: str
    students: int | None
    accounts: tuple[AccountMonth, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PlatformMonth:
    """Площадка вуза: сумма аккаунтов; покрытие — по худшему аккаунту."""
    covered_days: float
    posts: int
    active_days: int
    viewed_posts: int
    views: int
    interactions: int
    pack_views: int
    pack_reactions: int
    late_reactions: int
    even: bool


def even_account(account: AccountMonth, formula: Mapping[str, Any] = FORMULA_CURRENT) -> bool:
    rule = formula["evenResponse"]
    limit = rule["maxEvenness"].get(account.platform)
    return (limit is not None and account.evenness is not None and account.evenness <= limit
            and (account.median_reactions or 0) >= rule["minMedianReactions"]
            and account.residuals >= rule["minResiduals"]
            and (account.late_share is not None or not rule["needsLateExcess"]))


def combine(accounts: Iterable[AccountMonth], formula: Mapping[str, Any] = FORMULA_CURRENT) -> PlatformMonth:
    items = list(accounts)
    return PlatformMonth(
        covered_days=min(item.covered_days for item in items),
        posts=sum(item.posts for item in items),
        # Дни площадки: у вуза почти всегда один аккаунт; при двух — больший,
        # чтобы второй канал не удваивал регулярность.
        active_days=max(item.active_days for item in items),
        viewed_posts=sum(item.viewed_posts for item in items),
        views=sum(item.views for item in items),
        interactions=sum(item.interactions for item in items),
        pack_views=sum(min(item.pack_views, item.views) for item in items),
        pack_reactions=sum(min(item.pack_reactions, item.interactions) for item in items),
        late_reactions=sum(int(round((item.late_share or 0.0) * item.interactions)) for item in items),
        even=any(even_account(item, formula) for item in items))


def log_subscore(value: float | None, low: float, high: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(100.0, max(0.0, 100.0 * math.log(value / low) / math.log(high / low)))


def removed_interactions(month: PlatformMonth) -> int:
    """Вычитается большее из пакетов на постах и избытка хвоста — не сумма."""
    return min(month.interactions, max(month.pack_reactions, month.late_reactions))


def clean_erv(month: PlatformMonth) -> float | None:
    views = month.views - month.pack_views
    return (month.interactions - removed_interactions(month)) / views if views > 0 else None


@dataclass(frozen=True)
class PlatformScore:
    score: float | None
    source: str
    subscores: dict[str, float]
    metrics: dict[str, Any]


def platform_score(platform: str, month: PlatformMonth | None, students: int | None, elapsed_days: float,
                   days_in_month: int, *, clean: bool = True, erv_cap: float | None = None,
                   formula: Mapping[str, Any] = FORMULA_CURRENT) -> PlatformScore:
    """Балл площадки. clean=False — тот же расчёт без вычета накрутки."""
    if month is None:
        return PlatformScore(0.0, "no_account", {}, {})
    needed = min(formula["minCoverageDays"], formula["partialBelow"] * elapsed_days)
    if month.covered_days < needed:
        return PlatformScore(None, "no_data", {}, {"coveredDays": round(month.covered_days, 1)})
    partial = month.covered_days < formula["partialBelow"] * elapsed_days
    views = month.views - (month.pack_views if clean else 0)
    interactions = month.interactions - (removed_interactions(month) if clean else 0)
    average = views / month.viewed_posts if month.viewed_posts else None
    reach = average / students if average is not None and students else None
    erv = interactions / views if views > 0 else None
    capped = False
    if clean and month.even and erv_cap is not None and erv is not None and erv > erv_cap:
        erv, capped = erv_cap, True
    metrics = {"posts": month.posts, "activeDays": month.active_days, "coveredDays": round(month.covered_days, 1),
               "avgViews": round(average, 1) if average is not None else None, "students": students,
               "reach": round(reach, 5) if reach is not None else None, "erv": round(erv, 5) if erv is not None else None,
               "removedViews": month.pack_views if clean else 0,
               "removedInteractions": removed_interactions(month) if clean else 0,
               "evenCapped": capped}
    source = "partial" if partial else "formula"
    if month.posts == 0:
        return PlatformScore(0.0, "no_posts" if not partial else "partial",
                             {"activity": 0.0, "reach": 0.0, "engagement": 0.0}, metrics)
    full_days = formula["activeDays"]["full"][platform] / formula["activeDays"]["perDays"]
    share = min(1.0, month.active_days / month.covered_days) if month.covered_days > 0 else 0.0
    activity = 100.0 * min(1.0, share / full_days)
    reach_score = log_subscore(reach, **formula["reachPerStudent"][platform])
    engagement = log_subscore(erv, **formula["erv"][platform])
    # Малая выборка: охват и вовлечённость пропорционально числу постов, порог —
    # на долю месяца, которую площадку собирали.
    needed_posts = formula["minPosts"][platform] * min(1.0, month.covered_days / days_in_month)
    weight = min(1.0, month.posts / needed_posts) if needed_posts > 0 else 1.0
    subscores = {"activity": activity, "reach": reach_score * weight, "engagement": engagement * weight}
    return PlatformScore(sum(subscores.values()) / 3, source, subscores, metrics)


def median_clean_erv(months: Iterable[tuple[PlatformMonth, float]], formula: Mapping[str, Any] = FORMULA_CURRENT) -> float | None:
    """Медиана очищенного ERV площадки среди площадок с полным покрытием и постами."""
    values = [erv for month, elapsed in months
              if month.posts > 0 and month.covered_days >= formula["partialBelow"] * elapsed
              and (erv := clean_erv(month)) is not None]
    return statistics.median(values) if values else None


def rank(scores: Mapping[str, float], names: Mapping[str, str]) -> dict[str, int]:
    order = sorted(scores, key=lambda key: (-scores[key], names.get(key, "").casefold(), key))
    return {key: index for index, key in enumerate(order, 1)}


def compute(institutions: Iterable[InstitutionMonth], *, elapsed_days: float, days_in_month: int,
            formula: Mapping[str, Any] = FORMULA_CURRENT) -> list[dict[str, Any]]:
    """Баллы и места месяца. Вуз с данными меньше чем по minPlatforms площадкам не ранжируется."""
    items = list(institutions)
    months: dict[str, dict[str, PlatformMonth]] = {}
    for institution in items:
        grouped: dict[str, list[AccountMonth]] = {}
        for account in institution.accounts:
            grouped.setdefault(account.platform, []).append(account)
        months[institution.institution_id] = {platform: combine(accounts, formula)
                                              for platform, accounts in grouped.items() if platform in PLATFORMS}
    caps = {platform: median_clean_erv(((value[platform], elapsed_days) for value in months.values()
                                        if platform in value), formula) for platform in PLATFORMS}
    weights = formula["weights"]
    computed: dict[str, dict[str, Any]] = {}
    for institution in items:
        platforms, raw = {}, {}
        for platform in PLATFORMS:
            month = months[institution.institution_id].get(platform)
            platforms[platform] = platform_score(platform, month, institution.students, elapsed_days, days_in_month,
                                                 erv_cap=caps[platform], formula=formula)
            raw[platform] = platform_score(platform, month, institution.students, elapsed_days, days_in_month,
                                           clean=False, formula=formula)
        present = [platform for platform in PLATFORMS if platforms[platform].score is not None]
        if len(present) < formula["minPlatforms"]:
            continue
        total = sum(weights[platform] * platforms[platform].score for platform in present) / sum(
            weights[platform] for platform in present)
        raw_total = sum(weights[platform] * raw[platform].score for platform in present) / sum(
            weights[platform] for platform in present)
        computed[institution.institution_id] = {"institution": institution, "platforms": platforms, "raw": raw,
                                                "score": total, "rawScore": raw_total, "present": present}
    names = {key: value["institution"].name for key, value in computed.items()}
    ranks = rank({key: value["score"] for key, value in computed.items()}, names)
    raw_ranks = rank({key: value["rawScore"] for key, value in computed.items()}, names)
    rows = []
    for key, value in computed.items():
        platforms = value["platforms"]
        partial = len(value["present"]) < len(PLATFORMS) or any(
            platforms[platform].source == "partial" for platform in value["present"])
        rows.append({
            "institutionId": key, "score": round(value["score"], 2), "rank": ranks[key],
            "explanation": {
                "partial": partial, "rawScore": round(value["rawScore"], 2), "rawRank": raw_ranks[key],
                "platforms": {platform: {
                    "source": item.source,
                    "score": None if item.score is None else round(item.score, 2),
                    "rawScore": None if value["raw"][platform].score is None else round(value["raw"][platform].score, 2),
                    "subscores": {name: round(number, 2) for name, number in item.subscores.items()},
                    "metrics": item.metrics,
                } for platform, item in platforms.items()},
            },
        })
    return sorted(rows, key=lambda row: row["rank"])
