"""Аккаунтные находки: закономерность, видимая только на многих постах сразу.

Пост сравнивается сам с собой, и слабая статистика одного поста не даёт
уверенного вывода: 60 реакций в первые два часа и почти ничего потом — у
небольшой аудитории это может быть и случайностью. Если же так выглядят
почти все посты аккаунта месяц подряд, а у других аккаунтов площадки нет,
это уже закономерность. Находка относится к аккаунту, считается отдельно от
уровней постов и показывается на постах, из которых она складывается.

Виды:

* ``early_pack`` — повторяющийся стартовый пакет: доля реакций на просмотр в
  первые два часа во много раз выше доли за следующие сутки. У живой
  аудитории она выше в 1,5–2 раза (медиана когорты 1,5 в MAX и 1,0 в ВК по
  постам 12.09–05.10.2026); у аккаунта с находкой — больше чем в пять раз у
  типичного поста и больше чем в восемь у большинства.
* ``regular_reactions`` — слишком ровный отклик: число реакций к 72 часам
  почти не меняется от поста к посту. Разброс сверх пуассоновского шума
  (sd log R за вычетом 1/R) у живых аккаунтов отражает разный интерес к
  разным постам — медиана когорты MAX 0,35. Около нуля он означает, что
  содержание поста на число реакций не влияет.
* ``late_engagement`` — устойчиво необычный поздний отклик из профиля
  account_tail (ADR-015); участники — посты окна с поздним приростом.

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

from .tail_ledger import Point, TailLedger

METHOD_VERSION = "account-findings-v1"
WINDOW_DAYS = 30
STATUS_LABELS = {1: "необычный", 2: "устойчиво необычный"}
TITLES = {
    "early_pack": "Повторяющийся стартовый пакет реакций",
    "regular_reactions": "Слишком ровный отклик",
    "late_engagement": "Необычный поздний отклик",
}
ALTERNATIVES = {
    "early_pack": ("Подписчики-активисты реагируют сразу после публикации, а поздние читатели почти не "
                   "реагируют; рассылка поста в профильные чаты в первые минуты"),
    "regular_reactions": ("Стабильное ядро аудитории, которое реагирует на каждый пост одинаково; "
                          "однотипные посты по расписанию"),
    "late_engagement": "Регулярные читатели архива, подборки и пересылки старых постов",
}

# Стартовый пакет: окна «первые 2 ч» и «2–24 ч» по отметкам сводки.
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
MIN_HALF_POSTS = 7


@dataclass(frozen=True, slots=True)
class LedgerPost:
    publication_id: UUID
    account_id: UUID
    platform: str
    published_at: datetime
    is_repost: bool
    ledger: TailLedger


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
    """Во сколько раз доля реакций в первые 2 ч выше доли за 2–24 ч; None — мало данных."""
    early, day = ledger.marks.get("h2"), ledger.marks.get("h24")
    if early is None or day is None:
        return None
    r1, v1 = early.reactions, early.views
    r2, v2 = max(0, day.reactions - early.reactions), max(0, day.views - early.views)
    if r1 + r2 < PACK_MIN_REACTIONS or v1 < PACK_MIN_EARLY_VIEWS or v2 < PACK_MIN_LATER_VIEWS:
        return None
    return (r1 / v1) / max(r2 / v2, 0.5 / v2), r1, v1, r2, v2


def findings(posts: Iterable[LedgerPost], computed_for: date,
             late_members: Mapping[UUID, Sequence[UUID]] | None = None,
             tail_status: Mapping[UUID, tuple[str, int, Mapping[str, Any]]] | None = None) -> list[AccountFinding]:
    """Находки по постам окна [computed_for − 30 сут; computed_for).

    `tail_status` — статус профиля позднего отклика аккаунта (площадка, статус,
    метрики), `late_members` — посты окна с поздним приростом реакций.
    """
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account: dict[UUID, list[LedgerPost]] = {}
    for post in posts:
        if start <= post.published_at.date() < computed_for:
            by_account.setdefault(post.account_id, []).append(post)
    result: list[AccountFinding] = []
    pack_cohort = _cohort(by_account, _pack_stats)
    regular_cohort = _cohort(by_account, _regular_stats)
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
            halves = [_regular_stats(half, min_posts=MIN_HALF_POSTS) for half in _halves(items)]
            status = 2 if all(item is not None and item["extra"] <= REGULAR_HALF_EXTRA for item in halves) else 1
            metrics = {**_public(regular), "cohort": _without(regular_cohort.get(platform, {}), "medians")}
            result.append(AccountFinding(account, platform, "regular_reactions", status, start, computed_for,
                                         metrics, tuple(regular["members"])))
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


def _regular_stats(items: Sequence[LedgerPost], min_posts: int = REGULAR_MIN_POSTS) -> dict[str, Any] | None:
    rows = [(post.publication_id, mark) for post in items
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
    return {
        "posts": len(rows), "extra": round(math.sqrt(max(variance - poisson, 0.0)), 4),
        "sdLogReactions": round(math.sqrt(variance), 4),
        "sdLogViews": round(math.sqrt(sum((value - view_mean) ** 2 for value in view_logs) / len(view_logs)), 4),
        "medianReactions": median(reactions), "medianViews": median(views),
        "p10Reactions": ordered[len(ordered) // 10], "p90Reactions": ordered[(9 * len(ordered)) // 10],
        "members": [publication for publication, _ in rows],
    }


def _cohort(by_account, measure) -> dict[str, dict[str, Any]]:
    values: dict[str, list[float]] = {}
    for items in by_account.values():
        stats = measure(items)
        if stats is not None:
            key = "median" if "median" in stats else "extra"
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


def summary(finding: AccountFinding) -> str:
    """Одна фраза с числами — для карточки аккаунта и ссылки со страницы поста."""
    data = finding.metrics
    if finding.kind == "early_pack":
        cohort = data.get("cohort", {})
        return (f"У {data['posts']} постов за {WINDOW_DAYS} дней доля реакций на просмотр в первые 2 часа "
                f"в {data['median']:.1f} раза выше, чем за следующие сутки (у {data['share']:.0%} постов — "
                f"больше чем в {PACK_POST_RATIO:.0f} раз); у типичного аккаунта площадки — "
                f"в {cohort.get('median', 0):.1f} раза")
    if finding.kind == "regular_reactions":
        return (f"У {data['posts']} постов за {WINDOW_DAYS} дней к 72 часам от {data['p10Reactions']} до "
                f"{data['p90Reactions']} реакций (80 % постов) при медиане просмотров {data['medianViews']}; "
                f"разброс сверх случайного — {data['extra']:.2f} при медиане площадки "
                f"{data.get('cohort', {}).get('median', 0):.2f}")
    ratio = data.get("ratio") or data.get("k")
    return ("Поздний отклик на посты 4–28 суток устойчиво выше, чем у аккаунтов площадки"
            + (f" (отношение поздней доли к ранней {ratio})" if ratio else ""))


def with_texts(finding: AccountFinding) -> AccountFinding:
    """Находка со словами для API: заголовок, фраза с числами, статус, альтернативы.

    API модуль анализа не импортирует (ADR-014) и показывает сохранённые слова.
    """
    from dataclasses import replace
    return replace(finding, metrics={**finding.metrics, "title": finding.title, "summary": summary(finding),
                                     "statusLabel": STATUS_LABELS[finding.status],
                                     "alternatives": ALTERNATIVES[finding.kind], "members": len(finding.members)})
