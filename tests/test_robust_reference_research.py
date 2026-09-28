"""Leakage boundaries, human-session mechanics and family-risk calibration."""
import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import binom

PATH=Path(__file__).resolve().parents[1]/'research/smart-engagement-2026-09/scripts/robust_reference_validation.py'
SPEC=importlib.util.spec_from_file_location('robust_reference_research',PATH)
R=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def rows():
    return [dict(primary_account_id=a,publication_type='photo' if a=='a' else 'video',
                 published_at=f'2026-09-{day:02}T12:00:00+00:00',
                 published=datetime(2026,9,day,12,tzinfo=timezone.utc))
            for a in ('a','b','c') for day in (6,13,20)]


def sample(n=100):
    mask=np.ones((n,12,14),bool)
    mask[:,:,4:7]=False
    mask[:,6:,:]=False
    v=10*mask.astype(int);r=2*mask.astype(int)
    return v,r,mask,v.astype(float),.1*mask


def test_prepublication_design_is_counter_invariant_and_does_not_fit_test_values():
    data=rows();fit=np.array([0,3,6])
    a=R.design(data,fit,'prepublication_context',np.arange(len(data)))
    b=R.design(data,fit,'prepublication_context',np.arange(len(data))*1000)
    np.testing.assert_array_equal(a,b)
    modified=copy.deepcopy(data)
    modified[2]['publication_type']='never_seen_in_fit'
    modified[2]['published']=datetime(2026,9,24,1,tzinfo=timezone.utc)
    c=R.design(modified,fit,'prepublication_context',np.zeros(len(data)))
    np.testing.assert_array_equal(a[fit],c[fit])
    assert a.shape==c.shape


def test_excluded_account_never_enters_fit_or_calibration_and_each_test_is_once():
    data=rows();folds=R.temporal_folds(data,True)
    seen=[]
    for account,fit,cal,test in folds:
        assert all(data[i]['primary_account_id']!=account for i in np.r_[fit,cal])
        assert all(data[i]['primary_account_id']==account for i in test)
        assert all(data[i]['published']<data[test[0]]['published'] for i in np.r_[fit,cal])
        seen.extend(test)
    assert sorted(seen)==[2,5,8]


def test_one_visitor_reacts_at_most_once_to_each_post_and_only_where_observed():
    original=sample()
    before=[x.copy() for x in original]
    changed=R.add_archive_sessions(original,123,broad_count=1,reaction_probability=1.)
    dv,dr=changed[0]-original[0],changed[1]-original[1]
    np.testing.assert_array_equal(dv,dr)
    assert (dr.sum(axis=2)<=1).all()
    assert ((dr>0).any(axis=1).sum(axis=1)==1).all()
    assert (dr[~original[2]]==0).all()
    for a,b in zip(original,before):np.testing.assert_array_equal(a,b)


@pytest.mark.parametrize('kind',['archive_sessions','exposure_event'])
def test_benign_mechanisms_keep_missing_observations_missing(kind):
    original=sample(20)
    changed=R.family(original,kind,38)
    assert (changed[0][~original[2]]==0).all()
    assert (changed[1][~original[2]]==0).all()
    assert (changed[0]>=original[0]).all()
    assert (changed[1]>=original[1]).all()
    assert np.isfinite(R.MASK.features(*changed)).all()


def test_zero_sessions_and_zero_exposure_leave_counters_unchanged():
    original=sample(20)
    for changed in (R.add_archive_sessions(original,23,mean_sessions=0),
                    R.add_exposure_event(original,23,fixed_fraction=0)):
        np.testing.assert_array_equal(changed[0],original[0])
        np.testing.assert_array_equal(changed[1],original[1])


def test_tolerance_family_envelope_and_small_sample_abstention():
    samples=[np.arange(2000,dtype=float)+shift for shift in (0,200,400)]
    thresholds=[R.tolerance_threshold(s,R.DELTA/3) for s in samples]
    maximum=max(t[0] for t in thresholds)
    for s,(threshold,order) in zip(samples,thresholds):
        assert binom.sf(order-1,len(s),1-R.ALPHA)<=R.DELTA/3
        assert maximum>=threshold
        assert not ((s>maximum)&(s<=threshold)).any()
    assert np.isinf(R.tolerance_threshold(np.arange(10))[0])


def test_component_budget_controls_all_eighteen_calibration_events():
    threshold,order=R.tolerance_threshold(np.arange(2000),delta=.05/18,alpha=.05/6)
    assert np.isfinite(threshold)
    assert 18*binom.sf(order-1,2000,1-.05/6)<=.05
    assert 6*(.05/6)==pytest.approx(.05)


def test_mixture_and_joint_score_are_reproducible_and_do_not_saturate():
    designs=sample(2)[2:]
    a,b=R.mixture(designs,72,32),R.mixture(designs,72,32)
    for x,y in zip(a,b):np.testing.assert_array_equal(x,y)
    center,scale=R.score_scale(R.MASK.features(*a))
    before=R.joint_score(a,center,scale)
    x=tuple(v.copy() for v in a)
    x[0][:]+=100000*x[2]
    assert (R.joint_score(x,center,scale)>before.max()).all()


def test_simulation_size_override_is_restored():
    before=R.MASK.N
    assert len(R.simulate_n(sample(2)[2:],17,n=4)[0])==4
    assert R.MASK.N==before
