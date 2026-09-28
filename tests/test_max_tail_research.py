"""Observation eligibility, rather than a test of fitted research coefficients."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "research/smart-engagement-2026-09/scripts/analyze_max_tail.py"
SPEC = importlib.util.spec_from_file_location("max_tail_research", SCRIPT)
TAIL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TAIL)


def fixture():
    def snapshot(day, views, reactions):
        return dict(day=day, observed_at=day+"T20:00:00+00:00", v=views, r=reactions,
                    vq="exact", rq="exact", uncertain=False)
    before, after = snapshot("2026-09-13", 100, 10), snapshot("2026-09-14", 130, 10)
    published = TAIL.dt("2026-09-09T20:00:00+00:00")
    post = dict(post=dict(id="p", primary_account_id="a", is_repost=False, publication_type="text"),
                published=published, daily_by_day={before["day"]: before, after["day"]: after},
                early24=snapshot("2026-09-10", 60, 8))
    return post, {"a": [published]}


def test_real_zero_is_observed_but_missing_day_is_not_zero():
    post, clocks = fixture()
    rows, _, audit, _ = TAIL.intervals([post], clocks)
    assert len(rows) == 1 and rows[0]["dr"] == 0 and rows[0]["dv"] == 30
    assert rows[0]["actual_start_age"] == 4
    assert audit["missing_endpoint"] > 0
    del post["daily_by_day"]["2026-09-13"]
    assert not TAIL.intervals([post], clocks)[0]


@pytest.mark.parametrize("field,value,reason", [
    ("observed_at", "2026-09-14T17:00:00+00:00", "stale_endpoint"),
    ("r", 9, "negative_net_change"),
    ("v", 99, "negative_net_change"),
    ("rq", "rounded", "not_exact_or_uncertain"),
    ("v", None, "not_exact_or_uncertain"),
    ("uncertain", True, "not_exact_or_uncertain"),
])
def test_bad_boundaries_are_excluded_not_carried(field, value, reason):
    post, clocks = fixture()
    post["daily_by_day"]["2026-09-14"][field] = value
    rows, _, audit, _ = TAIL.intervals([post], clocks)
    assert not rows and audit[reason] == 1


def test_early_covariate_never_uses_a_future_measurement():
    post, clocks = fixture()
    post["early24"]["observed_at"] = "2026-09-14T19:00:00+00:00"
    rows = TAIL.intervals([post], clocks)[0]
    assert len(rows) == 1 and rows[0]["q24"] is None


def test_reposts_are_a_separate_sensitivity():
    post, clocks = fixture()
    post["post"]["is_repost"] = True
    assert not TAIL.intervals([post], clocks)[0]
    assert len(TAIL.intervals([post], clocks, reposts=True)[0]) == 1
