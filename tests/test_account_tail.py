"""Профиль позднего отклика аккаунта относительно аккаунтов площадки."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import UUID

from anomaly_analysis.v2.account_tail import PostLedger, profiles, window_end
from anomaly_analysis.v2.tail_ledger import DAY, Point, TailLedger

COMPUTED_FOR = date(2026, 9, 29)
END = window_end(COMPUTED_FOR)


def _post(account: int, index: int, age_days: float, *, early=(1000, 30), late=(200, 1), growth_days=()):
    published = END - timedelta(days=age_days)
    days = tuple((published + timedelta(days=offset)).date().isoformat() for offset in range(5, 14)
                 if published + timedelta(days=offset + 1) <= END)
    ledger = TailLedger(Point(DAY, *early), Point(4 * DAY, early[0] + 100, early[1] + 2),
                        Point(13 * DAY, early[0] + 100 + late[0], early[1] + 2 + late[1]), days,
                        {day: 1 for day in days if day in growth_days})
    return PostLedger(UUID(int=account * 1000 + index), UUID(int=account), "max", published, ledger)


def _account(account: int, *, late=(200, 1), posts=16, growth_days=()):
    # Посты раз в два с половиной дня: половина — «ранние», половина — «свежие».
    return [_post(account, index, 5 + 2.3 * index, late=late, growth_days=growth_days) for index in range(posts)]


def _cohort(size=20):
    posts, accounts = [], {}
    for account in range(1, size + 1):
        # Обычные аккаунты: поздняя доля — 10–25 % ранней (ранняя 3 %).
        posts += _account(account, late=(200, 1 + account % 4))
        accounts[UUID(int=account)] = "max"
    return posts, accounts


def _by_id(result):
    return {item.account_id: item for item in result}


def test_ordinary_accounts_are_not_marked_and_the_threshold_comes_from_other_accounts():
    posts, accounts = _cohort()
    result = _by_id(profiles(posts, accounts, COMPUTED_FOR))
    assert {item.status for item in result.values()} == {0}
    cohort = result[UUID(int=1)].metrics["cohort"]
    assert cohort["accounts"] == 20 and cohort["threshold"] >= 3 * cohort["median"] - 1e-3


def test_a_constant_late_addition_over_the_whole_history_is_not_absorbed():
    posts, accounts = _cohort()
    # Весь период — и ранние, и свежие посты — старые посты получают реакции
    # почти без новых просмотров. Собственная история здесь «такая всегда».
    all_days = {(END - timedelta(days=offset)).date().isoformat() for offset in range(1, 29)}
    posts += _account(99, late=(200, 30), growth_days=all_days)
    accounts[UUID(int=99)] = "max"
    profile = _by_id(profiles(posts, accounts, COMPUTED_FOR))[UUID(int=99)]
    assert profile.status == 2
    assert profile.metrics["ratio"] > 1 and profile.metrics["activeWeeks"] >= 2
    assert profile.metrics["cohort"]["rank"] == 1.0


def test_one_archive_session_is_unusual_but_not_persistent():
    posts, accounts = _cohort()
    one_day = {(END - timedelta(days=3)).date().isoformat()}
    posts += _account(98, late=(200, 30), growth_days=one_day)
    accounts[UUID(int=98)] = "max"
    profile = _by_id(profiles(posts, accounts, COMPUTED_FOR))[UUID(int=98)]
    assert profile.status == 1
    assert profile.metrics["activeDays"] <= 1


def test_a_handful_of_late_reactions_is_not_a_status():
    posts, accounts = _cohort()
    posts += _account(97, late=(5, 1), posts=10)
    accounts[UUID(int=97)] = "max"
    profile = _by_id(profiles(posts, accounts, COMPUTED_FOR))[UUID(int=97)]
    assert profile.metrics["lateReactions"] < 20 and profile.status == 0


def test_abstentions_have_reasons_instead_of_quiet_statuses():
    posts, accounts = _cohort(size=10)
    posts += _account(96, posts=3)
    accounts[UUID(int=96)] = "max"
    accounts[UUID(int=95)] = "vk"
    result = _by_id(profiles(posts, accounts, COMPUTED_FOR))
    assert result[UUID(int=96)].status is None and result[UUID(int=96)].abstain_reason == "few_posts"
    assert result[UUID(int=95)].abstain_reason == "few_posts"
    # Десять аккаунтов площадки — мало для сравнения.
    assert result[UUID(int=1)].abstain_reason == "small_cohort"
    assert result[UUID(int=1)].metrics["abstainText"]


def test_posts_outside_the_window_and_ledgers_without_endpoints_are_ignored():
    posts, accounts = _cohort()
    young = _post(1, 900, 2)
    old = _post(1, 901, 50)
    empty = PostLedger(UUID(int=902), UUID(int=1), "max", END - timedelta(days=10), TailLedger(None, None, None))
    before = _by_id(profiles(posts, accounts, COMPUTED_FOR))[UUID(int=1)].metrics
    after = _by_id(profiles(posts + [young, old, empty], accounts, COMPUTED_FOR))[UUID(int=1)].metrics
    assert after["posts"] == before["posts"]


def test_daily_breadth_is_described_with_its_denominator():
    posts, accounts = _cohort()
    day = (END - timedelta(days=6)).date().isoformat()
    posts += _account(94, late=(200, 30), growth_days={day})
    accounts[UUID(int=94)] = "max"
    metrics = _by_id(profiles(posts, accounts, COMPUTED_FOR))[UUID(int=94)].metrics
    [entry] = [item for item in metrics["days"] if item["day"] == day]
    assert entry["observed"] >= entry["active"] > 0 and entry["reactions"] == entry["active"]
    assert len(metrics["days"]) == 21 and metrics["windowEnd"] == (END - timedelta(days=1)).date().isoformat()
    assert isinstance(END, datetime)
