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
from math import log1p, sqrt
from statistics import quantiles
from typing import Any, Mapping, Sequence
from uuid import UUID

from .account_findings import WINDOW_DAYS, AccountFinding, LedgerPost, _halves_by_time
from .audience_rhythm import account_rhythm, summed_views
from .detectors.view_burst_response import MIN_SURPRISE
from .tail_ledger import MOSCOW

REACH_KINDS = ("view_packs", "view_waves", "level3_share", "flat_daily_views", "promotion", "early_response",
               "reaction_view_link")
TITLES = {
    "view_packs": "Повторяющиеся пакеты просмотров",
    "view_waves": "Волны просмотров по стене",
    "level3_share": "Много постов с признаками искусственной активности",
    "flat_daily_views": "Просмотры без суточного ритма",
    "promotion": "Похоже на продвижение записей",
    "early_response": "Ранний отклик выше площадки",
    "reaction_view_link": "Просмотры растут независимо от отклика",
}
ALTERNATIVES = {
    "view_packs": "Регулярное платное продвижение записей; встраивание на сайт или рассылка со ссылкой",
    "view_waves": "Подборка или рекомендация площадки; виджет стены на сайте",
    "level3_share": ("Сводка признаков постов, новых свидетельств не добавляет; методика может "
                     "систематически ошибаться на особом формате аккаунта"),
    "flat_daily_views": "Аудитория в нескольких часовых поясах; круглосуточный показ на экранах",
    "promotion": ("Платное продвижение записи: реклама ВК засчитывает показы как просмотры; подборка "
                  "или рекомендация площадки; ссылка на запись с внешнего ресурса"),
    "reaction_view_link": ("Посты разных форматов находят разную аудиторию: новости шире, внутренние объявления уже; "
                           "платное продвижение или рекомендации отдельных записей"),
    "early_response": ("Ядро подписчиков, которое реагирует сразу: студенческие чаты, сотрудники; анонс "
                       "записи в чате или рассылке до публикации"),
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
# Волны по стене: в один час ≥ 10 постов старше суток, среди них хотя бы 30 %
# из N последних (при 80 % волны через один-два поста не считались: МИФИ 345 тыс.
# просмотров за 29 часов и МИСИС 555 тыс. за 13 в октябре на копии 07.11), и реакций на просмотр меньше трети позднего
# отклика аккаунта. Час, общий для половины аккаунтов площадки, — событие
# площадки (обновление счётчиков), а не аккаунта.
WAVE_MIN_POSTS = 10
WAVE_LATEST_SHARE = 0.3
WAVE_RESPONSE = 1 / 3
WAVE_PLATFORM_SHARE = 0.5
WAVE_STRONG_VIEW_SHARE = 0.2
# Суточный ритм: самое тихое окно четырёх часов к самому активному выше p90
# площадки и пик вне дневных часов аудитории. Одна глубина окна не годится: у
# крупных федеральных вузов и сибирских аккаунтов она выше p90 при обычном вечернем пике.
FLAT_MIN_VIEWS = 20_000
FLAT_STEADY_FACTOR = 1.0
FLAT_WINDOW = 4


# Похоже на продвижение (только ВК): сутки поста, когда просмотров во много
# раз больше, чем у постов аккаунта в те же сутки жизни, реакций на просмотр
# мало, а ночью (00–06 МСК) просмотров почти нет — показы идут по суточному
# ритму аудитории. Калибровка — пять постов МФТИ с подтверждённой рекламой
# 07.10–12.10.2026 (research/findings-2026-10-13). Ровный круглосуточный пакет
# ночную долю не проходит. Это контекст поста, а не уровень аномалии: статус
# всегда 1 (аккаунт не скрывается фильтром устойчивых находок), признаки
# поста остаются как есть.
PROMOTION_PLATFORMS = frozenset({"vk"})
# Порог ×5 на всех постах ВК 13.09–13.10.2026 (копия прода 13.10) пометил 90
# постов у 38 из 85 аккаунтов: двое суток по ×5–10 и 700–4 000 просмотров —
# обычный разброс. По силе слабые серии от настоящей рекламы не отличить: у
# двух постов МФТИ из пяти подтверждённых ×11–18 и 1,7–2,3 тыс. просмотров.
# Отличает кампания: в рекламе крутят несколько постов аккаунта в одни и те же
# сутки. Поэтому серия засчитывается, если у поста не меньше двух общих суток
# продвижения с другим постом аккаунта, или если она сама сильная: от трёх
# суток, медиана превышения от ×20 и от 5 000 просмотров. С ×10 и этими
# условиями — 24 поста у 11 аккаунтов, все пять постов МФТИ и ни одного его
# непродвигаемого соседа.
PROMOTION_EXCESS = 10.0
PROMOTION_CAMPAIGN_SHARED_DAYS = 2
PROMOTION_STRONG_DAYS = 3
PROMOTION_STRONG_EXCESS = 20.0
PROMOTION_STRONG_VIEWS = 5_000
# Отклик — по всей серии суток, а не по каждым: реакций в сутки у такого поста
# единицы, и одна случайная реакция рвала серию (МФТИ №58974: 1 реакция на
# 903 просмотра — 1,19 нормы аккаунта на 11-е сутки). У пяти постов МФТИ
# суммарный отклик серии — 0,03–0,57 нормы аккаунта того же возраста.
PROMOTION_RESPONSE = 0.6
PROMOTION_NIGHT_SHARE = 0.17
# Сводка хранит просмотры 00–06 МСК, а у восточной аудитории это утро: порог
# растёт вместе с долей этих часов у самого аккаунта против обычной (медиана ВК 0,08).
PROMOTION_MSK_NIGHT_TYPICAL = 0.08
MSK_NIGHT_UTC_HOURS = (21, 22, 23, 0, 1, 2)
# Не меньше 300 просмотров в сутки: при 100 в кандидаты шли посты БРУ
# со 100–250 просмотрами в сутки, которые владелец счёл спорными или не
# продвижением; пять постов МФТИ набирали в сутки кампании от 600.
PROMOTION_MIN_VIEWS = 300
PROMOTION_MIN_DAYS = 2
# Базовая линия суток жизни — медиана хотя бы пяти постов аккаунта.
PROMOTION_MIN_BASE_POSTS = 5
# Причины ADR-019: форма, которая одинакова у продвижения и рекомендаций. На одном посте
# они мало что значат: лесенка встречается у 10 % постов обычного вуза. Находка — только
# при охвате на подписчика выше 90 % площадки, обычном отклике и повторении на постах.
PROMOTION_LATE_SHARE = 0.05
PROMOTION_LATE_MIN_VIEWS = 2_000
PROMOTION_STAIR_DAYS = 4
PROMOTION_STAIR_MIN_VIEWS = 150
PROMOTION_STAIR_DECAY = (0.45, 0.95)
PROMOTION_STAIR_NIGHT = 0.20
PROMOTION_REASON_MIN_POSTS = 15
PROMOTION_REASON_SHARE = 0.15
PROMOTION_MAX_RESPONSE = 2.0


# Связь реакций и просмотров между постами аккаунта: корреляция логарифмов к 72 ч
# ниже 10-го перцентиля других аккаунтов площадки. Слабая находка: часть таких
# аккаунтов — смешение форматов, поэтому статус всегда 1.
LINK_PLATFORMS = frozenset({"vk"})
LINK_MIN_POSTS = 30
LINK_MIN_COHORT = 15

# Ранний отклик выше площадки (только ВК, без видео: у клипа просмотры записи
# — не аудитория): доля постов, у которых на первом точном замере (не позже
# получаса, tail_ledger.marks["first"]) реакций не меньше 40 % просмотров.
# Живой ранний отклик ВК — единицы процентов. Посты ВК 15.09–11.10.2026 (копия
# прода 12.10; 36 аккаунтов, у которых таких постов не меньше 10): у ГУАП 86 %,
# у РТУ МИРЭА 46 %, у остальных не больше 6 %, 90-й перцентиль площадки 1,5 %.
EARLY_PLATFORMS = frozenset({"vk"})
EARLY_EXCLUDED_TYPES = frozenset({"video"})
EARLY_RATIO = 0.4
EARLY_MIN_VIEWS = 20
EARLY_MIN_POSTS = 10
EARLY_SHARE = 0.15
EARLY_STRONG_SHARE = 0.25


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
    return [finding for finding, _ in account_waves(posts, computed_for)]


def view_discounts(posts: Sequence[LedgerPost],
                   waves: Sequence[tuple[AccountFinding, Mapping[UUID, int]]]) -> dict[UUID, int | None]:
    """Просмотры поста, не входящие в сумму «без волн и всплесков»; None — таких нет.

    Часы всплеска в сводке не хранятся, и он может совпасть с часом волны,
    поэтому берётся большее из двух: сумма не занижается вдвойне.
    """
    in_waves = {publication: views for _, by_post in waves for publication, views in by_post.items()}
    result: dict[UUID, int | None] = {}
    for post in posts:
        burst = post.ledger.burst
        burst_views = burst[2] if burst and burst[0] == "decoupled" and burst[3] >= MIN_SURPRISE else 0
        result[post.publication_id] = max(in_waves.get(post.publication_id, 0), burst_views) or None
    return result


def account_waves(posts: Sequence[LedgerPost],
                  computed_for: date) -> list[tuple[AccountFinding, dict[UUID, int]]]:
    """Часы, когда последние посты стены разом получили просмотры почти без реакций.

    Вместе с находкой — просмотры этих часов по постам.
    """
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
        by_post: dict[UUID, int] = {}
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
            for post, views, _ in hits:
                by_post[post.publication_id] = by_post.get(post.publication_id, 0) + views
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
                   "viewShare": round(share, 3), "latestN": latest, "posts": len(items),
                   "viewsWithoutWaves": max(0, total_views - views_in)}
        result.append((AccountFinding(account, platform, "view_waves", status, start, computed_for, metrics,
                                      tuple(sorted(members, key=str))), by_post))
    return result


def _post_day_index(post: LedgerPost, day: str) -> int:
    return (date.fromisoformat(day) - post.published_at.astimezone(MOSCOW).date()).days


def _promotion_days(items: Sequence[LedgerPost], start: date,
                    computed_for: date) -> dict[UUID, list[tuple[int, str, int, int, float, float]]]:
    """Сутки постов аккаунта, похожие на продвижение: (k, дата, просмотры, реакции, превышение,
    ожидаемые реакции при отклике аккаунта)."""
    views_by_k: dict[int, list[int]] = {}
    totals: dict[int, list[int]] = {}
    for post in items:
        for day, views, reactions, _ in post.ledger.days:
            k = _post_day_index(post, day)
            views_by_k.setdefault(k, []).append(views)
            pair = totals.setdefault(k, [0, 0])
            pair[0] += views
            pair[1] += reactions
    base = {k: sorted(values)[len(values) // 2] for k, values in views_by_k.items()
            if len(values) >= PROMOTION_MIN_BASE_POSTS}
    response = {k: pair[1] / pair[0] for k, pair in totals.items() if pair[0] > 0}
    night_limit = _promotion_night_limit(items)
    found: dict[UUID, list[tuple[int, str, int, int, float, float]]] = {}
    for post in items:
        days = []
        for day, views, reactions, night in post.ledger.days:
            k = _post_day_index(post, day)
            if (k not in base or views < PROMOTION_MIN_VIEWS or not start <= date.fromisoformat(day) < computed_for
                    or views < PROMOTION_EXCESS * max(base[k], 1) or night > night_limit * views):
                continue
            # Ожидаемые реакции на эти просмотры при отклике аккаунта того же возраста.
            days.append((k, day, views, reactions, views / max(base[k], 1), response.get(k, 0.0) * views))
        if days:
            found[post.publication_id] = days
    return found


def _promotion_night_limit(items: Sequence[LedgerPost]) -> float:
    views = summed_views(post.ledger for post in items)
    rhythm = account_rhythm(post.ledger for post in items)
    if rhythm is None or rhythm.offset_hours <= 1:
        return PROMOTION_NIGHT_SHARE
    share = sum(views[hour] for hour in MSK_NIGHT_UTC_HOURS) / sum(views)
    return PROMOTION_NIGHT_SHARE * max(1.0, share / PROMOTION_MSK_NIGHT_TYPICAL)


def _longest_run(days: list[tuple[int, str, int, int, float, float]]) -> list[tuple[int, str, int, int, float, float]]:
    """Самая длинная серия суток подряд с откликом не выше PROMOTION_RESPONSE нормы в сумме."""
    best: list = []
    current: list = []
    for item in days:
        current = current + [item] if current and item[0] == current[-1][0] + 1 else [item]
        if len(current) > len(best) and sum(day[3] for day in current) <= PROMOTION_RESPONSE * sum(
                day[5] for day in current):
            best = current
    return best


def _in_campaign(publication: UUID, run: list, runs: dict[UUID, list]) -> bool:
    """Другой пост аккаунта продвигался в те же сутки — не меньше двух общих."""
    own = {item[1] for item in run}
    return any(len(own & {item[1] for item in other}) >= PROMOTION_CAMPAIGN_SHARED_DAYS
               for key, other in runs.items() if key != publication)


def _strong_run(run: list) -> bool:
    """Одиночная серия, которой хватает самой: долгая, крупная и с большим превышением."""
    excess = sorted(item[4] for item in run)
    return (len(run) >= PROMOTION_STRONG_DAYS and sum(item[2] for item in run) >= PROMOTION_STRONG_VIEWS
            and excess[len(excess) // 2] >= PROMOTION_STRONG_EXCESS)


def promotion_reasons(post: LedgerPost) -> frozenset[str]:
    """Почему пост похож на продвижение или рекомендации: необычная форма при живых реакциях (ADR-019)."""
    if post.platform not in PROMOTION_PLATFORMS or post.publication_type in EARLY_EXCLUDED_TYPES:
        return frozenset()
    ledger, reasons = post.ledger, set()
    decoupled = ledger.burst is not None and ledger.burst[0] == "decoupled"
    early, final = ledger.marks.get("h6"), ledger.marks.get("h72")
    if early and final and final.views >= PROMOTION_LATE_MIN_VIEWS and early.views < PROMOTION_LATE_SHARE * final.views and not decoupled:
        reasons.add("late_start")
    if ledger.burst is not None and not decoupled:
        reasons.add("live_burst")
    if _staircase(ledger.days):
        reasons.add("staircase")
    return frozenset(reasons)


def _staircase(days: Sequence[tuple[str, int, int, int]]) -> bool:
    """Лесенка: сутки подряд с заметным набором, спадом день ко дню и провалом ночью."""
    run = days[:PROMOTION_STAIR_DAYS + 1]
    views = [item[1] for item in run]
    if len(run) < PROMOTION_STAIR_DAYS or min(views[:PROMOTION_STAIR_DAYS]) < PROMOTION_STAIR_MIN_VIEWS:
        return False
    declines = sum(PROMOTION_STAIR_DECAY[0] <= right / max(left, 1) <= PROMOTION_STAIR_DECAY[1]
                   for left, right in zip(views, views[1:]))
    nights = sorted(item[3] / max(item[1], 1) for item in run)
    return declines >= len(views) - 2 and nights[len(nights) // 2] <= PROMOTION_STAIR_NIGHT


def _reach_of(items: Sequence[LedgerPost], subscribers: int | None) -> float | None:
    if not subscribers:
        return None
    values = sorted(point.views / subscribers for post in items if (point := post.ledger.marks.get("h72")))
    return values[len(values) // 2] if values else None


def _median_response(items: Sequence[LedgerPost]) -> float | None:
    values = sorted(point.reactions / point.views for post in items
                    if (point := post.ledger.marks.get("h72")) and point.views > 0)
    return values[len(values) // 2] if values else None


def _reason_findings(by_account: dict[UUID, list[LedgerPost]], subscribers: Mapping[UUID, int]) -> dict[UUID, dict[str, Any]]:
    """Аккаунты с охватом выше 90 % площадки, у которых необычная форма при живых реакциях повторяется."""
    reach = {account: value for account, items in by_account.items()
             if (value := _reach_of(items, subscribers.get(account))) is not None}
    response = [value for items in by_account.values() if (value := _median_response(items)) is not None]
    typical = sorted(response)[len(response) // 2] if response else 0.0
    platform_of = {account: by_account[account][0].platform for account in reach}
    found: dict[UUID, dict[str, Any]] = {}
    for account, value in reach.items():
        items = by_account[account]
        cohort = _p90_without(reach, platform_of, account)
        own_response = _median_response(items)
        if len(items) < PROMOTION_REASON_MIN_POSTS or not cohort or value <= cohort:
            continue
        if own_response is None or own_response > PROMOTION_MAX_RESPONSE * typical:
            continue
        reasons = {post.publication_id: promotion_reasons(post) for post in items}
        marked = [publication for publication, codes in reasons.items() if codes]
        if len(marked) < PROMOTION_REASON_SHARE * len(items):
            continue
        others = sorted(item for other, item in reach.items() if other != account and platform_of[other] == platform_of[account])
        found[account] = {"reach": round(value, 4), "reachP90": round(cohort, 4),
                          "reachRatio": round(value / max(others[len(others) // 2], 1e-9), 1),
                          "reasonPosts": len(marked), "windowPosts": len(items),
                          "reasons": {code: sum(code in codes for codes in reasons.values())
                                      for code in ("late_start", "live_burst", "staircase")},
                          "members": marked}
    return found


def promotion_findings(posts: Sequence[LedgerPost], computed_for: date,
                       subscribers: Mapping[UUID, int] | None = None) -> list[AccountFinding]:
    """Посты ВК, похожие на продвижение: серия суток как у продвигаемой записи или повторяемая форма при высоком охвате."""
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account = {account: [post for post in items if post.platform in PROMOTION_PLATFORMS and post.ledger.days]
                  for account, items in _own(posts, computed_for).items()}
    candidates = {account: _promotion_days(items, start, computed_for)
                  for account, items in by_account.items() if items}
    # Сутки, когда «продвижение» видно у половины аккаунтов площадки, — событие
    # площадки (обновление счётчиков), а не аккаунта.
    busy: dict[str, int] = {}
    for found in candidates.values():
        for day in {item[1] for days in found.values() for item in days}:
            busy[day] = busy.get(day, 0) + 1
    limit = max(2, WAVE_PLATFORM_SHARE * len(candidates))
    vk_posts = {account: [post for post in items if post.platform in PROMOTION_PLATFORMS]
                for account, items in _own(posts, computed_for).items() if items[0].platform in PROMOTION_PLATFORMS}
    by_reason = _reason_findings(vk_posts, subscribers or {})
    result = []
    for account, found in candidates.items():
        members, days_all, views_in, reactions_in, excesses = set(), set(), 0, 0, []
        reasoned = by_reason.pop(account, None)
        runs = {publication: run for publication, days in found.items()
                if len(run := _longest_run([item for item in days if busy[item[1]] < limit])) >= PROMOTION_MIN_DAYS}
        for publication, run in runs.items():
            if not (_in_campaign(publication, run, runs) or _strong_run(run)):
                continue
            members.add(publication)
            days_all |= {item[1] for item in run}
            views_in += sum(item[2] for item in run)
            reactions_in += sum(item[3] for item in run)
            excesses += [item[4] for item in run]
        if not members and reasoned is None:
            continue
        metrics: dict[str, Any] = {"posts": len(members)}
        if members:
            ordered = sorted(days_all)
            excesses.sort()
            metrics.update({"days": len(ordered), "firstDay": ordered[0], "lastDay": ordered[-1], "views": views_in,
                            "reactions": reactions_in, "excessMedian": round(excesses[len(excesses) // 2], 1)})
        if reasoned is not None:
            members |= set(reasoned["members"])
            metrics.update({key: value for key, value in reasoned.items() if key != "members"})
            metrics["posts"] = len(members)
        result.append(AccountFinding(account, by_account[account][0].platform, "promotion", 1, start, computed_for,
                                     metrics, tuple(sorted(members, key=str))))
    for account, reasoned in by_reason.items():
        metrics = {**{key: value for key, value in reasoned.items() if key != "members"}, "posts": len(reasoned["members"])}
        result.append(AccountFinding(account, vk_posts[account][0].platform, "promotion", 1, start, computed_for,
                                     metrics, tuple(sorted(reasoned["members"], key=str))))
    return result


def response_link_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]:
    """Реакции не растут вместе с просмотрами между постами аккаунта."""
    start = computed_for - timedelta(days=WINDOW_DAYS)
    values: dict[UUID, tuple[float, int]] = {}
    platform_of: dict[UUID, str] = {}
    for account, items in _own(posts, computed_for).items():
        if items[0].platform not in LINK_PLATFORMS:
            continue
        pairs = [(point.views, point.reactions) for post in items if (point := post.ledger.marks.get("h72")) and point.views > 0
                 and post.publication_type not in EARLY_EXCLUDED_TYPES]
        if len(pairs) < LINK_MIN_POSTS:
            continue
        views, reactions = zip(*pairs)
        correlation = _correlation([log1p(value) for value in views], [log1p(value) for value in reactions])
        if correlation is not None:
            values[account] = (correlation, len(pairs))
            platform_of[account] = items[0].platform
    result = []
    for account, (correlation, count) in values.items():
        others = sorted(item for other, (item, _) in values.items() if other != account and platform_of[other] == platform_of[account])
        if len(others) < LINK_MIN_COHORT:
            continue
        p10 = others[len(others) // 10]
        if correlation >= p10:
            continue
        metrics = {"correlation": round(correlation, 3), "cohortP10": round(p10, 3),
                   "cohortMedian": round(others[len(others) // 2], 3), "posts": count}
        result.append(AccountFinding(account, platform_of[account], "reaction_view_link", 1, start, computed_for, metrics))
    return result


def _correlation(left: Sequence[float], right: Sequence[float]) -> float | None:
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    cross = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    spread = sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right)
    return None if spread <= 0 else cross / sqrt(spread)


def _early_ratio(post: LedgerPost) -> float | None:
    """Доля реакций на просмотр на первом точном замере; None — пост не судится."""
    if post.platform not in EARLY_PLATFORMS or post.publication_type in EARLY_EXCLUDED_TYPES:
        return None
    first = post.ledger.marks.get("first")
    if first is None or first.views < EARLY_MIN_VIEWS:
        return None
    return first.reactions / first.views


def early_response_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]:
    """Посты аккаунта систематически получают реакции на первых минутах выше площадки."""
    start = computed_for - timedelta(days=WINDOW_DAYS)
    judged: dict[UUID, list[tuple[LedgerPost, float]]] = {}
    for account, items in _own(posts, computed_for).items():
        pairs = [(post, ratio) for post in items if (ratio := _early_ratio(post)) is not None]
        if pairs:
            judged[account] = pairs
    share = {account: sum(ratio >= EARLY_RATIO for _, ratio in pairs) / len(pairs)
             for account, pairs in judged.items()}
    platform_of = {account: pairs[0][0].platform for account, pairs in judged.items()}
    result = []
    for account, pairs in judged.items():
        if len(pairs) < EARLY_MIN_POSTS:
            continue
        cohort = _p90_without({other: value for other, value in share.items()
                               if len(judged[other]) >= EARLY_MIN_POSTS}, platform_of, account)
        if share[account] < max(EARLY_SHARE, cohort):
            continue
        members = [post for post, ratio in pairs if ratio >= EARLY_RATIO]
        member_ids = {post.publication_id for post in members}
        halves = _halves_by_time([post for post, _ in pairs], start, computed_for)
        steady = share[account] >= max(EARLY_STRONG_SHARE, cohort) and all(
            any(post.publication_id in member_ids for post in half) for half in halves)
        ratios = sorted(ratio for _, ratio in pairs)
        metrics = {"posts": len(pairs), "early": len(members), "share": round(share[account], 3),
                   "cohortP90": round(cohort, 3), "ratio": EARLY_RATIO,
                   "medianRatio": round(ratios[len(ratios) // 2], 3)}
        result.append(AccountFinding(account, platform_of[account], "early_response", 2 if steady else 1, start,
                                     computed_for, metrics, tuple(post.publication_id for post in members)))
    return result


def _amplitude(items: Sequence[LedgerPost]):
    return account_rhythm(post.ledger for post in items)


def flat_day_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]:
    """Поздние просмотры без ночного провала и с пиком вне дневных часов аудитории."""
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account = _own(posts, computed_for)
    measured = {account: rhythm for account, items in by_account.items()
                if (rhythm := _amplitude(items)) is not None and rhythm.views >= FLAT_MIN_VIEWS}
    values = {account: item.quiet_over_peak for account, item in measured.items()}
    platform_of = {account: by_account[account][0].platform for account in measured}
    result = []
    for account, item in measured.items():
        cohort = _p90_without(values, platform_of, account)
        if item.quiet_over_peak <= cohort or item.peak_in_daytime:
            continue
        parts = [_amplitude(half) for half in _halves_by_time(by_account[account], start, computed_for)]
        steady = all(part is not None and part.quiet_over_peak >= FLAT_STEADY_FACTOR * cohort for part in parts)
        quiet = (item.quiet_start_msk - 3) % 24
        members = []
        for post in by_account[account]:
            if post.ledger.hours is None:
                continue
            own = post.ledger.hours[0]
            windows = [sum(own[(begin + offset) % 24] for offset in range(FLAT_WINDOW)) for begin in range(24)]
            if max(windows) and 2 * windows[quiet] >= max(windows):
                members.append(post.publication_id)
        metrics = {"amplitude": round(item.quiet_over_peak, 3), "quietStartUtc": quiet, "cohortP90": round(cohort, 3),
                   "offsetHours": item.offset_hours, "peakStartMsk": item.peak_start_msk,
                   "posts": len(by_account[account])}
        result.append(AccountFinding(account, platform_of[account], "flat_daily_views", 2 if steady else 1,
                                     start, computed_for, metrics, tuple(members)))
    return result


def _percent(value: float) -> str:
    return f"{round(100 * value)} %"


def _number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _day(value: str) -> str:
    return date.fromisoformat(value).strftime("%d.%m")


def summary(finding: AccountFinding) -> str:
    """Одна фраза с числами — для карточки аккаунта и ссылки со страницы поста."""
    data = finding.metrics
    if finding.kind == "view_packs":
        return (f"У {data['packs']} из {data['posts']} постов за {WINDOW_DAYS} дней просмотры с публикации шли "
                f"ровным темпом или приходили пакетом почти без реакций; у аккаунтов площадки такое "
                f"бывает не больше чем у {_percent(data['cohortP90'])} постов (90-й перцентиль)")
    if finding.kind == "view_waves":
        return (f"В {data['days']} дн. ({data['hours']} ч) посты стены одновременно "
                f"получали просмотры почти без реакций: +{_number(data['views'])} просмотров, "
                f"{_number(data['reactions'])} реакций; это {_percent(data['viewShare'])} просмотров постов окна")
    if finding.kind == "promotion" and "reach" in data:
        return (f"Охват в {data['reachRatio']:g} раза выше ожидаемого при обычной доле реакций; так выглядят платное "
                f"продвижение записей, рекомендации или посев по внешней ссылке. Постов с такой формой: {data['posts']}. "
                "Пометка — контекст поста, а не уровень аномалии")
    if finding.kind == "reaction_view_link":
        return (f"Связь реакций с просмотрами между {data['posts']} постами — {data['correlation']:g} при "
                f"{data['cohortMedian']:g} у типичного аккаунта площадки. Отдельный признак слабый: разные форматы постов "
                "тоже находят разную аудиторию")
    if finding.kind == "promotion":
        return (f"У {data['posts']} пост. в {data['days']} дн. ({_day(data['firstDay'])}–{_day(data['lastDay'])}) "
                f"просмотров в {data['excessMedian']:g} раза больше, чем у постов аккаунта того же возраста, "
                f"по суточному ритму аудитории и почти без реакций: +{_number(data['views'])} просмотров, "
                f"{_number(data['reactions'])} реакций. Пометка — контекст поста, а не уровень аномалии")
    if finding.kind == "early_response":
        return (f"У {data['early']} из {data['posts']} постов за {WINDOW_DAYS} дней на первом замере, в первые "
                f"полчаса, реакций было не меньше {_percent(data['ratio'])} просмотров (медиана — "
                f"{_percent(data['medianRatio'])}); у 9 из 10 аккаунтов площадки таких постов не больше "
                f"{_percent(data['cohortP90'])}. Живой ранний отклик — единицы процентов")
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
        return "Волны просмотров по стене"
    if finding.kind == "reaction_view_link":
        return f"Связь реакций с просмотрами {data['correlation']:g}"
    if finding.kind == "promotion" and "reach" in data:
        return f"Охват выше ожидаемого в {data['reachRatio']:g} раза: {data['posts']} пост."
    if finding.kind == "promotion":
        return f"Похоже на продвижение: {data['posts']} пост. за {data['days']} дн."
    if finding.kind == "early_response":
        return f"Реакций не меньше {_percent(data['ratio'])} просмотров в первые полчаса у {_percent(data['share'])} постов"
    if finding.kind == "level3_share":
        return f"{_percent(data['share'])} постов на уровне 3"
    return "Просмотры идут круглые сутки"


def figure(finding: AccountFinding) -> dict[str, Any] | None:
    """Аккаунт против 90-го перцентиля площадки — одна мера для инфографики."""
    data = finding.metrics
    if finding.kind in ("view_waves", "promotion"):
        return None
    if finding.kind == "reaction_view_link":
        return {"value": data["correlation"], "typical": data["cohortMedian"], "unit": "decimal",
                "label": "связь реакций и просмотров между постами", "direction": "lower"}
    labels = {"view_packs": "постов с пакетом просмотров", "level3_share": "постов на уровне 3",
              "flat_daily_views": "тихие часы к активным",
              "early_response": f"постов с реакциями ≥ {_percent(EARLY_RATIO)} просмотров в первые полчаса"}
    value = data["amplitude"] if finding.kind == "flat_daily_views" else data["share"]
    return {"value": value, "typical": data["cohortP90"], "unit": "percent", "label": labels[finding.kind],
            "direction": "higher"}
