"""Evidence bounds must survive gaps without reconstructing hidden activity."""
import itertools
from pathlib import Path
import sys

import numpy as np
import pytest

SCRIPTS=Path(__file__).resolve().parents[1]/"research/smart-engagement-2026-09/scripts"
sys.path.insert(0,str(SCRIPTS))
import interval_evidence as X


def point(at,r,v=100,**kwargs):
    return {"observed_at":at,"r":r,"v":v,"rq":"exact","vq":"exact","uncertain":False,"correction_sequence":0,**kwargs}


def post(points):
    return {"post":{"id":"p","primary_account_id":"a","published_at":"2026-09-10T00:00:00+03:00","is_repost":False},"daily":points}


def result(points,start=X.START,end=X.END):
    prepared,_=X.prepare([post(points)])
    return X.ledger(prepared,start,end)[0]["a"]


def test_whole_gap_is_preserved_without_early_fit_and_no_hourly_shape():
    for minutes in (89,90,91,95):
        start=X.START+X.timedelta(hours=19)
        r=result([point(start.isoformat(),47,2975),point((start+X.timedelta(minutes=minutes)).isoformat(),363,2976)])
        assert r["sum_positive_net_r"]==316 and r["sum_net_v"]==1
        assert r["minimum_growth_days"]==1 and r["hours"]==pytest.approx(minutes/60)
        assert "hourly_rate" not in r


def test_unknown_quality_is_a_barrier_not_an_invitation_to_bridge():
    points=[point("2026-09-14T12:00:00+03:00",1),point("2026-09-15T12:00:00+03:00",5),point("2026-09-16T12:00:00+03:00",10)]
    for changes in ({"rq":"rounded"},{"vq":"unknown"},{"uncertain":True},{"synthetic":True},{"correction_sequence":1}):
        altered=[points[0],points[1]|changes,points[2]]
        assert result(altered)["intervals"]==0
        altered[1]["r"]=1000000
        assert result(altered)["sum_positive_net_r"]==0


def test_duplicate_points_do_not_multiply_evidence_and_conflicts_break_chain():
    a=point("2026-09-14T12:00:00+03:00",1);b=point("2026-09-15T12:00:00+03:00",10)
    assert result([a,b])==result([a,a,b,b])
    assert result([a,a|{"r":4},b])["intervals"]==0


def test_midnight_is_a_possible_change_day_without_assigning_it_as_fact():
    intervals=[(X.T.dt("2026-09-14T23:59:59.999999+03:00"),X.T.dt("2026-09-15T00:00:00+03:00")),
               (X.T.dt("2026-09-15T00:00:00+03:00"),X.T.dt("2026-09-15T01:00:00+03:00"))]
    assert X.minimum_days(intervals)==1


def test_greedy_day_bound_matches_exhaustive_small_hitting_sets():
    random=np.random.default_rng(219)
    for _ in range(80):
        windows=[];pairs=[]
        for _ in range(8):
            left=int(random.integers(0,6));right=int(random.integers(left,6))
            windows.append(set(range(left,right+1)))
            pairs.append((X.START+X.timedelta(days=left,hours=1),X.START+X.timedelta(days=right,hours=23)))
        brute=next(k for k in range(1,7) if any(all(set(selected)&w for w in windows) for selected in itertools.combinations(range(6),k)))
        assert X.minimum_days(pairs)==brute


def test_cross_week_growth_cannot_be_counted_in_both_weeks():
    a=point("2026-09-20T23:00:00+03:00",2);b=point("2026-09-21T01:00:00+03:00",8)
    assert result([a,b])["minimum_growth_days"]==1
    assert result([a,b],X.START,X.SPLIT)["intervals"]==0
    assert result([a,b],X.SPLIT,X.END)["intervals"]==0
    b["observed_at"]=X.SPLIT.isoformat()
    assert result([a,b],X.START,X.SPLIT)["intervals"]==0  # End is exclusive.


def test_actual_age_boundaries_do_not_smuggle_younger_or_older_counts():
    assert result([point("2026-09-13T23:59:59+03:00",1),point("2026-09-14T12:00:00+03:00",8)])["intervals"]==0
    assert result([point("2026-09-23T12:00:00+03:00",1),point("2026-09-24T00:00:00+03:00",8)])["intervals"]==1
    assert result([point("2026-09-23T12:00:00+03:00",1),point("2026-09-24T00:00:01+03:00",8)])["intervals"]==0


def test_missing_and_equal_endpoints_do_not_prove_no_activity():
    assert result([])["status"]=="unknown_no_trusted_interval"
    r=result([point("2026-09-14T12:00:00+03:00",8),point("2026-09-17T12:00:00+03:00",8)])
    assert r["minimum_growth_days"]==0 and r["status"]=="no_observed_positive_net_change"
    assert r["not_a_normality_or_fraud_verdict"]
    empty,_=X.ledger([],X.START,X.END,accounts=["missing"])
    assert empty["missing"]["coverage_hours"] is None


def test_counter_decrease_is_not_positive_growth_and_is_not_bridged():
    r=result([point("2026-09-14T12:00:00+03:00",9),point("2026-09-15T12:00:00+03:00",3),point("2026-09-16T12:00:00+03:00",8)])
    assert r["sum_positive_net_r"]==5 and r["excluded"]["known_counter_decrease"]==1


def test_long_interval_does_not_imply_daily_growth():
    r=result([point("2026-09-14T12:00:00+03:00",0),point("2026-09-20T12:00:00+03:00",100)])
    assert r["minimum_growth_days"]==1 and r["positive_intervals"]==1
    assert r["bands"]["gt72h"]["intervals"]==1


def test_future_date_never_grants_validation_by_itself():
    manifest={"start_inclusive":"2026-09-29T00:00:00+03:00","end_exclusive":"2026-10-06T00:00:00+03:00","earliest_assessment":"2026-10-06T00:00:00+03:00"}
    for at,state in (("2026-09-28T16:00:00+03:00","not_started"),("2026-10-02T00:00:00+03:00","immature"),
                     ("2026-10-06T00:00:00+03:00","calendar_mature_requires_support_audit")):
        r=X.prospective_status(at,manifest)
        assert r["state"]==state and not r["evaluation_permitted"]
    with pytest.raises(ValueError):X.prospective_status("2026-10-06T00:00:00",manifest)


def test_coarsening_simulation_has_no_overclaim_or_anomaly_decisions():
    report=X.simulation_cycle(worlds=2)
    assert report["measurement_gate_pass"] and not report["invariant_violations"]
    assert not report["new_production_signal"] and report["not_detection_accuracy"]


def test_protocol_hash_is_frozen():
    assert X.provenance(SCRIPTS.parents[2])["protocol_sha256"]==X.PROTOCOL_SHA


def test_derived_report_cannot_overwrite_raw_audit(monkeypatch,tmp_path):
    path=tmp_path/"raw.json";path.write_text("[]\n")
    monkeypatch.setattr(sys,"argv",["interval_evidence.py","--mode","availability","--availability",str(path),"--output",str(path)])
    with pytest.raises(SystemExit):X.main()
    assert path.read_text()=="[]\n"


def test_latest_version_requires_verified_source_contract_and_real_quality():
    p=point("2026-09-14T12:00:00+03:00",20,correction_sequence=1)
    assert not X.trusted(p)
    assert not X.trusted(p,policy="latest_as_of_cutoff")
    for seq in (1,2,100):
        assert X.trusted(p|{"correction_sequence":seq},policy="latest_as_of_cutoff",latest_version_verified=True)
    for changes in ({"rq":"rounded"},{"uncertain":True},{"synthetic":True},{"correction_sequence":None},{"correction_sequence":-1}):
        assert not X.trusted(p|changes,policy="latest_as_of_cutoff",latest_version_verified=True)


def test_latest_version_does_not_bypass_decreases_or_conflicting_timestamps():
    a=point("2026-09-14T12:00:00+03:00",47,2975)
    b=point("2026-09-14T13:35:00+03:00",363,2976,correction_sequence=1)
    prepared,_=X.prepare([post([a,b])])
    r,_=X.ledger(prepared,X.START,X.END,policy="latest_as_of_cutoff",latest_version_verified=True)
    assert r["a"]["sum_positive_net_r"]==316 and r["a"]["minimum_growth_days"]==1
    for points in ([a,b|{"v":2974}],[a,b,b|{"r":365}]):
        prepared,_=X.prepare([post(points)])
        r,_=X.ledger(prepared,X.START,X.END,policy="latest_as_of_cutoff",latest_version_verified=True)
        assert r["a"]["intervals"]==0
