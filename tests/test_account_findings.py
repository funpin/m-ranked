from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import random
from uuid import UUID

from anomaly_analysis.v2.account_findings import (
    PACK_MIN_POSTS, REGULAR_MIN_POSTS, LedgerPost, findings, pack_ratio, summary,
)
from anomaly_analysis.v2.tail_ledger import Point, TailLedger

TODAY = date(2026, 10, 6)
HOUR = 3600


def post(account: int, index: int, h2: tuple[int, int], h24: tuple[int, int], h72: tuple[int, int] | None = None,
         platform: str = "max", repost: bool = False) -> LedgerPost:
    marks = {"h2": Point(2 * HOUR, *h2), "h24": Point(24 * HOUR, *h24)}
    if h72 is not None:
        marks["h72"] = Point(72 * HOUR, *h72)
    published = datetime(2026, 9, 7, 9, tzinfo=timezone.utc) + timedelta(hours=7 * index)
    return LedgerPost(UUID(int=account * 10_000 + index), UUID(int=account), platform, published, repost,
                      TailLedger(None, None, None, marks=marks))


def organic(account: int, count: int, rng: random.Random, platform: str = "max") -> list[LedgerPost]:
    """Живая аудитория: доля в первые 2 ч чуть выше суточной, реакции растут с охватом."""
    posts = []
    for index in range(count):
        v2 = rng.randint(200, 400)
        v24 = v2 + rng.randint(300, 600)
        quality = rng.lognormvariate(0, 0.4)
        r2 = round(v2 * 0.08 * quality)
        r24 = r2 + round((v24 - v2) * 0.05 * quality)
        posts.append(post(account, index, (v2, r2), (v24, r24), (v24 + 100, r24 + 3), platform))
    return posts


def test_pack_ratio_compares_first_two_hours_with_the_rest_of_the_day():
    # 60 реакций на 250 просмотров, затем 4 на 400: доля упала в ~24 раза.
    ratio, *_ = pack_ratio(post(1, 0, (250, 60), (650, 64)).ledger)
    assert 20 < ratio < 30
    assert pack_ratio(post(1, 0, (5, 1), (10, 2)).ledger) is None


def test_pack_lasting_several_hours_is_measured_at_six_hours():
    # ГУАП в MAX: 36 реакций на 220 просмотров к 2 ч, 59 на 334 к 6 ч, затем
    # +1 на 120. Двухчасовое окно делило пакет пополам и видело лишь ~1,6 раза.
    ledger = TailLedger(None, None, None, marks={
        "h2": Point(2 * HOUR, 221, 36), "h6": Point(6 * HOUR, 334, 59), "h24": Point(24 * HOUR, 452, 60)})
    ratio, r1, v1, *_ = pack_ratio(ledger)
    assert (r1, v1) == (59, 334) and ratio > 20


def test_repeated_early_pack_is_found_and_names_its_posts():
    rng = random.Random(3)
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    packed = [post(1, index, (250, 60 + index % 7), (650, 62 + index % 7), (800, 64)) for index in range(40)]
    result = findings(cohort + packed, TODAY)
    (finding,) = [item for item in result if item.kind == "early_pack"]
    assert finding.account_id == UUID(int=1) and finding.status == 2
    assert set(finding.members) == {item.publication_id for item in packed}
    assert finding.metrics["cohort"]["median"] < 3 and finding.metrics["median"] > 10
    assert "первые часы" in summary(finding)


def test_too_few_posts_or_organic_accounts_give_no_finding():
    rng = random.Random(5)
    few = [post(1, index, (250, 60), (650, 62)) for index in range(PACK_MIN_POSTS - 1)]
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    assert findings(few + cohort, TODAY) == []


def test_regular_reactions_flag_counts_that_ignore_post_appeal():
    rng = random.Random(7)
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    # Охват от 400 до 1 300, а реакций к 72 часам — пуассоновский шум вокруг 75.
    regular = []
    for index in range(REGULAR_MIN_POSTS + 10):
        views = rng.randint(400, 1300)
        reactions = max(1, round(rng.gauss(75, 75 ** 0.5)))
        regular.append(post(1, index, (views // 3, reactions // 2), (views, reactions - 2), (views + 50, reactions)))
    result = findings(cohort + regular, TODAY)
    kinds = {(item.account_id, item.kind) for item in result}
    assert (UUID(int=1), "regular_reactions") in kinds
    assert not any(account != UUID(int=1) for account, _ in kinds)


def test_reposts_count_for_packs_but_not_for_regularity():
    packed = [post(1, index, (250, 60), (650, 62), (800, 64), repost=True) for index in range(40)]
    result = findings(packed, TODAY)
    assert {item.kind for item in result} == {"early_pack"}


def test_persistently_unusual_tail_profile_becomes_a_finding_with_late_posts():
    members = {UUID(int=1): [UUID(int=11), UUID(int=12)]}
    tail = {UUID(int=1): ("max", 2, {"ratio": 0.65}), UUID(int=2): ("max", 1, {"ratio": 0.4})}
    # Пост с округлёнными счётчиками без признака: по сводке поздняя доля втрое выше ранней.
    late = post(1, 0, (250, 20), (600, 30))
    late = LedgerPost(late.publication_id, late.account_id, late.platform, late.published_at, False,
                      TailLedger(Point(24 * HOUR, 600, 30), Point(4 * 24 * HOUR, 700, 31), Point(10 * 24 * HOUR, 900, 61)))
    result = findings([late], TODAY, members, tail)
    (finding,) = result
    assert finding.kind == "late_engagement"
    assert finding.members == (UUID(int=11), UUID(int=12), late.publication_id)


def test_posts_outside_the_thirty_day_window_are_ignored():
    old = [post(1, index, (250, 60), (650, 62)) for index in range(40)]
    shifted = [LedgerPost(item.publication_id, item.account_id, item.platform,
                          item.published_at - timedelta(days=60), item.is_repost, item.ledger) for item in old]
    assert findings(shifted, TODAY) == []


def test_posts_that_gain_reactions_days_later_are_a_finding():
    from anomaly_analysis.v2.account_findings import headline, figure, with_texts
    rng = random.Random(9)
    cohort = [item for account in range(2, 12) for item in organic(account, 40, rng)]
    boosted = []
    for index in range(30):
        base = post(1, index, (300, 8), (600, 10), (900, 12))
        # К суткам 10 реакций, к 10-м суткам — 360: докачка через дни.
        ledger = TailLedger(Point(24 * HOUR, 600, 10), Point(4 * 24 * HOUR, 900, 12), Point(10 * 24 * HOUR, 7000, 360),
                            marks=base.ledger.marks)
        boosted.append(LedgerPost(base.publication_id, base.account_id, "vk", base.published_at, False, ledger))
    organic_vk = [LedgerPost(item.publication_id, item.account_id, "vk", item.published_at, False,
                             TailLedger(item.ledger.marks["h24"], item.ledger.marks["h72"], item.ledger.marks["h72"],
                                        marks=item.ledger.marks)) for item in cohort]
    result = findings(boosted + organic_vk, TODAY)
    (finding,) = [item for item in result if item.kind == "late_growth"]
    assert finding.account_id == UUID(int=1) and finding.status == 2 and len(finding.members) == 30
    texts = with_texts(finding).metrics
    assert texts["headline"].startswith("У 100 % постов") and texts["figure"]["unit"] == "percent"
    assert texts["figure"]["typical"] == 0.0
