"""Просмотры, которые не входят в сумму «без волн и всплесков» на /compare."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from anomaly_analysis.v2.account_findings import AccountFinding, LedgerPost
from anomaly_analysis.v2.detectors.view_burst_response import MIN_SURPRISE
from anomaly_analysis.v2.reach_findings import account_waves, view_discounts, wave_findings
from anomaly_analysis.v2.tail_ledger import TailLedger
from api.sql import compare
from test_reach_findings import TODAY, WAVES, wall

PUBLISHED = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
FINDING = AccountFinding(UUID(int=9), "vk", "view_waves", 1, TODAY, TODAY, {}, ())


def _post(index: int, burst=None) -> LedgerPost:
    ledger = TailLedger(None, None, None, burst=burst)
    return LedgerPost(UUID(int=index), UUID(int=9), "vk", PUBLISHED, False, ledger)


def test_post_without_waves_or_a_decoupled_burst_has_no_discount():
    posts = [_post(1), _post(2, ("coupled", 0.9, 5000, 0.0)), _post(3, ("intermediate", 0.3, 5000, 9.0))]
    assert view_discounts(posts, []) == {UUID(int=index): None for index in (1, 2, 3)}


def test_decoupled_burst_counts_only_when_it_is_shown_as_a_sign():
    posts = [_post(1, ("decoupled", 0.1, 5000, MIN_SURPRISE)), _post(2, ("decoupled", 0.1, 5000, MIN_SURPRISE - 1))]
    assert view_discounts(posts, []) == {UUID(int=1): 5000, UUID(int=2): None}


def test_wave_and_burst_on_one_post_are_not_counted_twice():
    post = _post(1, ("decoupled", 0.1, 5000, MIN_SURPRISE))
    assert view_discounts([post], [(FINDING, {UUID(int=1): 800})]) == {UUID(int=1): 5000}
    assert view_discounts([post], [(FINDING, {UUID(int=1): 7000})]) == {UUID(int=1): 7000}


def test_wave_views_by_post_add_up_to_the_finding():
    posts = wall(1, waves=WAVES) + [post for account in range(2, 12) for post in wall(account)]
    waves = account_waves(posts, TODAY)
    assert [finding for finding, _ in waves] == wave_findings(posts, TODAY)
    (finding, by_post), = [item for item in waves if item[0].account_id == UUID(int=1)]
    assert sum(by_post.values()) == finding.metrics["views"]
    assert set(by_post) == set(finding.members)


def test_vk_video_is_left_out_of_engagement_only():
    assert "publication.publication_type = 'video'" in compare._ENGAGEMENT24
    assert "account.platform = 'vk'" in compare._ENGAGEMENT24
    assert "views_adjusted" in compare.DASHBOARD
