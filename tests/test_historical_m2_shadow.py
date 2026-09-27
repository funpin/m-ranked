"""The archive diagnostic must not pick each post's most extreme interval."""

from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID


SCRIPT = (Path(__file__).resolve().parents[1] / "research" /
          "smart-engagement-2026-09" / "scripts" / "run_historical_m2_shadow.py")
spec = spec_from_file_location("historical_m2_shadow", SCRIPT)
assert spec and spec.loader
module = module_from_spec(spec)
spec.loader.exec_module(module)


def pair(post_id: int, minute: int, m1: float, m2: float,
         *, event: bool = True, ranked: bool = True):
    end_at = datetime(2026, 9, 21, 12, tzinfo=timezone.utc) + timedelta(minutes=minute)
    row = SimpleNamespace(interval=SimpleNamespace(publication_id=UUID(int=post_id),
                                                   end_at=end_at),
                          nearest_event_distance=1 if event else None)
    status = "ranked" if ranked else "insufficient_calibration"
    result = SimpleNamespace(m1=SimpleNamespace(status=status, upper_tail_rank=m1),
                             m2=SimpleNamespace(status=status, upper_tail_rank=m2))
    return row, result


def test_first_event_per_post_uses_time_not_smallest_rank():
    first = pair(1, 5, .20, .04)
    later = pair(1, 10, .001, .001)
    other = pair(2, 15, .03, .30)
    no_event = pair(3, 5, .001, .001, event=False)
    unusable = pair(4, 5, .001, .001, ranked=False)
    pairs = (later, no_event, other, unusable, first)
    summary = module._first_comparable_event_per_post(
        tuple(row for row, _ in pairs), tuple(result for _, result in pairs))
    assert summary["posts"] == 2
    assert summary["m1_small_tail_posts"] == 1
    assert summary["m2_small_tail_posts"] == 1
    assert summary["m1_only"] == 1
    assert summary["m2_only"] == 1
