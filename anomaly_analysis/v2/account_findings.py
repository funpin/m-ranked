"""Аккаунтные находки: закономерность, видимая только на многих постах сразу.

Пост сравнивается сам с собой, и слабая статистика одного поста не даёт
уверенного вывода: 60 реакций в первые часы и почти ничего потом — у
небольшой аудитории это может быть и случайностью. Если же так выглядят
почти все посты аккаунта месяц подряд, а у других аккаунтов площадки нет,
это уже закономерность. Находка относится к аккаунту, считается отдельно от
уровней постов и показывается на постах, из которых она складывается.

Виды:

* ``early_pack`` — повторяющийся стартовый пакет: доля реакций на просмотр в
  первые 2 или 6 часов (что сильнее) во много раз выше доли за остаток суток. У живой
  аудитории она выше в 1,5–2 раза (медиана когорты 1,5 в MAX и 1,0 в ВК по
  постам 12.09–05.10.2026); у аккаунта с находкой — больше чем в пять раз у
  типичного поста и больше чем в восемь у большинства.
* ``regular_reactions`` — слишком ровный отклик: число реакций к 72 часам
  почти не меняется от поста к посту. Разброс сверх пуассоновского шума
  (sd log R за вычетом 1/R) у живых аккаунтов отражает разный интерес к
  разным постам — медиана когорты MAX 0,35. Около нуля он означает, что
  содержание поста на число реакций не влияет.
* ``late_growth`` — посты добирают реакции через дни: через 3–14 суток реакций
  втрое больше, чем к суткам, и не меньше чем на +20. У типичного аккаунта MAX
  и Telegram таких постов нет, ВК — до 2 % (90-й перцентиль 22 %); у
  аккаунтов с находкой — треть постов и больше или 8 постов подряд. Это и
  делает медианы старых постов на графике аккаунта выше свежих.
* ``late_engagement`` — устойчиво необычный поздний отклик из профиля
  account_tail (ADR-015); участники — посты окна с поздним приростом.
* ``synchronous_waves`` — волны реакций сразу по многим постам: дни, когда
  синхронный подъём (признак 8) получили 10 и больше постов аккаунта. У
  типичного аккаунта площадки таких дней за месяц нет; на 08.09–07.10.2026
  находка у двух аккаунтов ВК, ЮЗГУ (7 дней) и КГУ (6). В эти дни лайки за
  одни и те же 15 минут получала бо́льшая часть стены (в среднем 27–45 %
  старых постов на 15-минутку против 4–5 % у медианного вуза ВК), а доля
  лайков на просмотр старых постов — 8–13 % против 1,1–1,3 %.
* ``engagement_shift`` — отклик вырос без роста аудитории: с некоторой даты доля
  реакций на просмотр (R72/V72) у постов вдвое и больше выше, чем две недели до
  неё, почти все посты после даты выше 90 % прежних, просмотры прежние. Тот же
  сдвиг у других аккаунтов вуза в ±3 сутках показывается как подтверждение.
* ``night_reactions`` — реакции приходят ночью аудитории (определённой по
  провалу её просмотров), когда просмотров почти нет.

``regular_reactions`` меряет разброс и за окно, и внутри суток публикации:
скачок общего уровня раздувает первый, но не второй; разброс меньше
пуассоновского (недоразброс) — самая сильная форма.

Это статистическая необычность относительно площадки, а не доказательство
искусственного происхождения (ADR-006); у каждого вида есть честные
альтернативы.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import math
from statistics import median
from typing import Any, Iterable, Mapping, Sequence
from uuid import UUID

from .tail_ledger import MOSCOW, Point, TailLedger

METHOD_VERSION = "account-findings-v3"
WINDOW_DAYS = 30
STATUS_LABELS = {1: "необычный", 2: "устойчиво необычный"}
TITLES = {
    "early_pack": "Повторяющийся стартовый пакет реакций",
    "regular_reactions": "Слишком ровный отклик",
    "late_growth": "Посты добирают реакции через дни",
    "late_engagement": "Необычный отклик на старые посты",
    "synchronous_waves": "Волны реакций сразу на многих постах",
    "engagement_shift": "Отклик вырос без роста аудитории",
    "night_reactions": "Реакции приходят ночью, когда просмотров нет",
}
ALTERNATIVES = {
    "early_pack": ("Подписчики-активисты реагируют сразу после публикации, а поздние читатели почти не "
                   "реагируют; рассылка поста в профильные чаты в первые минуты"),
    "regular_reactions": ("Стабильное ядро аудитории, которое реагирует на каждый пост одинаково; "
                          "однотипные посты по расписанию"),
    "late_growth": "Пост попал в рекомендации или подборку спустя дни; пересылки в чаты",
    "late_engagement": "Регулярные читатели архива, подборки и пересылки старых постов",
    "synchronous_waves": ("Ссылка на стену в популярном сообществе или рассылке: пришедшие листают ленту и "
                          "отмечают старые посты; активисты отмечают всю ленту после события"),
    "engagement_shift": ("Конкурс или акция вуза, призыв реагировать на посты, смена формата постов; приток "
                         "новых активных подписчиков (тогда растут и просмотры)"),
    "night_reactions": ("Студенты на практике или за рубежом, ночные смены, иностранная аудитория (тогда "
                        "ночью растут и просмотры)"),
}

# Стартовый пакет: окна «первые 2 ч / 2–24 ч» и «первые 6 ч / 6–24 ч» по отметкам
# сводки; у поста берётся большее отношение. Пакет ГУАП в MAX длится 3,5–5 ч, и
# двухчасовое окно делило его пополам. Когорта считается тем же правилом.
# Первый замер (до 30 мин) — для мгновенного старта: у id0901006061 в MAX
# по 10 реакций в первую минуту на каждом посте, затем обычный темп.
PACK_SPLITS = ("first", "h2", "h6")
PACK_MIN_POSTS = 15
PACK_MIN_REACTIONS = 5
PACK_MIN_EARLY_VIEWS = 10
PACK_MIN_LATER_VIEWS = 20
PACK_POST_RATIO = 8.0
PACK_MEDIAN_RATIO = 5.0
PACK_MIN_SHARE = 0.4
# Ровный отклик: реакции к 72 часам.
REGULAR_MIN_POSTS = 30
REGULAR_MIN_MEDIAN = 20
REGULAR_MAX_EXTRA = 0.08
REGULAR_HALF_EXTRA = 0.10
# Разброс внутри московских суток публикации: скачок общего уровня (ЮЗГУ в MAX,
# ~95 реакций на пост до 19.09 и ~250 после) раздувает разброс за окно, хотя
# посты одного дня по-прежнему получают почти одно и то же число реакций.
REGULAR_DAY_MIN_POSTS = 3
REGULAR_MIN_DAYS = 8
REGULAR_HALF_MIN_DAYS = 4
# Недоразброс: χ² разброса внутри дней ниже 1-го перцентиля (z = −2,326) при
# пуассоновской гипотезе. Посты отличаются меньше, чем дал бы чистый случай.
SUBPOISSON_Z = -2.326
SUBPOISSON_MIN_DF = 20
MIN_HALF_POSTS = 7
# Поздняя докачка: реакции через 3–14 суток против реакций к суткам.
GROWTH_MIN_AGE = 3 * 24 * 3600
GROWTH_RATIO = 3.0
GROWTH_MIN_DELTA = 20
GROWTH_MIN_POSTS = 15
GROWTH_MIN_SHARE = 0.3
GROWTH_MIN_RUN = 8
GROWTH_STRONG_SHARE = 0.4
GROWTH_STRONG_RUN = 15
# Синхронные волны: день — волна, если признак 8 в этот день (по Москве) у
# стольких постов аккаунта; находка — от четырёх таких дней за окно, устойчивая —
# от двух в каждой половине окна.
WAVE_MIN_POSTS = 10
WAVE_MIN_DAYS = 4
WAVE_HALF_DAYS = 2
# Скачок отклика: доля реакций на просмотр (R72 / V72) у постов после даты среза
# против двух недель до неё. ЮЗГУ в MAX с 19.09.2026: медиана 9,9 % → 24,9 %,
# просмотры 753 → 830, все посты после среза выше 90-го перцентиля до него. У
# аккаунтов MAX наибольший такой сдвиг за месяц — медиана ×1,26, p90 ×1,64.
SHIFT_BEFORE_DAYS = 14
SHIFT_AFTER_DAYS = 10
SHIFT_MIN_BEFORE = 12
SHIFT_MIN_AFTER = 8
SHIFT_MIN_VIEWS = 50
SHIFT_MIN_REACTIONS = 5
SHIFT_RATIO = 2.0
SHIFT_SEPARATION = 0.8
SHIFT_VIEWS_RANGE = (0.5, 2.0)
SHIFT_STRONG_SEPARATION = 0.9
SHIFT_RECENT_DAYS = 7
SHIFT_RECENT_RATIO = 1.5
SHIFT_ONSET_SHARE = 0.95
# Подтверждение: тот же вуз, другая площадка, лучший срез в ±3 сутках.
SHIFT_SUPPORT_DAYS = 3
SHIFT_SUPPORT_RATIO = 1.5
# Ночные реакции: почасовой поздний прирост сводки v4 (24 ч–14 сут). Ночь —
# шесть подряд часов с наименьшей долей просмотров у самой аудитории аккаунта:
# часового пояса вуза в каталоге нет, а у вузов Сибири и Дальнего Востока
# «московская ночь» — их утро (БГУ в MAX: 26 % поздних просмотров в 01–07 МСК).
# Если провала нет (ночью больше 12 % просмотров), ночь не определена. МАИ в
# MAX 10.09–01.10.2026: 36 % поздних реакций ночью при 3 % просмотров, НИТУ
# МИСИС — 10 % при 1,3 %; у остальных аккаунтов MAX доля реакций ночью не выше
# доли просмотров больше чем в полтора раза.
NIGHT_HOURS = 6
NIGHT_MAX_VIEW_SHARE = 0.12
NIGHT_MIN_REACTIONS = 200
NIGHT_HALF_MIN_REACTIONS = 50
NIGHT_MIN_SHARE = 0.10
NIGHT_LIFT = 4.0
NIGHT_MEMBER_REACTIONS = 5
NIGHT_MSK_START = 1
NIGHT_SHIFT_NOTE_HOURS = 2
MOSCOW_UTC_OFFSET = 3
PLATFORM_TITLES = {"telegram": "Telegram", "vk": "VK", "max": "MAX", "rutube": "Rutube"}


@dataclass(frozen=True, slots=True)
class LedgerPost:
    publication_id: UUID
    account_id: UUID
    platform: str
    published_at: datetime
    is_repost: bool
    ledger: TailLedger
    institution_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class SynchronyEvent:
    """Признак синхронного подъёма (8) на посте: час подъёма из сохранённого вывода."""

    account_id: UUID
    platform: str
    publication_id: UUID
    hour: datetime


@dataclass(frozen=True, slots=True)
class AccountFinding:
    account_id: UUID
    platform: str
    kind: str
    status: int
    window_start: date
    window_end: date
    metrics: Mapping[str, Any]
    members: tuple[UUID, ...] = field(default=())

    @property
    def title(self) -> str:
        return TITLES[self.kind]


def pack_ratio(ledger: TailLedger) -> tuple[float, int, int, int, int] | None:
    """Во сколько раз доля реакций в первые 2 или 6 ч выше доли за остаток суток; None — мало данных."""
    day = ledger.marks.get("h24")
    best = None
    for key in PACK_SPLITS:
        early = ledger.marks.get(key)
        if early is None or day is None:
            continue
        r1, v1 = early.reactions, early.views
        r2, v2 = max(0, day.reactions - early.reactions), max(0, day.views - early.views)
        if r1 + r2 < PACK_MIN_REACTIONS or v1 < PACK_MIN_EARLY_VIEWS or v2 < PACK_MIN_LATER_VIEWS:
            continue
        value = ((r1 / v1) / max(r2 / v2, 0.5 / v2), r1, v1, r2, v2)
        if best is None or value[0] > best[0]:
            best = value
    return best


def findings(posts: Iterable[LedgerPost], computed_for: date,
             late_members: Mapping[UUID, Sequence[UUID]] | None = None,
             tail_status: Mapping[UUID, tuple[str, int, Mapping[str, Any]]] | None = None,
             synchrony: Iterable[SynchronyEvent] = ()) -> list[AccountFinding]:
    """Находки по постам окна [computed_for − 30 сут; computed_for).

    `tail_status` — статус профиля позднего отклика аккаунта (площадка, статус,
    метрики), `late_members` — посты окна с поздним приростом реакций,
    `synchrony` — признаки синхронного подъёма постов окна.
    """
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account: dict[UUID, list[LedgerPost]] = {}
    for post in posts:
        if start <= post.published_at.date() < computed_for:
            by_account.setdefault(post.account_id, []).append(post)
    result: list[AccountFinding] = []
    pack_cohort = _cohort(by_account, _pack_stats, "median")
    regular_cohort = _cohort(by_account, _regular_stats, "extra")
    growth_cohort = _cohort(by_account, _growth_stats, "share")
    events: dict[UUID, list[SynchronyEvent]] = {}
    for event in synchrony:
        events.setdefault(event.account_id, []).append(event)
    waves = {account: _wave_stats(items, events.get(account, ()), start, computed_for)
             for account, items in by_account.items()}
    shifts = {account: _shift_stats(items) for account, items in by_account.items()}
    shift_cohort = _cohort(by_account, _shift_stats, "ratio")
    nights = {account: _night_stats(items) for account, items in by_account.items()}
    night_cohort = _cohort(by_account, _night_stats, "lift")
    wave_cohort: dict[str, list[float]] = {}
    for account, stats in waves.items():
        wave_cohort.setdefault(by_account[account][0].platform, []).append(stats["share"])
    for account, items in by_account.items():
        platform = items[0].platform
        pack = _pack_stats(items)
        if pack is not None and _pack_found(pack):
            halves = [_pack_stats(half, min_posts=MIN_HALF_POSTS) for half in _halves(items)]
            status = 2 if all(item is not None and item["median"] >= PACK_MEDIAN_RATIO for item in halves) else 1
            metrics = {**_public(pack), "cohort": pack_cohort.get(platform, {}),
                       "cohortRank": _rank(pack["median"], pack_cohort.get(platform, {}).get("medians", ()))}
            result.append(AccountFinding(account, platform, "early_pack", status, start, computed_for,
                                         _without(metrics, "medians"), tuple(pack["members"])))
        regular = _regular_stats(items)
        if regular is not None and regular["extra"] <= REGULAR_MAX_EXTRA:
            halves = [_regular_stats(half, min_posts=MIN_HALF_POSTS, min_days=REGULAR_HALF_MIN_DAYS)
                      for half in _halves(items)]
            steady = all(item is not None and item["extra"] <= REGULAR_HALF_EXTRA for item in halves)
            status = 2 if steady or regular["subPoisson"] else 1
            metrics = {**_public(regular), "cohort": _without(regular_cohort.get(platform, {}), "medians")}
            result.append(AccountFinding(account, platform, "regular_reactions", status, start, computed_for,
                                         metrics, tuple(regular["members"])))
        growth = _growth_stats(items)
        if growth is not None and (growth["share"] >= GROWTH_MIN_SHARE or growth["run"] >= GROWTH_MIN_RUN):
            status = 2 if growth["share"] >= GROWTH_STRONG_SHARE or growth["run"] >= GROWTH_STRONG_RUN else 1
            metrics = {**_public(growth), "cohort": _without(growth_cohort.get(platform, {}), "medians")}
            result.append(AccountFinding(account, platform, "late_growth", status, start, computed_for,
                                         metrics, tuple(growth["members"])))
        wave = waves[account]
        if wave["days"] >= WAVE_MIN_DAYS:
            status = 2 if min(wave["firstHalfDays"], wave["secondHalfDays"]) >= WAVE_HALF_DAYS else 1
            shares = sorted(wave_cohort.get(platform, ()))
            metrics = {**_public(wave), "cohort": {"accounts": len(shares), "median": round(median(shares), 3)}}
            result.append(AccountFinding(account, platform, "synchronous_waves", status, start, computed_for,
                                         metrics, tuple(wave["members"])))
        shift = shifts[account]
        if shift is not None and _shift_found(shift):
            status = 2 if (shift["separation"] >= SHIFT_STRONG_SEPARATION and shift["erRecent"] is not None
                           and shift["erRecent"] >= SHIFT_RECENT_RATIO * shift["erBefore"]) else 1
            metrics = {**_public(shift), "cohort": _without(shift_cohort.get(platform, {}), "medians"),
                       "corroboration": _corroboration(account, items, shift, by_account, shifts)}
            result.append(AccountFinding(account, platform, "engagement_shift", status, start, computed_for,
                                         metrics, tuple(shift["members"])))
        night = nights[account]
        if night is not None and _night_found(night):
            halves = [_night_stats(half, night["nightStartUtc"], NIGHT_HALF_MIN_REACTIONS) for half in _halves(items)]
            status = 2 if all(item is not None and _night_found(item) for item in halves) else 1
            metrics = {**_public(night), "cohort": _without(night_cohort.get(platform, {}), "medians")}
            result.append(AccountFinding(account, platform, "night_reactions", status, start, computed_for,
                                         metrics, tuple(night["members"])))
    for account, (platform, status, metrics) in (tail_status or {}).items():
        if status == 2:
            # Участники — посты с признаком позднего отклика и посты, у которых
            # по сводке доля поздних реакций хотя бы вдвое выше ранней (в том
            # числе округлённые счётчики Telegram, где признак поста не ставится).
            from_ledgers = [post.publication_id for post in by_account.get(account, ())
                            if _late_member(post.ledger)]
            members = tuple(dict.fromkeys([*(late_members or {}).get(account, ()), *from_ledgers]))
            result.append(AccountFinding(account, platform, "late_engagement", 2, start, computed_for,
                                         dict(metrics), members))
    return result


LATE_MEMBER_RATIO = 2.0
LATE_MEMBER_REACTIONS = 3


def _late_member(ledger: TailLedger) -> bool:
    late, early = ledger.late, ledger.early
    if late is None or early is None or late[1] < LATE_MEMBER_REACTIONS:
        return False
    late_rate = (late[1] + 0.5) / (late[0] + 1)
    early_rate = (early.reactions + 0.5) / (early.views + 1)
    return late_rate >= LATE_MEMBER_RATIO * early_rate


def _pack_stats(items: Sequence[LedgerPost], min_posts: int = PACK_MIN_POSTS) -> dict[str, Any] | None:
    rows = [(post.publication_id, value) for post in items if (value := pack_ratio(post.ledger)) is not None]
    if len(rows) < min_posts:
        return None
    ratios = [value[0] for _, value in rows]
    return {
        "posts": len(rows), "median": round(median(ratios), 2),
        "share": round(sum(ratio >= PACK_POST_RATIO for ratio in ratios) / len(rows), 3),
        "earlyReactions": sum(value[1] for _, value in rows), "earlyViews": sum(value[2] for _, value in rows),
        "laterReactions": sum(value[3] for _, value in rows), "laterViews": sum(value[4] for _, value in rows),
        "members": [publication for publication, value in rows if value[0] >= PACK_POST_RATIO],
    }


def _pack_found(stats: Mapping[str, Any]) -> bool:
    return stats["median"] >= PACK_MEDIAN_RATIO and stats["share"] >= PACK_MIN_SHARE


def _regular_stats(items: Sequence[LedgerPost], min_posts: int = REGULAR_MIN_POSTS,
                   min_days: int = REGULAR_MIN_DAYS) -> dict[str, Any] | None:
    rows = [(post, mark) for post in items
            if not post.is_repost and (mark := post.ledger.marks.get("h72")) is not None and mark.reactions > 0
            and mark.views > 0]
    if len(rows) < min_posts:
        return None
    reactions = [mark.reactions for _, mark in rows]
    views = [mark.views for _, mark in rows]
    if median(reactions) < REGULAR_MIN_MEDIAN:
        return None
    logs = [math.log(value) for value in reactions]
    mean = sum(logs) / len(logs)
    variance = sum((value - mean) ** 2 for value in logs) / len(logs)
    poisson = sum(1 / value for value in reactions) / len(reactions)
    view_logs = [math.log(value) for value in views]
    view_mean = sum(view_logs) / len(view_logs)
    ordered = sorted(reactions)
    window_extra = round(math.sqrt(max(variance - poisson, 0.0)), 4)
    day = _day_spread([(post.published_at, mark.reactions) for post, mark in rows], min_days)
    extra, measure = window_extra, "window"
    if day["dayExtra"] is not None and day["dayExtra"] < window_extra:
        extra, measure = day["dayExtra"], "day"
    return {
        "posts": len(rows), "extra": extra, "measure": measure, "windowExtra": window_extra, **day,
        "sdLogReactions": round(math.sqrt(variance), 4),
        "sdLogViews": round(math.sqrt(sum((value - view_mean) ** 2 for value in view_logs) / len(view_logs)), 4),
        "medianReactions": median(reactions), "medianViews": median(views),
        "p10Reactions": ordered[len(ordered) // 10], "p90Reactions": ordered[(9 * len(ordered)) // 10],
        "members": [post.publication_id for post, _ in rows],
    }


def _day_spread(rows: Sequence[tuple[datetime, int]], min_days: int) -> dict[str, Any]:
    """Разброс реакций между постами одних московских суток и проверка недоразброса.

    dayExtra — как extra, но по отклонениям log R от медианы своих суток:
    объединённая несмещённая дисперсия минус пуассоновская доля mean(1/R).
    χ² = Σ (R − m)² / m по суткам (m — среднее суток) при df = Σ(n − 1).
    """
    by_day: dict[date, list[int]] = {}
    for published, value in rows:
        by_day.setdefault(published.astimezone(MOSCOW).date(), []).append(value)
    days = [values for values in by_day.values() if len(values) >= REGULAR_DAY_MIN_POSTS]
    if len(days) < min_days:
        return {"dayExtra": None, "days": len(days), "chi2": None, "chi2Df": None, "subPoisson": False}
    squares = df = 0.0
    inverse = []
    chi2 = 0.0
    for values in days:
        center = math.log(median(values))
        squares += sum((math.log(value) - center) ** 2 for value in values)
        df += len(values) - 1
        inverse += [1 / value for value in values]
        average = sum(values) / len(values)
        chi2 += sum((value - average) ** 2 for value in values) / average
    pooled = squares / df
    day_extra = round(math.sqrt(max(pooled - sum(inverse) / len(inverse), 0.0)), 4)
    critical = df * (1 - 2 / (9 * df) + SUBPOISSON_Z * math.sqrt(2 / (9 * df))) ** 3
    return {"dayExtra": day_extra, "days": len(days), "chi2": round(chi2, 1), "chi2Df": int(df),
            "subPoisson": df >= SUBPOISSON_MIN_DF and chi2 < critical}


def _growth_stats(items: Sequence[LedgerPost]) -> dict[str, Any] | None:
    rows = []
    for post in sorted(items, key=lambda item: item.published_at):
        day, late = post.ledger.marks.get("h24"), post.ledger.end or post.ledger.marks.get("h72")
        if day is None or late is None or late.age < GROWTH_MIN_AGE:
            continue
        gained = late.reactions - day.reactions
        rows.append((post.publication_id, late.reactions >= GROWTH_RATIO * (day.reactions + 1)
                     and gained >= GROWTH_MIN_DELTA, day.reactions, late.reactions))
    if len(rows) < GROWTH_MIN_POSTS:
        return None
    run = longest = 0
    for _, boosted, _, _ in rows:
        run = run + 1 if boosted else 0
        longest = max(longest, run)
    boosted_rows = [row for row in rows if row[1]]
    return {
        "posts": len(rows), "boosted": len(boosted_rows), "share": round(len(boosted_rows) / len(rows), 3),
        "run": longest,
        "medianDay": median([row[2] for row in boosted_rows]) if boosted_rows else None,
        "medianLate": median([row[3] for row in boosted_rows]) if boosted_rows else None,
        "members": [row[0] for row in boosted_rows],
    }


def _wave_stats(items: Sequence[LedgerPost], events: Iterable[SynchronyEvent], start: date,
                end: date) -> dict[str, Any]:
    """Дни-волны: признак 8 в один день у WAVE_MIN_POSTS и больше постов окна."""
    posts = {post.publication_id for post in items}
    by_day: dict[date, set[UUID]] = {}
    for event in events:
        day = event.hour.astimezone(MOSCOW).date()
        if event.publication_id in posts and start <= day < end:
            by_day.setdefault(day, set()).add(event.publication_id)
    wave_days = sorted(day for day, members in by_day.items() if len(members) >= WAVE_MIN_POSTS)
    members = sorted(set().union(*(by_day[day] for day in wave_days)), key=str) if wave_days else []
    middle = start + (end - start) / 2
    return {
        "posts": len(posts), "days": len(wave_days),
        "firstHalfDays": sum(day < middle for day in wave_days),
        "secondHalfDays": sum(day >= middle for day in wave_days),
        "maxPosts": max((len(by_day[day]) for day in wave_days), default=0),
        "dates": [day.isoformat() for day in wave_days],
        "share": round(len(members) / len(posts), 3) if posts else 0.0,
        "members": members,
    }


def _shift_stats(items: Sequence[LedgerPost]) -> dict[str, Any] | None:
    """Лучший срез: наибольшие рост медианы R72/V72 после даты и отделимость при сопоставимых просмотрах."""
    rows = sorted(((post.published_at.astimezone(MOSCOW).date(), post.publication_id, mark.reactions, mark.views)
                   for post in items if not post.is_repost and (mark := post.ledger.marks.get("h72")) is not None
                   and mark.views >= SHIFT_MIN_VIEWS), key=lambda row: (row[0], str(row[1])))
    if len(rows) < SHIFT_MIN_BEFORE + SHIFT_MIN_AFTER:
        return None
    candidates = []
    for cut in sorted({row[0] for row in rows}):
        before = [row for row in rows if cut - timedelta(days=SHIFT_BEFORE_DAYS) <= row[0] < cut]
        after = [row for row in rows if cut <= row[0] < cut + timedelta(days=SHIFT_AFTER_DAYS)]
        if len(before) < SHIFT_MIN_BEFORE or len(after) < SHIFT_MIN_AFTER:
            continue
        reactions_before = median(row[2] for row in before)
        er_before = median(row[2] / row[3] for row in before)
        views_ratio = median(row[3] for row in after) / median(row[3] for row in before)
        if reactions_before < SHIFT_MIN_REACTIONS or er_before <= 0 or not (
                SHIFT_VIEWS_RANGE[0] <= views_ratio <= SHIFT_VIEWS_RANGE[1]):
            continue
        er_after = median(row[2] / row[3] for row in after)
        ratio = er_after / er_before
        ordered = sorted(row[2] / row[3] for row in before)
        p90 = ordered[min(len(ordered) - 1, math.ceil(0.9 * len(ordered)) - 1)]
        above = [row for row in after if row[2] / row[3] > p90]
        candidates.append((ratio * len(above) / len(after), ratio, cut, before, after, er_before, er_after,
                           views_ratio, above))
    if not candidates:
        return None
    # Срез — там, где рост и отделимость вместе наибольшие; из почти равных
    # (через сутки после скачка «до» почти не меняется) — самый ранний: начало.
    top = max(item[0] for item in candidates)
    _, ratio, cut, before, after, er_before, er_after, views_ratio, above = next(
        item for item in candidates if item[0] >= SHIFT_ONSET_SHARE * top)
    last = rows[-1][0]
    recent = [row[2] / row[3] for row in rows if row[0] > last - timedelta(days=SHIFT_RECENT_DAYS) and row[0] >= cut]
    return {
        "cut": cut.isoformat(), "ratio": round(ratio, 3), "separation": round(len(above) / len(after), 3),
        "viewsRatio": round(views_ratio, 3), "erBefore": round(er_before, 4), "erAfter": round(er_after, 4),
        "erRecent": round(median(recent), 4) if recent else None,
        "before": len(before), "after": len(after),
        "medianReactionsBefore": median(row[2] for row in before),
        "medianReactionsAfter": median(row[2] for row in after),
        "medianViewsBefore": median(row[3] for row in before), "medianViewsAfter": median(row[3] for row in after),
        "members": [row[1] for row in above],
    }


def _shift_found(stats: Mapping[str, Any]) -> bool:
    return stats["ratio"] >= SHIFT_RATIO and stats["separation"] >= SHIFT_SEPARATION


def _corroboration(account: UUID, items: Sequence[LedgerPost], shift: Mapping[str, Any],
                   by_account: Mapping[UUID, Sequence[LedgerPost]],
                   shifts: Mapping[UUID, Mapping[str, Any] | None]) -> list[dict[str, Any]]:
    """Тот же сдвиг у других аккаунтов вуза: лучший срез рядом по времени."""
    institution = items[0].institution_id
    if institution is None:
        return []
    cut = date.fromisoformat(shift["cut"])
    support = []
    for other, posts in by_account.items():
        stats = shifts.get(other)
        if other == account or posts[0].institution_id != institution or stats is None:
            continue
        if abs((date.fromisoformat(stats["cut"]) - cut).days) <= SHIFT_SUPPORT_DAYS and \
                stats["ratio"] >= SHIFT_SUPPORT_RATIO:
            support.append({"platform": posts[0].platform, "accountId": str(other), "cut": stats["cut"],
                            "ratio": stats["ratio"]})
    return sorted(support, key=lambda item: (-item["ratio"], item["platform"]))


def _night_stats(items: Sequence[LedgerPost], night_start: int | None = None,
                 min_reactions: int = NIGHT_MIN_REACTIONS) -> dict[str, Any] | None:
    """Доли позднего прироста реакций и просмотров в ночь аудитории; None — мало данных или нет ночи."""
    posts = [post for post in items if not post.is_repost and post.ledger.hours is not None]
    views, reactions = [0] * 24, [0] * 24
    for post in posts:
        for hour in range(24):
            views[hour] += post.ledger.hours[0][hour]
            reactions[hour] += post.ledger.hours[1][hour]
    total_views, total_reactions = sum(views), sum(reactions)
    if total_reactions < min_reactions or not total_views:
        return None

    def window(start: int) -> list[int]:
        return [(start + offset) % 24 for offset in range(NIGHT_HOURS)]

    if night_start is None:
        night_start = min(range(24), key=lambda start: (sum(views[hour] for hour in window(start)), start))
    night = window(night_start)
    view_share = sum(views[hour] for hour in night) / total_views
    if view_share > NIGHT_MAX_VIEW_SHARE:
        return None
    reaction_share = sum(reactions[hour] for hour in night) / total_reactions
    start_msk = (night_start + MOSCOW_UTC_OFFSET) % 24
    shift = (start_msk - NIGHT_MSK_START + 12) % 24 - 12
    return {
        "posts": len(posts), "views": total_views, "reactions": total_reactions,
        "nightStartUtc": night_start, "nightStartMsk": start_msk, "shiftHours": shift,
        "viewShare": round(view_share, 4), "reactionShare": round(reaction_share, 4),
        "lift": round(reaction_share / max(view_share, 0.005), 2),
        "members": [post.publication_id for post in posts
                    if sum(post.ledger.hours[1][hour] for hour in night) >= NIGHT_MEMBER_REACTIONS],
    }


def _night_found(stats: Mapping[str, Any]) -> bool:
    return stats["reactionShare"] >= NIGHT_MIN_SHARE and stats["reactionShare"] >= NIGHT_LIFT * stats["viewShare"]


def _cohort(by_account, measure, key: str) -> dict[str, dict[str, Any]]:
    values: dict[str, list[float]] = {}
    for items in by_account.values():
        stats = measure(items)
        if stats is not None:
            values.setdefault(items[0].platform, []).append(stats[key])
    return {platform: {"accounts": len(items), "median": round(median(items), 3), "medians": sorted(items)}
            for platform, items in values.items()}


def _rank(value: float, ordered: Sequence[float]) -> float | None:
    if not ordered:
        return None
    return round(sum(item <= value for item in ordered) / len(ordered), 3)


def _halves(items: Sequence[LedgerPost]) -> tuple[list[LedgerPost], list[LedgerPost]]:
    ordered = sorted(items, key=lambda post: post.published_at)
    middle = len(ordered) // 2
    return ordered[:middle], ordered[middle:]


def _public(stats: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in stats.items() if key != "members"}


def _without(mapping: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in mapping.items() if name != key}


def _ru(value: float, digits: int = 1) -> str:
    """Число по-русски: десятичная запятая, неразрывный пробел между разрядами."""
    text = f"{value:,.{digits}f}".replace(",", "\u00a0").replace(".", ",")
    if not digits:
        return text
    trimmed = text.rstrip("0").rstrip(",")
    return trimmed if trimmed and trimmed != "-" else "0"


def summary(finding: AccountFinding) -> str:
    """Одна фраза с числами — для карточки аккаунта и ссылки со страницы поста."""
    data = finding.metrics
    if finding.kind == "early_pack":
        cohort = data.get("cohort", {})
        return (f"У {data['posts']} постов за {WINDOW_DAYS} дней доля реакций на просмотр в первые часы "
                f"в {_ru(data['median'])} раза выше, чем за остаток суток (у {round(100 * data['share'])} % постов — "
                f"больше чем в {PACK_POST_RATIO:.0f} раз); у типичного аккаунта площадки — "
                f"в {_ru(cohort.get('median', 0))} раза")
    if finding.kind == "regular_reactions":
        within = data.get("measure") == "day"
        text = (f"У {data['posts']} постов за {WINDOW_DAYS} дней к 72 часам от {data['p10Reactions']} до "
                f"{data['p90Reactions']} реакций (80 % постов) при медиане просмотров {_ru(data['medianViews'], 0)}; "
                f"разброс сверх случайного{' внутри дня публикации' if within else ''} — {_ru(data['extra'], 2)} "
                f"при медиане площадки {_ru(data.get('cohort', {}).get('median', 0), 2)}")
        if within:
            text += (f" (за весь месяц — {_ru(data['windowExtra'], 2)}: общий уровень менялся, а посты одного дня "
                     f"получали почти одинаково)")
        if data.get("subPoisson"):
            text += (f"; посты одного дня отличаются меньше, чем дал бы случай (χ² = {_ru(data['chi2'], 1)} "
                     f"при {data['chi2Df']} степенях свободы, p < 0,01) — у независимых людей так не бывает")
        return text
    if finding.kind == "late_growth":
        return (f"У {data['boosted']} из {data['posts']} постов реакции через 3–14 суток выросли втрое и больше "
                f"(медиана {_ru(data['medianDay'] or 0, 0)} → {_ru(data['medianLate'] or 0, 0)}); подряд — до "
                f"{data['run']} постов; у типичного аккаунта площадки — "
                f"{round(100 * data.get('cohort', {}).get('median', 0))} % постов")
    if finding.kind == "synchronous_waves":
        return (f"За {WINDOW_DAYS} дней — {_days(data['days'])}, когда реакции подросли одновременно у "
                f"{WAVE_MIN_POSTS} и больше постов аккаунта (до {data['maxPosts']} за день); в волнах — "
                f"{round(100 * data['share'])} % постов окна; у типичного аккаунта площадки — "
                f"{round(100 * data.get('cohort', {}).get('median', 0))} %")
    if finding.kind == "engagement_shift":
        cut = date.fromisoformat(data["cut"])
        text = (f"С {cut:%d.%m} доля реакций на просмотр у постов выросла в {_ru(data['ratio'])} раза "
                f"({_ru(100 * data['erBefore'])} % → {_ru(100 * data['erAfter'])} %), а просмотры — "
                f"{_ru(data['medianViewsBefore'], 0)} → {_ru(data['medianViewsAfter'], 0)}; "
                f"{round(100 * data['separation'])} % постов после этой даты выше 90 % постов двух недель до неё; "
                f"у типичного аккаунта площадки наибольший такой рост за месяц — в "
                f"{_ru(data.get('cohort', {}).get('median', 0))} раза")
        support = data.get("corroboration") or []
        if support:
            text += "; в те же дни отклик вырос и " + ", ".join(
                f"в {PLATFORM_TITLES.get(item['platform'], item['platform'])} (×{_ru(item['ratio'])})"
                for item in support)
        return text
    if finding.kind == "night_reactions":
        start = data["nightStartMsk"]
        text = (f"Ночью аудитории ({start:02d}:00–{(start + NIGHT_HOURS) % 24:02d}:00 МСК) приходит "
                f"{_ru(100 * data['reactionShare'])} % поздних реакций и только {_ru(100 * data['viewShare'])} % "
                f"поздних просмотров — в {_ru(data['lift'])} раза больше; у типичного аккаунта площадки — в "
                f"{_ru(data.get('cohort', {}).get('median', 0))} раза")
        if abs(data["shiftHours"]) > NIGHT_SHIFT_NOTE_HOURS:
            text += (f"; ночь определена по просмотрам: судя по ним, вуз в другом часовом поясе "
                     f"(≈ UTC{MOSCOW_UTC_OFFSET - data['shiftHours']:+d})")
        return text
    ratio = data.get("ratio") or data.get("k")
    return ("Поздний отклик на посты 4–28 суток устойчиво выше, чем у аккаунтов площадки"
            + (f" (поздняя доля реакций к ранней — {_ru(float(ratio), 2)})" if ratio else ""))


def _reaction_word(count: int) -> str:
    """Согласование с последним числом диапазона: 84 реакции, 85 реакций, 81 реакция."""
    if count % 10 == 1 and count % 100 != 11:
        return "реакция"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "реакции"
    return "реакций"


def _days(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} день"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} дня"
    return f"{count} дней"


def headline(finding: AccountFinding) -> str:
    """Короткая строка для свёрнутого вида: что происходит, одним предложением."""
    data = finding.metrics
    if finding.kind == "early_pack":
        return f"Пакет реакций в первые часы у {round(100 * data['share'])} % постов"
    if finding.kind == "regular_reactions":
        return (f"{data['p10Reactions']}–{data['p90Reactions']} {_reaction_word(data['p90Reactions'])} "
                f"у 80 % постов при любом охвате")
    if finding.kind == "late_growth":
        return f"У {round(100 * data['share'])} % постов реакции через дни выросли втрое и больше"
    if finding.kind == "synchronous_waves":
        return f"{_days(data['days'])} с волной реакций сразу на многих постах"
    if finding.kind == "engagement_shift":
        return (f"С {date.fromisoformat(data['cut']):%d.%m} реакций на просмотр в {_ru(data['ratio'])} раза "
                f"больше при тех же просмотрах")
    if finding.kind == "night_reactions":
        return (f"{_ru(100 * data['reactionShare'], 0)} % поздних реакций ночью при "
                f"{_ru(100 * data['viewShare'])} % просмотров")
    return "Старые посты получают реакции чаще, чем у других аккаунтов"


def figure(finding: AccountFinding) -> dict[str, Any] | None:
    """Аккаунт против типичного аккаунта площадки — одна мера для инфографики."""
    data = finding.metrics
    typical = (data.get("cohort") or {}).get("median")
    if finding.kind == "early_pack":
        value, unit, label, direction = data["median"], "times", "доля реакций: первые часы / остаток суток", "higher"
    elif finding.kind == "regular_reactions":
        value, unit, label, direction = data["extra"], "decimal", "разброс реакций сверх случайного", "lower"
    elif finding.kind == "late_growth":
        value, unit, label, direction = data["share"], "percent", "постов, добравших реакции через дни", "higher"
    elif finding.kind == "synchronous_waves":
        value, unit, label, direction = data["share"], "percent", "постов в волнах реакций", "higher"
    elif finding.kind == "engagement_shift":
        value, unit, label, direction = data["ratio"], "times", "рост доли реакций на просмотр", "higher"
    elif finding.kind == "night_reactions":
        value, unit, label, direction = data["lift"], "times", "доля реакций ночью к доле просмотров", "higher"
    else:
        value, unit, label, direction = data.get("ratio"), "times", "поздняя доля реакций к ранней", "higher"
    if value is None or typical is None:
        return None
    return {"value": value, "typical": typical, "unit": unit, "label": label, "direction": direction}


def with_texts(finding: AccountFinding) -> AccountFinding:
    """Находка со словами для API: заголовок, фраза с числами, статус, альтернативы.

    API модуль анализа не импортирует (ADR-014) и показывает сохранённые слова.
    """
    from dataclasses import replace
    return replace(finding, metrics={**finding.metrics, "title": finding.title, "summary": summary(finding),
                                     "headline": headline(finding), "figure": figure(finding),
                                     "statusLabel": STATUS_LABELS[finding.status],
                                     "alternatives": ALTERNATIVES[finding.kind], "members": len(finding.members)})
