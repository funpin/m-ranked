"""Аккаунтные находки по охватам: пакеты и волны просмотров, суточный ритм, много постов уровня 3.

Считаются ночным `account_tail_job` рядом с `account_findings` по тем же
правилам: окно 30 суток, пороги относительно других аккаунтов площадки без
самого аккаунта, статус 1 «необычный», 2 «устойчиво необычный» (держится в
обеих половинах окна). Это необычность относительно площадки, а не
доказательство искусственного происхождения (ADR-006): у каждого вида есть
честные альтернативы.

Аудит 01.09–07.10.2026 (research/reach-audit-2026-10): самые крупные эпизоды
месяца — по просмотрам, а все прежние находки построены на реакциях.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import quantiles
from typing import Sequence
from uuid import UUID

from .account_findings import WINDOW_DAYS, AccountFinding, _halves_by_time

REACH_KINDS = ("view_packs", "view_waves", "level3_share", "flat_daily_views")
TITLES = {
    "view_packs": "Повторяющиеся пакеты просмотров",
    "view_waves": "Волны просмотров по стене",
    "level3_share": "Много постов с признаками искусственной активности",
    "flat_daily_views": "Просмотры без суточного ритма",
}
ALTERNATIVES = {
    "view_packs": "Регулярное платное продвижение записей; встраивание на сайт или рассылка со ссылкой",
    "view_waves": "Подборка или рекомендация площадки; виджет стены на сайте",
    "level3_share": ("Сводка признаков постов, новых свидетельств не добавляет; методика может "
                     "систематически ошибаться на особом формате аккаунта"),
    "flat_daily_views": "Аудитория в нескольких часовых поясах; круглосуточный показ на экранах",
}

# Пакеты просмотров: пост с признаком 1 режима «short_views» не слабее
# выраженной аномалии (store.read_post_levels).
PACK_MIN_POSTS = 5
PACK_SHARE = 0.15
PACK_STRONG_SHARE = 0.25
# Много постов уровня 3: у большинства аккаунтов площадки таких 0 % (аудит:
# 90-й перцентиль ВК 24 %, MAX 5 %, Telegram 1,3 %).
L3_MIN_POSTS = 20
L3_SHARE = 0.15
L3_WEAK_SHARE = 0.10
L3_HALF_SHARE = 0.10
L3_MIN_PATTERNS = 2


@dataclass(frozen=True, slots=True)
class PostLevel:
    """Вывод поста окна: уровень, номера признаков уровня 3 и пакет просмотров."""

    publication_id: UUID
    account_id: UUID
    platform: str
    published_at: datetime
    level: int
    patterns: frozenset[int]
    view_pack: bool


def _window(posts: Sequence, computed_for: date) -> dict[UUID, list]:
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account: dict[UUID, list] = {}
    for post in posts:
        if start <= post.published_at.date() < computed_for:
            by_account.setdefault(post.account_id, []).append(post)
    return by_account


def _p90_without(values: dict[UUID, float], platform_of: dict[UUID, str], account: UUID) -> float:
    """90-й перцентиль меры у других аккаунтов той же площадки."""
    others = [value for other, value in values.items()
              if other != account and platform_of[other] == platform_of[account]]
    if len(others) < 2:
        return 0.0
    return quantiles(others, n=10, method="inclusive")[-1]


def view_pack_findings(posts: Sequence[PostLevel], computed_for: date) -> list[AccountFinding]:
    """Пакеты просмотров на многих постах аккаунта."""
    by_account = _window(posts, computed_for)
    start = computed_for - timedelta(days=WINDOW_DAYS)
    share = {account: sum(post.view_pack for post in items) / len(items) for account, items in by_account.items()}
    platform_of = {account: items[0].platform for account, items in by_account.items()}
    result = []
    for account, items in by_account.items():
        members = [post for post in items if post.view_pack]
        cohort = _p90_without(share, platform_of, account)
        if len(members) < PACK_MIN_POSTS or share[account] < max(PACK_SHARE, cohort):
            continue
        halves = _halves_by_time(items, start, computed_for)
        steady = share[account] >= PACK_STRONG_SHARE and all(any(post.view_pack for post in half) for half in halves)
        metrics = {"posts": len(items), "packs": len(members), "share": round(share[account], 3),
                   "cohortP90": round(cohort, 3)}
        result.append(AccountFinding(account, platform_of[account], "view_packs", 2 if steady else 1, start,
                                     computed_for, metrics, tuple(post.publication_id for post in members)))
    return result


def level3_findings(posts: Sequence[PostLevel], computed_for: date) -> list[AccountFinding]:
    """Доля постов уровня 3 выше, чем у аккаунтов площадки: сводка уже найденного."""
    by_account = _window(posts, computed_for)
    start = computed_for - timedelta(days=WINDOW_DAYS)
    share = {account: sum(post.level == 3 for post in items) / len(items) for account, items in by_account.items()}
    platform_of = {account: items[0].platform for account, items in by_account.items()}
    result = []
    for account, items in by_account.items():
        if len(items) < L3_MIN_POSTS:
            continue
        cohort = _p90_without(share, platform_of, account)
        if share[account] < max(L3_WEAK_SHARE, cohort):
            continue
        members = [post for post in items if post.level == 3]
        patterns = frozenset().union(*(post.patterns for post in members))
        halves = _halves_by_time(items, start, computed_for)
        steady = (share[account] >= max(L3_SHARE, cohort) and len(patterns) >= L3_MIN_PATTERNS
                  and all(half and sum(post.level == 3 for post in half) / len(half) >= L3_HALF_SHARE
                          for half in halves))
        metrics = {"posts": len(items), "level3": len(members), "share": round(share[account], 3),
                   "cohortP90": round(cohort, 3), "patterns": sorted(patterns)}
        result.append(AccountFinding(account, platform_of[account], "level3_share", 2 if steady else 1, start,
                                     computed_for, metrics, tuple(post.publication_id for post in members)))
    return result
