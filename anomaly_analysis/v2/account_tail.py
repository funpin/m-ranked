"""Поздний отклик аккаунта относительно аккаунтов той же площадки.

Для каждого аккаунта по постам, вышедшим за 4–28 суток до расчёта, считается
отношение поздней вовлечённости к ранней на одних и тех же постах:

    K = ((ΣΔR₄₋₁₄ + ½) / (ΣΔV₄₋₁₄ + 1)) / ((ΣR₂₄ + ½) / (ΣV₂₄ + 1))

— доля реакций на просмотры, пришедшие к постам в возрасте 4–14 суток, к той
же доле в первые сутки. Внимание стареет: поздние зрители реагируют реже
ранних (Vassio et al., 2022), и у большинства аккаунтов K заметно меньше
единицы. Отношение не опирается на историю аккаунта, поэтому постоянный
отклик на старые посты не поглощается собственной «нормой» — именно так
терялся повторяющийся хвост (research/smart-engagement-2026-09, MAX_TAIL §4).

Порог задают другие аккаунты площадки, без самого аккаунта: K не ниже их
90-го перцентиля и не меньше трёх их медиан. Медиана и перцентиль устойчивы,
пока загрязнена меньшая часть площадки. Устойчивый статус требует, чтобы
отклонение держалось и на более ранних, и на свежих постах и чтобы поздний
прирост реакций наблюдался в разные сутки как минимум двух недель: одна
сессия читателя архива даёт один день, а не две недели.

Сильного статуса нет. Так же выглядят и живые обстоятельства — увлечённая
аудитория, регулярные читатели архива, профильный чат, пересылающий старые
посты. По счётчикам они неотличимы от организованной активности
(research/smart-engagement-2026-09, GENERALIZATION H53).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

import numpy as np

from .tail_ledger import MOSCOW, TailLedger

METHOD_VERSION = "account-tail-v1"
# Посты, вышедшие за 4–28 суток до расчёта: все они ещё отслеживаются (30
# суток), поэтому их сводки свежие. Старше — пост заморожен до появления сводки.
POSTS_FROM_DAYS = 28
POSTS_UNTIL_DAYS = 4
# Граница «ранних» и «свежих» постов для проверки устойчивости: по двенадцать
# суток публикаций в каждой половине.
HALF_SPLIT_DAYS = 16
# Суточная раскладка: последние три недели — туда попадают поздние окна постов.
DAYS_WINDOW = 21

MIN_POSTS = 8
MIN_EARLY_VIEWS = 300
MIN_EARLY_REACTIONS = 10
MIN_HALF_POSTS = 4
MIN_HALF_EARLY_REACTIONS = 5
# Меньше двух десятков поздних реакций за четыре недели — несколько читателей.
MIN_LATE_REACTIONS = 20
MIN_COHORT = 15
COHORT_QUANTILE = 0.9
MEDIAN_MULTIPLE = 3.0
# Устойчивость: поздние реакции не меньше чем у двух постов в сутки — в
# четырёх и более сутках из двух разных недель.
ACTIVE_DAY_POSTS = 2
MIN_ACTIVE_DAYS = 4
MIN_ACTIVE_WEEKS = 2
WIDE_DAY_POSTS = 5
BREADTH_MIN_REACTIONS = 5

STATUS_LABELS = {0: "обычный для площадки", 1: "необычный", 2: "устойчиво необычный"}
ABSTAIN_TEXTS = {
    "few_posts": "мало постов с точными замерами в первые сутки и после четырёх суток",
    "few_early_views": "мало просмотров в первые сутки, ранняя доля реакций не определена",
    "few_early_reactions": "мало реакций в первые сутки, ранняя доля реакций не определена",
    "small_cohort": "мало аккаунтов площадки с достаточными данными для сравнения",
}


@dataclass(frozen=True, slots=True)
class PostLedger:
    publication_id: UUID
    account_id: UUID
    platform: str
    published_at: datetime
    ledger: TailLedger


@dataclass(frozen=True, slots=True)
class Totals:
    posts: int = 0
    early_views: int = 0
    early_reactions: int = 0
    late_views: int = 0
    late_reactions: int = 0

    def add(self, ledger: TailLedger) -> "Totals":
        late = ledger.late
        return Totals(self.posts + 1, self.early_views + ledger.early.views,
                      self.early_reactions + ledger.early.reactions,
                      self.late_views + late[0], self.late_reactions + late[1])

    @property
    def early_rate(self) -> float:
        return (self.early_reactions + 0.5) / (self.early_views + 1)

    @property
    def late_rate(self) -> float:
        return (self.late_reactions + 0.5) / (self.late_views + 1)

    @property
    def ratio(self) -> float:
        return self.late_rate / self.early_rate

    def payload(self) -> dict[str, Any]:
        return {"posts": self.posts, "earlyViews": self.early_views, "earlyReactions": self.early_reactions,
                "lateViews": self.late_views, "lateReactions": self.late_reactions,
                "earlyRate": round(self.early_rate, 6), "lateRate": round(self.late_rate, 6),
                # Без постов отношение сглаживания равно единице и ничего не значит.
                "ratio": round(self.ratio, 4) if self.posts else None}


@dataclass(frozen=True, slots=True)
class AccountTailProfile:
    account_id: UUID
    platform: str
    computed_for: date
    status: int | None
    abstain_reason: str | None
    metrics: Mapping[str, Any]


def window_end(computed_for: date) -> datetime:
    """Конец окна профиля — московская полночь начала `computed_for`."""
    return datetime.combine(computed_for, time(0), MOSCOW)


def profiles(posts: Iterable[PostLedger], accounts: Mapping[UUID, str],
             computed_for: date) -> list[AccountTailProfile]:
    """Профили всех `accounts` (аккаунт → площадка) на сутки `computed_for`."""
    end = window_end(computed_for)
    posts_from, posts_until = end - timedelta(days=POSTS_FROM_DAYS), end - timedelta(days=POSTS_UNTIL_DAYS)
    split = end - timedelta(days=HALF_SPLIT_DAYS)
    days = [(end - timedelta(days=DAYS_WINDOW - index)).date() for index in range(DAYS_WINDOW)]
    grouped: dict[UUID, list[PostLedger]] = {account: [] for account in accounts}
    for item in posts:
        if item.account_id in grouped and posts_from < item.published_at <= posts_until:
            grouped[item.account_id].append(item)
    measured = {account: _measure(items, split, days) for account, items in grouped.items()}
    supported: dict[str, dict[UUID, float]] = {}
    for account, platform in accounts.items():
        if measured[account]["abstain"] is None:
            supported.setdefault(platform, {})[account] = measured[account]["whole"].ratio
    result = []
    for account, platform in sorted(accounts.items(), key=lambda item: str(item[0])):
        data = measured[account]
        metrics: dict[str, Any] = {
            "methodVersion": METHOD_VERSION,
            "windowStart": days[0].isoformat(), "windowEnd": days[-1].isoformat(),
            **data["whole"].payload(),
            "halves": {"earlier": data["earlier"].payload(), "recent": data["recent"].payload()},
            "days": data["days"], "activeDays": data["active_days"], "activeWeeks": data["active_weeks"],
            "wideDays": data["wide_days"], "breadth": data["breadth"], "roundedPosts": data["rounded"],
        }
        reason = data["abstain"]
        others = {key: value for key, value in supported.get(platform, {}).items() if key != account}
        cohort = None
        if reason is None and len(others) + 1 < MIN_COHORT:
            reason = "small_cohort"
        if len(others) >= MIN_COHORT - 1:
            values = np.fromiter(others.values(), dtype=np.float64)
            median = float(np.median(values))
            quantile = float(np.quantile(values, COHORT_QUANTILE))
            cohort = {"accounts": len(others) + (reason is None), "median": round(median, 4),
                      "p90": round(quantile, 4), "threshold": round(max(quantile, MEDIAN_MULTIPLE * median), 4)}
            if reason is None:
                cohort["rank"] = round(float((values < data["whole"].ratio).mean()), 4)
        metrics["cohort"] = cohort
        status = None if reason is not None else _status(data, cohort)
        if reason is not None:
            metrics["abstainText"] = ABSTAIN_TEXTS[reason]
        result.append(AccountTailProfile(account, platform, computed_for, status, reason, metrics))
    return result


def _status(data: Mapping[str, Any], cohort: Mapping[str, Any]) -> int:
    whole: Totals = data["whole"]
    threshold, median = cohort["threshold"], cohort["median"]
    if whole.ratio < threshold or whole.late_reactions < MIN_LATE_REACTIONS:
        return 0
    halves = [data["earlier"], data["recent"]]
    persistent = (whole.ratio >= 1.0
                  and all(half.posts >= MIN_HALF_POSTS and half.early_reactions >= MIN_HALF_EARLY_REACTIONS
                          and half.ratio >= MEDIAN_MULTIPLE * median for half in halves)
                  and data["active_days"] >= MIN_ACTIVE_DAYS and data["active_weeks"] >= MIN_ACTIVE_WEEKS)
    return 2 if persistent else 1


def _measure(items: Sequence[PostLedger], split: datetime, days: Sequence[date]) -> dict[str, Any]:
    whole, earlier, recent = Totals(), Totals(), Totals()
    rounded = 0
    for item in items:
        ledger = item.ledger
        if ledger.early is None or ledger.late is None:
            continue
        whole = whole.add(ledger)
        rounded += ledger.rounded
        if item.published_at <= split:
            earlier = earlier.add(ledger)
        else:
            recent = recent.add(ledger)
    abstain = None
    if whole.posts < MIN_POSTS:
        abstain = "few_posts"
    elif whole.early_views < MIN_EARLY_VIEWS:
        abstain = "few_early_views"
    elif whole.early_reactions < MIN_EARLY_REACTIONS:
        abstain = "few_early_reactions"
    daily, active_days, weeks, wide = [], 0, set(), 0
    observed_total = expected_total = 0.0
    for day in days:
        key = day.isoformat()
        covering = [item for item in items if key in item.ledger.covered]
        grown = [item.ledger.growth[key] for item in covering if item.ledger.growth.get(key, 0) > 0]
        reactions = int(sum(grown))
        daily.append({"day": key, "observed": len(covering), "active": len(grown), "reactions": reactions})
        if len(grown) >= ACTIVE_DAY_POSTS:
            active_days += 1
            weeks.add(day.isocalendar()[:2])
        if len(covering) >= WIDE_DAY_POSTS and 2 * len(grown) >= len(covering):
            wide += 1
        if reactions >= BREADTH_MIN_REACTIONS:
            expected_total += _expected_breadth(covering, reactions)
            observed_total += len(grown)
    breadth = None if expected_total == 0 else {
        "observed": int(observed_total), "expected": round(expected_total, 2),
        "excess": round(observed_total / expected_total, 3)}
    return {"whole": whole, "earlier": earlier, "recent": recent, "abstain": abstain, "days": daily,
            "active_days": active_days, "active_weeks": len(weeks), "wide_days": wide, "breadth": breadth,
            "rounded": rounded}


def _expected_breadth(covering: Sequence[PostLedger], reactions: int) -> float:
    """E[число постов с реакциями | T реакций] при независимом распределении.

    Вес поста — его доля поздних просмотров: E[B|T,w] = Σ(1 − (1 − wᵢ)ᵀ)
    (research/smart-engagement-2026-09, MAX_TAIL §5, H22). Описание ширины, а не
    проверка: одна сессия читателя архива тоже ровно раскладывает реакции.
    """
    weights = np.array([max(1.0, float(item.ledger.late[0]) if item.ledger.late else 1.0)
                        for item in covering], dtype=np.float64)
    weights /= weights.sum()
    return float(np.sum(1 - (1 - weights) ** reactions))
