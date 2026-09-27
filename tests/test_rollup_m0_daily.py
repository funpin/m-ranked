import runpy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID


SCRIPT = Path(__file__).resolve().parents[1] / (
    "research/smart-engagement-2026-09/scripts/rollup_m0_daily.py"
)
summarize = runpy.run_path(str(SCRIPT))["_summarize"]
START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def receipt(post: int, minutes: int, count: int, *,
            quality: str = "exact", unit: int | None = None):
    return {
        "publication_id": UUID(int=post), "primary_account_id": UUID(int=1),
        "published_at": START, "platform": "max",
        "observed_at": START + timedelta(minutes=minutes),
        "views_count": count, "views_quality": quality,
        "interval_uncertain": False, "views_display_unit": unit,
    }


def test_rollup_uses_only_consecutive_successful_bounded_pairs():
    rows = [
        receipt(10, 60, 1000), receipt(10, 75, 1200),
        receipt(10, 90, 1200),
        receipt(11, 60, 1000, quality="rounded"),
        receipt(11, 75, 1300, quality="rounded"),
    ]
    daily, statuses, posts = summarize(
        rows, START.date(), (START + timedelta(days=1)).date(),
        timedelta(minutes=30),
    )
    assert posts == 2
    assert statuses == {"bounded": 2, "unknown_rounding_precision": 1}
    assert len(daily) == 1
    assert daily[0].publication_id == UUID(int=10)
    assert 800 < daily[0].upper_rate_per_hour < 800.000000001
    assert daily[0].source == "successful_poll_receipts"
