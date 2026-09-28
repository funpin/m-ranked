"""No evidence may become mature training support or an interpolated ERV."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.series import CollectionCadence, prepare, value_at, engagement_at
from anomaly_analysis.v2.norms import ERV, Norm, NormCell, Robust, build_norms, raw_account_norm, norm_to_payload
from anomaly_analysis.v2.store import norm_from_rows, norm_rows
from anomaly_analysis.v2.detectors import erv_outlier, DetectorContext

T = datetime(2026, 9, 1, tzinfo=timezone.utc)
V, R, C = Metric.VIEWS, Metric.REACTIONS, Metric.COMMENTS


def measured(ages=(0, 12, 24, 36, 48, 60, 72), *, index=1, account=2):
    return PostSeries(UUID(int=index), UUID(int=account), "max", T, False,
        tuple(T+timedelta(hours=a) for a in ages),
        {V:tuple(100+int(a*10) for a in ages), R:tuple(5+int(a) for a in ages)})


def prepared(subject):
    return prepare(subject, subject.observed_at[-1], CollectionCadence())


def test_unknown_rows_cannot_inflate_training_support():
    s = measured()
    unknown = [replace(s, publication_id=UUID(int=100+i),
        qualities={m:("unknown",)*len(s.observed_at) for m in s.values}) for i in range(50)]
    one = raw_account_norm("max", s.account_id, [prepared(s)])
    padded = raw_account_norm("max", s.account_id, [prepared(x) for x in [s,*unknown]])
    assert norm_to_payload(one) == norm_to_payload(padded)
    assert one.posts == 1 and one.confidence == .02


def test_accounts_without_usable_observations_are_not_platform_voters():
    valid = [prepared(measured(index=i+1)) for i in range(3)]
    baseline = build_norms("max", {UUID(int=2):valid})
    padded = {UUID(int=2):valid}
    for a in range(100,130):
        s = measured(account=a)
        s = replace(s, interval_uncertain=(True,)*len(s.observed_at))
        padded[s.account_id] = [prepared(replace(s, publication_id=UUID(int=a*10+i))) for i in range(3)]
    assert norm_to_payload(build_norms("max", padded).platform) == norm_to_payload(baseline.platform)


def test_views_cannot_make_sparse_reaction_reference_mature():
    ages = tuple(i/4 for i in range(289))
    full = measured(ages)
    rows = [prepared(full)]
    rows += [prepared(replace(full, publication_id=UUID(int=10+i), values={V:full.values[V]},
        qualities={V:full.qualities[V]})) for i in range(29)]
    norm = raw_account_norm("max", full.account_id, rows, final_age=48*3600)
    assert norm.confidence >= .5
    assert norm.confidence_for("views", 1) >= .5
    assert norm.confidence_for("reactions", 1) == .02
    assert norm.confidence_for(ERV, 1) == .02
    assert norm.confidence_for("comments", 1) == 0
    assert norm_to_payload(norm_from_rows(norm_rows(norm))) == norm_to_payload(norm)


@pytest.mark.parametrize("ages", [(25,26), (23,25)])
def test_anchor_neither_extrapolates_nor_bridges_long_gap(ages):
    p = prepared(measured(ages))
    assert value_at(p.metrics[V], 24*3600) is None
    norm = raw_account_norm("max", p.series.account_id, [p])
    assert norm.posts == 0 and not norm.cells and not norm.decay


@pytest.mark.parametrize("quality,uncertain", [("rounded",False), ("unknown",False), ("exact",True)])
def test_bad_interior_read_cannot_support_anchor(quality,uncertain):
    s = measured((23+55/60,24,24+5/60))
    s = replace(s, qualities={V:("exact",quality,"exact"), R:("exact",)*3},
                interval_uncertain=(False,uncertain,False))
    p = prepared(s)
    assert value_at(p.metrics[V],24*3600) is None
    if uncertain:
        assert engagement_at(p,24*3600) is None
    else:
        assert engagement_at(p,24*3600) is not None


def test_trusted_short_interpolation_and_exact_endpoint_remain_available():
    p = prepared(measured((23+55/60,24+5/60)))
    assert value_at(p.metrics[V],24*3600) == pytest.approx(339.5)
    assert value_at(p.metrics[V],p.metrics[V].ages[-1]) == p.metrics[V].values[-1]
    s = replace(p.series, values={V:(200,100),R:(20,10)})
    corrected = prepared(s)
    assert value_at(corrected.metrics[V],24*3600) is None
    assert value_at(corrected.metrics[V],corrected.metrics[V].ages[-1]) == 100


def test_missing_reported_engagement_is_not_dropped_from_sum():
    s = measured((24,25))
    s = replace(s,values={**s.values,C:(2,3)},qualities={**s.qualities,C:("unknown",)*2})
    assert engagement_at(prepared(s),24*3600) is None
    s = replace(s,values={**s.values,C:(0,0)},qualities={**s.qualities,C:("exact",)*2})
    assert engagement_at(prepared(s),24*3600) == s.values[R][0]


def test_erv_detector_does_not_extrapolate_day_one_from_late_start():
    s = measured((25,26))
    norm = Norm("max",s.account_id,"account",50,1.,cells={
        (ERV,0):NormCell(ERV,0,50,log_erv=Robust(-10,.1),confidence=1.)})
    assert not erv_outlier.detect(prepared(s),DetectorContext("max",norm))


def test_future_metric_does_not_change_past_engagement():
    s = measured((24,25))
    before = prepare(s,T+timedelta(hours=24),CollectionCadence())
    s = replace(s,values={**s.values,C:(None,3)},qualities={**s.qualities,C:("unknown","exact")})
    after = prepare(s,T+timedelta(hours=24),CollectionCadence())
    assert engagement_at(before,24*3600) == engagement_at(after,24*3600)


def test_counter_correction_is_not_scored_as_late_arrivals():
    import numpy as np
    from anomaly_analysis.v2.detectors import late_spike
    from anomaly_reference.mature_norms import synthetic_cases
    s = synthetic_cases()["p02_late_spike_telegram"].subject
    values = list(s.values[V])
    index = next(i for i,t in enumerate(s.observed_at) if t-s.published_at > timedelta(hours=26))
    values[index] = 0
    s = replace(s,values={**s.values,V:tuple(values)})
    # Natural counter corrections used to emit an invalid-log warning before
    # the grid mask was applied. They must remain safe even with strict FP.
    with np.errstate(invalid="raise"):
        late_spike.detect(prepared(s),DetectorContext(s.platform))


@pytest.mark.parametrize("name,detector_name", [
    ("p02_late_spike_telegram", "late_spike"),
    ("p04_gap_growth_telegram", "gap_growth"),
])
def test_sparse_cell_cannot_produce_a_strong_public_verdict(name, detector_name):
    from anomaly_analysis.v2 import detectors
    from anomaly_analysis.v2.levels import verdict
    from anomaly_reference.mature_norms import norms_for, synthetic_cases
    case = synthetic_cases()[name]
    p = prepared(case.subject)
    norm = norms_for(case).for_account(case.subject.account_id)
    detector = getattr(detectors, detector_name)
    strong = detector.detect(p, DetectorContext(case.subject.platform, norm))
    assert any(s.strength >= .7 for s in strong)
    sparse = replace(norm, confidence=1., cells={
        key:replace(cell, confidence=.02) for key,cell in norm.cells.items()})
    context = DetectorContext(case.subject.platform, sparse)
    result = verdict(p, context, detector.detect(p, context), {})
    assert result.signs and result.level <= 1
    assert all(s.strength < .7 for s in result.signs)
