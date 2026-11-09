"""Находки этапа 4: организованный отклик, причины продвижения, связь реакций с просмотрами, волны."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.account_findings import LedgerPost, SynchronyEvent, findings, summary, with_texts
from anomaly_analysis.v2.reach_findings import (
    promotion_findings, promotion_reasons, response_link_findings, wave_findings,
)
from anomaly_analysis.v2.tail_ledger import DAY, HOUR, Point, TailLedger, ledger_from_payload

TODAY = date(2026, 11, 1)
BASE = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)


def marks(views: int, reactions: int, early: int | None = None) -> dict:
    return {"h6": Point(6 * HOUR, early if early is not None else views // 3, reactions // 3),
            "h72": Point(3 * DAY, views, reactions)}


def post(account: int, index: int, views=2000, reactions=30, *, early=None, comments=0, burst=None, days=(),
         platform="vk", hours=None, kind="photo", institution=None):
    ledger = TailLedger(None, None, None, marks=marks(views, reactions, early), comments72=comments, burst=burst, days=days,
                        hours=hours)
    return LedgerPost(UUID(int=account * 10_000 + index), UUID(int=account), platform, BASE + timedelta(hours=6 * index),
                      False, ledger, institution, kind)


STAIR = (("2026-10-10", 1000, 5, 80), ("2026-10-11", 700, 4, 50), ("2026-10-12", 500, 3, 40), ("2026-10-13", 350, 2, 30))


def test_ledger_keeps_comments_and_burst():
    ledger = TailLedger(None, None, None, comments72=7, burst=("coupled", 1.6, 900, 0.3))
    restored = ledger_from_payload(ledger.payload())
    assert restored.comments72 == 7 and restored.burst == ("coupled", 1.6, 900, 0.3)


def test_reasons_keep_live_late_start_and_drop_decoupled_ones():
    assert promotion_reasons(post(1, 0, 5000, 30, early=100)) == {"late_start"}
    assert not promotion_reasons(post(1, 1, 5000, 30, early=100, burst=("decoupled", 0.05, 3000, 9.0)))
    assert not promotion_reasons(post(1, 2, 1500, 30, early=10))


def test_live_burst_and_staircase_are_reasons():
    assert promotion_reasons(post(1, 0, burst=("coupled", 0.9, 900, 0.1))) == {"live_burst"}
    assert promotion_reasons(post(1, 1, burst=("intermediate", 0.3, 900, 1.0))) == {"live_burst"}
    assert promotion_reasons(post(1, 2, days=STAIR)) == {"staircase"}


def test_video_is_not_judged():
    assert not promotion_reasons(post(1, 0, 5000, 30, early=100, kind="video"))


def _promoted(count=30):
    return [post(1, index, 9000, 60, early=200) for index in range(count)]


def _cohort():
    return [post(account, index, 900, 20) for account in range(2, 14) for index in range(30)]


def test_high_reach_with_reasons_marks_the_account_and_its_posts():
    subscribers = {UUID(int=a): 10_000 for a in range(1, 14)}
    (finding,) = [item for item in promotion_findings(_promoted() + _cohort(), TODAY, subscribers)
                  if item.account_id == UUID(int=1)]
    assert finding.kind == "promotion" and finding.status == 1 and len(finding.members) == 30
    text = with_texts(finding).metrics["summary"]
    assert "рекомендации" in text and "накрут" not in text and "бот" not in text


def test_reasons_without_high_reach_are_not_a_finding():
    subscribers = {UUID(int=1): 1_000_000, **{UUID(int=a): 10_000 for a in range(2, 14)}}
    assert not promotion_findings(_promoted() + _cohort(), TODAY, subscribers)


def test_a_very_high_response_is_not_promotion():
    subscribers = {UUID(int=a): 10_000 for a in range(1, 14)}
    loud = [post(1, index, 9000, 900, early=200) for index in range(30)]
    assert not [item for item in promotion_findings(loud + _cohort(), TODAY, subscribers)
                if item.account_id == UUID(int=1)]


def _audience_hours():
    return tuple(100 if 6 <= hour <= 20 else 5 for hour in range(24)), tuple([0] * 24)


def _organized_account(*, comments=20, reactions=200):
    return [post(1, index, 2000, reactions, comments=comments, hours=_audience_hours()) for index in range(40)]


def _organized_cohort():
    return [post(account, index, 2000, 30, hours=_audience_hours()) for account in range(2, 14) for index in range(40)]


def _waves(days: int, hour_utc=9):
    return [SynchronyEvent(UUID(int=1), "vk", UUID(int=10_000 + post_index), datetime(2026, 10, 10 + day, hour_utc, tzinfo=timezone.utc))
            for day in range(days) for post_index in range(12)]


def _kinds(found):
    return [item for item in found if item.kind == "organized_response" and item.account_id == UUID(int=1)]


def test_high_erv_with_comments_and_daytime_waves_is_organized_response():
    (finding,) = _kinds(findings(_organized_account() + _organized_cohort(), TODAY, synchrony=_waves(3)))
    assert finding.status == 1 and finding.metrics["ervRatio"] >= 2.5
    assert "накрут" not in summary(finding) and "бот" not in summary(finding)


def test_comments_alone_are_not_organized_response():
    assert not _kinds(findings(_organized_account() + _organized_cohort(), TODAY))


def test_night_waves_do_not_count_as_workday_waves():
    assert not _kinds(findings(_organized_account() + _organized_cohort(), TODAY, synchrony=_waves(3, hour_utc=23)))


def test_ordinary_erv_is_not_organized_response():
    assert not _kinds(findings(_organized_account(reactions=30) + _organized_cohort(), TODAY, synchrony=_waves(3)))


def test_same_shift_on_another_network_is_required_for_the_steady_status():
    (finding,) = _kinds(findings(_organized_account() + _organized_cohort(), TODAY, synchrony=_waves(3)))
    assert finding.status != 2


def _linked(account, index, spread):
    views = 500 * 2 ** (index % 6)
    return post(account, index, views, int(views * 0.02) if spread else 20 + (index * 7) % 13)


def test_views_growing_apart_from_reactions_are_a_weak_finding():
    posts = [_linked(1, index, False) for index in range(36)]
    posts += [_linked(account, index, True) for account in range(2, 20) for index in range(36)]
    (finding,) = [item for item in response_link_findings(posts, TODAY) if item.account_id == UUID(int=1)]
    assert finding.kind == "reaction_view_link" and finding.status == 1 and finding.metrics["correlation"] < 0.5


def test_too_few_posts_give_no_link_finding():
    posts = [_linked(1, index, False) for index in range(20)]
    posts += [_linked(account, index, True) for account in range(2, 20) for index in range(36)]
    assert not [item for item in response_link_findings(posts, TODAY) if item.account_id == UUID(int=1)]


def _wall(account, covered):
    result = []
    hour = int(datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp() // 3600)
    for index in range(40):
        surges = ((hour, 500, 0),) if index % 3 == 0 and index < covered else ()
        ledger = TailLedger(Point(DAY, 1000, 30), Point(4 * DAY, 2000, 60), Point(10 * DAY, 3000, 90), surges=surges)
        result.append(LedgerPost(UUID(int=account * 10_000 + index), UUID(int=account), "vk",
                                 datetime(2026, 10, 19, tzinfo=timezone.utc) - timedelta(hours=8 * index), False, ledger))
    return result


def test_a_wave_over_every_third_post_is_still_a_wave():
    (finding,) = [item for item in wave_findings(_wall(1, 33) + _wall(2, 0), TODAY) if item.account_id == UUID(int=1)]
    assert finding.metrics["viewsWithoutWaves"] < finding.metrics["viewsWithoutWaves"] + finding.metrics["views"]
