from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from migration.bridge.reconciliation import compare_rows, encode


def test_canonical_serialization_keeps_null_zero_and_normalizes_utc_numeric():
    utc = datetime(2026, 9, 5, 10, tzinfo=timezone.utc)
    moscow = utc.astimezone(timezone(timedelta(hours=3)))
    assert encode({"t": utc, "n": Decimal("1.2500")}) == encode({"n": 1.25, "t": moscow})
    assert encode({"n": None}) != encode({"n": 0})
    with pytest.raises(ValueError, match="timezone"):
        encode(datetime(2026, 9, 5))


@pytest.mark.parametrize("change", [
    "compensating", "rating_swap", "reaction_key", "null_zero", "timezone",
    "negative_transition", "deleted", "extra", "identity", "duplicate",
])
def test_actual_values_not_summary_totals_decide_reconciliation(change):
    source = [(('posts', 1, 1), {"views": 100, "rank": 1, "comments": None,
                               "observedAt": "2026-09-05T10:00:00Z", "reactions": {"like": 2}}),
              (('posts', 1, 2), {"views": 90, "rank": 2, "comments": 0,
                               "observedAt": "2026-09-05T11:00:00Z", "reactions": {"like": 1}})]
    target = [(key, dict(row)) for key, row in source]
    if change == "compensating":
        target[0][1]["views"] += 1
        target[1][1]["views"] -= 1
    elif change == "rating_swap":
        target[0][1]["rank"], target[1][1]["rank"] = 2, 1
    elif change == "reaction_key":
        target[0][1]["reactions"] = {"heart": 2}
    elif change == "null_zero":
        target[0][1]["comments"] = 0
    elif change == "timezone":
        target[0][1]["observedAt"] = "2026-09-05T13:00:00Z"
    elif change == "negative_transition":
        target[1][1]["views"] = 110
    elif change == "deleted":
        target.pop()
    elif change == "extra":
        target.append((('posts', 1, 3), target[0][1]))
    elif change == "identity":
        target[0] = (('posts', 2, 1), target[0][1])
    elif change == "duplicate":
        target.append(target[0])
    result = compare_rows(iter(source), iter(target))
    assert result["expected"] != result["actual"]
    assert result["changedKeysSample"]


def test_ordered_digest_is_stable_when_input_delivery_order_changes():
    source = [(('p', i), {"n": None if i % 3 else 0}) for i in range(2000)]
    result = compare_rows(iter(source), reversed(source))
    assert result["expected"] == result["actual"]
    assert result["actual"]["rows"] == 2000
    assert result["actual"]["duplicateKeys"] == 0
    assert result["changedKeysSample"] == []
