"""Scientific invariants for H54–H57; production is not imported."""
from pathlib import Path
import sys
import json

import numpy as np
import pytest

SCRIPTS=Path(__file__).resolve().parents[1]/"research/smart-engagement-2026-09/scripts"
sys.path.insert(0,str(SCRIPTS))
import context_validation as X


def test_subscribers_must_be_exact_positive_prior_and_recent(tmp_path):
    row={"account":"a","subscriber_count":200,"observed_at":"2026-09-13T12:00:00+03:00",
         "created_at":"2026-09-13T13:00:00+03:00","quality":"exact"}
    path=tmp_path/"input.json"
    path.write_text(json.dumps([row]));assert X.load_subscribers(path)=={"a":200}
    for key,value in (("quality","rounded"),("subscriber_count",0),
                      ("created_at","2026-09-14T00:00:00+03:00"),
                      ("observed_at","2026-08-30T23:59:00+03:00")):
        path.write_text(json.dumps([row|{key:value}]))
        with pytest.raises(ValueError):X.load_subscribers(path)
    path.write_text(json.dumps([row|{"subscriber_count":None}]))
    assert X.load_subscribers(path)=={}


def test_mean_correction_keeps_negative_values_and_handles_zero():
    assert X.statistics([10]*20)["H"]==pytest.approx(-.1)
    assert X.statistics([0]*20)["status"]=="no_positive_mean"
    assert X.statistics([])["n"]==0


def test_bootstrap_pairs_calendar_shocks_and_preserves_whole_days():
    groups={"2026-09-01":[1,2,2],"2026-09-02":[40,45],"2026-09-03":[3]}
    np.testing.assert_array_equal(X.paired_resample_h(groups,groups,8),np.zeros(2000))
    np.testing.assert_array_equal(X.paired_resample_h(groups,groups,8),X.paired_resample_h(groups,groups,8))


def test_block_dates_use_moscow_and_missing_support_abstains():
    def curve(date,r):return {"published_at":date,"points":[{"r":1}]+[None]*5+[{"r":r}]}
    curves=[curve("2026-09-02T22:00:00Z",3),curve("2026-09-03T09:00:00Z",5)]
    assert X.blocks(curves,"late")=={"2026-09-03":[2,4]}
    assert X.compare(curves,curves,1)["status"]=="abstain"


def test_simulation_preserves_frozen_counters_and_exposes_only_observed_s():
    data,s=X.simulation_world(8)
    original=X.P.ordinary_world(X.rng(57,8,1))
    assert set(data)=={"r","v","early_r","early_v"}
    for k in data:np.testing.assert_array_equal(data[k],original[k])
    assert s.shape==(61,) and (s>0).all() and np.issubdtype(s.dtype,np.integer)


def test_target_full_history_and_subscribers_cannot_train_reference_or_calibration():
    data,s=X.simulation_world(1)
    ref,model=X.subscriber_reference(data,s);cal=X.calibrate(data,s,ref,model)
    changed=X.P.clone(data);s2=s.copy();s2[0]*=100
    for k in changed:changed[k][0]*=100
    ref2,model2=X.subscriber_reference(changed,s2);cal2=X.calibrate(changed,s2,ref2,model2)
    assert model==model2
    for k in ref:np.testing.assert_array_equal(ref[k],ref2[k])
    for k in cal:np.testing.assert_array_equal(cal[k],cal2[k])


def test_cal_and_later_fit_observations_do_not_train_coefficients():
    data,s=X.simulation_world(2);ref,model=X.subscriber_reference(data,s)
    for k in ("r","v"):data[k][X.P.CAL]*=100;data[k][X.P.FIT,10:]*=100
    for k in ("early_r","early_v"):data[k][X.P.CAL]*=100
    s[X.P.CAL]*=100
    ref2,model2=X.subscriber_reference(data,s)
    assert model==model2
    for k in ref:np.testing.assert_array_equal(ref[k],ref2[k])


def test_subscriber_scale_normalization_and_uniform_scale_invariance():
    data,s=X.simulation_world(3);ref,model=X.subscriber_reference(data,s)
    ref2,model2=X.subscriber_reference(data,s*2)
    for m in X.P.MODES:
        factors=[X.scaled_reference(ref,model,int(s[a]))[m]/ref[m] for a in X.P.FIT]
        np.testing.assert_allclose(np.mean(factors,axis=0),1,atol=1e-12)
        np.testing.assert_allclose(X.scaled_reference(ref,model,int(s[0]))[m],
                                   X.scaled_reference(ref2,model2,int(s[0]*2))[m],atol=1e-12)
    with pytest.raises(ValueError):X.scaled_reference(ref,model,0)


def test_s_inflation_changes_predictions_without_changing_fit():
    reference={"structural":np.ones(20),"conditional":1.}
    model={"center":np.log(100.),"modes":{m:{"slope":1.,"normalizer":1.} for m in X.P.MODES}}
    for m in X.P.MODES:
        np.testing.assert_allclose(X.scaled_reference(reference,model,400)[m],reference[m]*4)


def test_all_month_reaction_and_er_interventions_are_distinct():
    data,s=X.simulation_world(4)
    changed={s:X.G.alter(data,0,s,X.rng(6)) for s in ("persistent_r100","early_r100","preserve_er100","audience_growth")}
    for scenario in changed:
        np.testing.assert_array_equal(changed[scenario]["r"],data["r"][0]*2)
    np.testing.assert_array_equal(changed["persistent_r100"]["early_r"],data["early_r"][0])
    for k in data:np.testing.assert_array_equal(changed["audience_growth"][k],changed["preserve_er100"][k])


def test_rank_ties_are_conservative_and_no_signal_is_not_normality():
    data,s=X.simulation_world(5);ref,model=X.subscriber_reference(data,s)
    one={k:v[0] for k,v in data.items()}
    tied={"old":np.full(30,np.inf),"subscriber":np.full(30,np.inf)}
    assert not any(X.decide(one,s[0],ref,model,tied).values())
    assert X.rate(0,0)["wilson95"] is None


def test_registered_protocol_still_matches():
    assert X.provenance(SCRIPTS.parents[2])["protocol_sha256"]==X.PROTOCOL_SHA
