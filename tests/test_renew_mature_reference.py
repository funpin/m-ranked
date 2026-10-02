"""Пересборка ориентира 11/12: тот же протокол, что у выпущенного артефакта."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random

import pytest

from anomaly_analysis.tools.renew_mature_reference import fit, reason
from anomaly_analysis.v2.mature_reference import MatureReference, bundled_reference

UTC = timezone.utc


def _row(account: int, published: datetime, early: tuple[int, int], late: tuple[int, int], **overrides):
    points = [{"v": early[0], "r": early[1], "vq": "exact", "rq": "exact", "uncertain": False,
               "observed_at": (published + timedelta(hours=23)).isoformat()},
              {"v": late[0], "r": late[1], "vq": "exact", "rq": "exact", "uncertain": False,
               "observed_at": (published + timedelta(hours=71)).isoformat()}]
    row = {"primary_account_id": f"00000000-0000-0000-0000-{account:012d}", "published_at": published.isoformat(),
           "points": points, "known_decrease": False}
    row.update(overrides)
    return row


def _rows(seed=7):
    rng = random.Random(seed)
    rows = []
    for fold_start in (datetime(2026, 9, 13, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC)):
        for account in range(12):
            for index in range(12):
                views = rng.randint(300, 3000)
                published = fold_start + timedelta(hours=7 * index + account)
                rows.append(_row(account, published, (views, views // 40),
                                 (int(views * rng.uniform(1.3, 1.8)), views // 30)))
    return rows


def test_the_calibrated_boundary_keeps_the_protocol_level_and_passes_runtime_validation():
    artifact, report = fit(_rows(), version="test-renewal",
                           fit_window=(datetime(2026, 9, 13, tzinfo=UTC), datetime(2026, 9, 17, tzinfo=UTC)),
                           calibration_window=(datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 24, tzinfo=UTC)),
                           available_at=datetime(2026, 9, 27, tzinfo=UTC),
                           expires_at=datetime(2026, 10, 25, tzinfo=UTC))
    reference = MatureReference.from_payload(artifact)
    assert reference.version == "test-renewal" and report["accounts"] == 12
    assert report["calibration_flagged"] <= 0.05 * (report["calibration"] + 1)


def test_unusable_endpoints_are_excluded_with_a_reason_and_small_folds_are_refused():
    published = datetime(2026, 9, 13, tzinfo=UTC)
    assert reason(_row(1, published, (100, 1), (200, 2), known_decrease=True)) == "known_decrease"
    rounded = _row(1, published, (100, 1), (200, 2))
    rounded["points"][1]["vq"] = "rounded"
    assert reason(rounded) == "nonexact_endpoint"
    with pytest.raises(ValueError):
        fit(_rows()[:50], version="x", fit_window=(published, published + timedelta(days=4)),
            calibration_window=(published + timedelta(days=7), published + timedelta(days=11)),
            available_at=published + timedelta(days=14), expires_at=published + timedelta(days=42))


def test_the_renewed_artifact_extends_coverage_without_replacing_the_first():
    bundle = bundled_reference()
    versions = [item.version for item in bundle.references]
    assert versions[0] == "max-2026-09-v1" and len(versions) >= 2
    assert bundle.expires_at > bundle.references[0].expires_at
