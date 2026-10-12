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
from datetime import date, datetime, timedelta, timezone
from statistics import quantiles
from typing import Any, Sequence
from uuid import UUID

from .account_findings import WINDOW_DAYS, AccountFinding, LedgerPost, _halves_by_time

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
# Волны по стене: в один час ≥ 10 постов старше суток, это последние посты
# подряд (≥ 80 % из N последних), и реакций на просмотр меньше трети позднего
# отклика аккаунта. Час, общий для половины аккаунтов площадки, — событие
# площадки (обновление счётчиков), а не аккаунта.
WAVE_MIN_POSTS = 10
WAVE_LATEST_SHARE = 0.8
WAVE_RESPONSE = 1 / 3
WAVE_PLATFORM_SHARE = 0.5
WAVE_STRONG_VIEW_SHARE = 0.2
# Суточный ритм: самое тихое окно четырёх часов к самому активному. У живой
# аудитории ночью просмотров мало (аудит: обычно ~0,2, у всех кроме одного
# аккаунта ≤ 0,37); мера не зависит от часового пояса.
FLAT_MIN_VIEWS = 20_000
FLAT_AMPLITUDE = 0.5
FLAT_COHORT_FACTOR = 1.5
FLAT_WINDOW = 4


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


def _own(posts: Sequence[LedgerPost], computed_for: date) -> dict[UUID, list[LedgerPost]]:
    return {account: [post for post in items if not post.is_repost]
            for account, items in _window(posts, computed_for).items()
            if any(not post.is_repost for post in items)}


def wave_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]:
    """Часы, когда последние посты стены разом получили просмотры почти без реакций."""
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account = _own(posts, computed_for)
    platform_of = {account: items[0].platform for account, items in by_account.items()}
    tables: dict[UUID, dict[int, list[tuple[LedgerPost, int, int]]]] = {}
    busy: dict[tuple[str, int], int] = {}
    for account, items in by_account.items():
        table: dict[int, list[tuple[LedgerPost, int, int]]] = {}
        for post in items:
            for hour, views, reactions in post.ledger.surges:
                table.setdefault(hour, []).append((post, views, reactions))
        tables[account] = table
        for hour, hits in table.items():
            if len(hits) >= WAVE_MIN_POSTS:
                busy[(platform_of[account], hour)] = busy.get((platform_of[account], hour), 0) + 1
    accounts_of: dict[str, int] = {}
    for platform in platform_of.values():
        accounts_of[platform] = accounts_of.get(platform, 0) + 1
    result = []
    for account, items in by_account.items():
        platform = platform_of[account]
        ordered = sorted(items, key=lambda post: post.published_at, reverse=True)
        late = [post.ledger.late for post in items if post.ledger.late is not None]
        late_views, late_reactions = sum(item[0] for item in late), sum(item[1] for item in late)
        late_rate = late_reactions / late_views if late_views else None
        wave_hours: list[int] = []
        members: set[UUID] = set()
        views_in = reactions_in = latest = 0
        for hour, hits in sorted(tables[account].items()):
            if len(hits) < WAVE_MIN_POSTS:
                continue
            if busy[(platform, hour)] >= max(2, WAVE_PLATFORM_SHARE * accounts_of[platform]):
                continue
            moment = datetime.fromtimestamp(hour * 3600, tz=timezone.utc)
            older = [post for post in ordered if post.published_at <= moment - timedelta(days=1)]
            hit_ids = {post.publication_id for post, _, _ in hits}
            depth = max((index for index, post in enumerate(older) if post.publication_id in hit_ids),
                        default=-1) + 1
            if depth == 0 or len(hit_ids) < WAVE_LATEST_SHARE * depth:
                continue
            hour_views = sum(views for _, views, _ in hits)
            hour_reactions = sum(reactions for _, _, reactions in hits)
            if late_rate is not None and hour_reactions > WAVE_RESPONSE * late_rate * hour_views:
                continue
            wave_hours.append(hour)
            members |= hit_ids
            views_in += hour_views
            reactions_in += hour_reactions
            latest = max(latest, depth)
        if not wave_hours:
            continue
        days = sorted({datetime.fromtimestamp(hour * 3600, tz=timezone.utc).date() for hour in wave_hours})
        weeks = {day.isocalendar()[:2] for day in days}
        total_views = sum(max(point.views for point in (post.ledger.early, post.ledger.end) if point is not None)
                          for post in items if post.ledger.early is not None or post.ledger.end is not None)
        share = views_in / total_views if total_views else 0.0
        status = 2 if len(weeks) >= 2 or share >= WAVE_STRONG_VIEW_SHARE else 1
        metrics = {"days": len(days), "hours": len(wave_hours), "views": views_in, "reactions": reactions_in,
                   "viewShare": round(share, 3), "latestN": latest, "posts": len(items)}
        result.append(AccountFinding(account, platform, "view_waves", status, start, computed_for, metrics,
                                     tuple(sorted(members, key=str))))
    return result


def _amplitude(items: Sequence[LedgerPost]) -> tuple[float, int] | None:
    """Самое тихое окно четырёх часов к самому активному и начало тихого (час UTC)."""
    views = [0] * 24
    for post in items:
        if post.ledger.hours is not None:
            for hour in range(24):
                views[hour] += post.ledger.hours[0][hour]
    if sum(views) < FLAT_MIN_VIEWS:
        return None
    windows = [sum(views[(begin + offset) % 24] for offset in range(FLAT_WINDOW)) for begin in range(24)]
    quiet = min(range(24), key=lambda begin: (windows[begin], begin))
    return windows[quiet] / max(max(windows), 1), quiet


def flat_day_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]:
    """Поздние просмотры постов идут круглые сутки, без ночного провала аудитории."""
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account = _own(posts, computed_for)
    measured = {account: _amplitude(items) for account, items in by_account.items()}
    values = {account: item[0] for account, item in measured.items() if item is not None}
    platform_of = {account: items[0].platform for account, items in by_account.items()}
    result = []
    for account, item in measured.items():
        if item is None:
            continue
        amplitude, quiet = item
        cohort = _p90_without(values, platform_of, account)
        if amplitude < max(FLAT_AMPLITUDE, FLAT_COHORT_FACTOR * cohort):
            continue
        parts = [_amplitude(half) for half in _halves_by_time(by_account[account], start, computed_for)]
        steady = all(part is not None and part[0] >= FLAT_AMPLITUDE for part in parts)
        members = []
        for post in by_account[account]:
            if post.ledger.hours is None:
                continue
            own = post.ledger.hours[0]
            windows = [sum(own[(begin + offset) % 24] for offset in range(FLAT_WINDOW)) for begin in range(24)]
            if max(windows) and 2 * windows[quiet] >= max(windows):
                members.append(post.publication_id)
        metrics = {"amplitude": round(amplitude, 3), "quietStartUtc": quiet, "cohortP90": round(cohort, 3),
                   "posts": len(by_account[account])}
        result.append(AccountFinding(account, platform_of[account], "flat_daily_views", 2 if steady else 1,
                                     start, computed_for, metrics, tuple(members)))
    return result


def _percent(value: float) -> str:
    return f"{round(100 * value)} %"


def _number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def summary(finding: AccountFinding) -> str:
    """Одна фраза с числами — для карточки аккаунта и ссылки со страницы поста."""
    data = finding.metrics
    if finding.kind == "view_packs":
        return (f"У {data['packs']} из {data['posts']} постов за {WINDOW_DAYS} дней просмотры с публикации шли "
                f"ровным темпом и обрывались при почти полном отсутствии реакций; у аккаунтов площадки такое "
                f"бывает не больше чем у {_percent(data['cohortP90'])} постов (90-й перцентиль)")
    if finding.kind == "view_waves":
        return (f"В {data['days']} дн. ({data['hours']} ч) последние {data['latestN']} постов одновременно "
                f"получали просмотры почти без реакций: +{_number(data['views'])} просмотров, "
                f"{_number(data['reactions'])} реакций; это {_percent(data['viewShare'])} просмотров постов окна")
    if finding.kind == "level3_share":
        return (f"{data['level3']} из {data['posts']} постов за {WINDOW_DAYS} дней на уровне 3 (признаки "
                f"{', '.join(map(str, data['patterns']))}); у аккаунтов площадки — не больше "
                f"{_percent(data['cohortP90'])} (90-й перцентиль). Сводка признаков постов, а не новое свидетельство")
    return (f"Самые тихие четыре часа суток дают {_percent(data['amplitude'])} притока просмотров самых активных; "
            f"у аккаунтов площадки — не больше {_percent(data['cohortP90'])}: живая аудитория ночью почти не смотрит")


def headline(finding: AccountFinding) -> str:
    """Короткая строка для свёрнутого вида."""
    data = finding.metrics
    if finding.kind == "view_packs":
        return f"Пакеты просмотров с публикации у {_percent(data['share'])} постов"
    if finding.kind == "view_waves":
        return f"Волны просмотров по последним {data['latestN']} постам"
    if finding.kind == "level3_share":
        return f"{_percent(data['share'])} постов на уровне 3"
    return "Просмотры идут круглые сутки"


def figure(finding: AccountFinding) -> dict[str, Any] | None:
    """Аккаунт против 90-го перцентиля площадки — одна мера для инфографики."""
    data = finding.metrics
    if finding.kind == "view_waves":
        return None
    labels = {"view_packs": "постов с пакетом просмотров", "level3_share": "постов на уровне 3",
              "flat_daily_views": "тихие часы к активным"}
    value = data["amplitude"] if finding.kind == "flat_daily_views" else data["share"]
    return {"value": value, "typical": data["cohortP90"], "unit": "percent", "label": labels[finding.kind],
            "direction": "higher"}
