"""Аккаунтные находки по охватам: пакеты и волны просмотров, суточный ритм, много постов уровня 3."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.reach_findings import PostLevel, level3_findings, view_pack_findings

TODAY = date(2026, 10, 8)


def posts(account: int, count: int, *, platform="vk", step_hours=7):
    """count чистых постов через `step_hours`, с 08.09."""
    start = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)
    return [PostLevel(UUID(int=account * 10_000 + i), UUID(int=account), platform,
                      start + timedelta(hours=step_hours * i), 0, frozenset(), False) for i in range(count)]


def spread(account, count, k, *, level3=False, packs=False, patterns=(9, 14), **kw):
    """k постов из count с признаком, равномерно по окну."""
    marked = set(range(0, count, max(1, count // k)))
    return [PostLevel(p.publication_id, p.account_id, p.platform, p.published_at,
                      3 if level3 and i in marked else 0,
                      frozenset(patterns) if level3 and i in marked else frozenset(),
                      packs and i in marked) for i, p in enumerate(posts(account, count, **kw))]


def cohort(n=12, count=60):
    return [p for a in range(2, 2 + n) for p in spread(a, count, 1, level3=True)]


def of(found, account=1):
    return [f for f in found if f.account_id == UUID(int=account)]


def test_many_level3_posts_in_both_halves_are_a_persistent_finding():
    (finding,) = of(level3_findings(cohort() + spread(1, 80, 40, level3=True), TODAY))
    assert finding.kind == "level3_share" and finding.status == 2 and len(finding.members) == 40


def test_level3_of_a_single_pattern_is_at_most_status_one():
    (finding,) = of(level3_findings(cohort() + spread(1, 80, 40, level3=True, patterns=(9,)), TODAY))
    assert finding.status == 1


def test_few_posts_give_no_level3_finding():
    assert not of(level3_findings(cohort() + spread(1, 15, 10, level3=True), TODAY))


def test_ordinary_share_of_level3_is_not_a_finding():
    assert not of(level3_findings(cohort() + spread(1, 60, 1, level3=True), TODAY))


def test_repeated_view_packs_are_a_finding():
    (finding,) = of(view_pack_findings(cohort() + spread(1, 80, 25, packs=True), TODAY))
    assert finding.kind == "view_packs" and finding.status == 2


def test_packs_in_one_week_only_are_not_persistent():
    early = datetime(2026, 9, 15, tzinfo=timezone.utc)
    items = [PostLevel(p.publication_id, p.account_id, p.platform, p.published_at, 0, frozenset(),
                       p.view_pack and p.published_at < early) for p in spread(1, 80, 80, packs=True)]
    found = of(view_pack_findings(cohort() + items, TODAY))
    assert found and all(f.status == 1 for f in found)


def test_a_few_packs_are_not_a_finding():
    assert not of(view_pack_findings(cohort() + spread(1, 80, 4, packs=True), TODAY))
