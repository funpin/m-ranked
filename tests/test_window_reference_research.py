"""Independent interval windows must preserve support, time and calibration units."""
from datetime import timedelta
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research/smart-engagement-2026-09/scripts'))
import window_reference as W


def sample_points(days=range(7),bad=None,revision=1):
    out=[]
    for day in days:
        value={'observed_at':(W.I.START+timedelta(days=day)).isoformat(),
            'r':day,'v':100+2*day,'rq':'exact','vq':'exact','uncertain':False,'correction_sequence':revision}
        if day==bad:value['rq']='rounded'
        out.append(value)
    return out


def prepared(points):
    return W.I.prepare([{'post':{'id':str(i),'primary_account_id':'a',
        'published_at':(W.I.START-timedelta(days=4)).isoformat(),'is_repost':False},'daily':points} for i in range(10)])[0]


def window(points):return W.extract(prepared(points),W.I.START,W.I.SPLIT,source_verified=True)['a']


def simple_model():
    return {'mode':'conditional','center':np.zeros(4),'scale':np.ones(4),'beta':np.zeros(4),'dispersion':.4}


def test_unverified_version_source_is_rejected():
    with pytest.raises(ValueError,match='source'):W.extract(prepared(sample_points()),W.I.START,W.I.SPLIT)


def test_interval_windows_use_real_times_and_catalog_denominator():
    r=window(sample_points())
    assert r['eligible'] and r['intervals']==60 and r['observed_posts']==10
    assert r['coverage']==pytest.approx(6/7) and r['span_hours']==144 and r['support']=='high:short'
    assert r['net_r']==60


def test_quality_barrier_is_not_bridged_by_interval_model():
    r=window(sample_points(bad=3))
    assert r['intervals']==40 and r['net_r']==40
    assert all(not (v['start']<W.I.START+timedelta(days=3)<v['end']) for v in r['rows'])


def test_long_gap_is_excluded_from_model_without_losing_catalog_opportunity():
    r=window(sample_points(days=(0,4,6)))
    assert r['intervals']==10 and r['excluded']['over72h']==10
    assert r['coverage']==pytest.approx(2/7) and not r['eligible']


def test_empty_window_is_unknown_and_not_zero_score():
    r=window([])
    assert W.score(r,simple_model())['status']=='abstain_window_support'
    assert 'scores' not in W.score(r,simple_model())


def test_zero_change_is_eligible_but_fails_recurrence_gate():
    points=[p|{'r':10} for p in sample_points()]
    s=W.score(window(points),simple_model())
    assert s['status']=='eligible' and not s['recurrence_gate'] and s['scores']=={'volume':0.,'joint':0.}


def test_window_boundary_excludes_crossing_interval():
    points=sample_points(days=(5,6,7,8))
    first=W.extract(prepared(points),W.I.START,W.I.SPLIT,source_verified=True)['a']
    second=W.extract(prepared(points),W.I.SPLIT,W.I.END,source_verified=True)['a']
    assert first['net_r']==10 and second['net_r']==10


def test_occupancy_groups_same_post_and_does_not_count_intervals_as_posts():
    r=window(sample_points());s=W.score(r,simple_model())
    assert s['expected_r']==pytest.approx(60)
    assert s['expected_positive_posts']==pytest.approx(10*(1-1.4**(-6/.4)))


def test_reaction_history_does_not_enter_explanatory_design():
    rows=window(sample_points())['rows']
    changed=[r|{'dr':100000,'r0':100000} for r in rows]
    for mode in W.MODES:
        x,offset=W.design(rows,mode);y,other=W.design(changed,mode)
        np.testing.assert_array_equal(x,y);np.testing.assert_array_equal(offset,other)


def test_calibration_matches_support_and_retains_ties():
    target={'status':'eligible','support':'high:short','scores':{'joint':1.}}
    same={'status':'eligible','support':'high:short','scores':{'joint':0.}}
    other=same|{'support':'medium:short'}
    assert W.decision(target,[same]*18+[other]*400,'joint')['status']=='abstain'
    assert W.decision(target,[same]*19,'joint')['flag']
    assert not W.decision(target,[target]*19,'joint')['flag']


def test_platforms_and_81_way_resolution_abstain():
    target={'status':'eligible','support':'high:short','scores':{'joint':100.}}
    cal=[target|{'scores':{'joint':0.}}]*40
    assert W.decision(target,cal,'joint',alpha=.05/81)['status']=='abstain'
    for platform in ('telegram','vk'):
        assert W.decision(target,cal,'joint',platform=platform)['status']=='abstain'


def test_reference_fit_excludes_target_and_future_rows():
    base=window(sample_points())['rows']
    data={str(a):[r|{'account':str(a),'dr':(i+a)%4} for i,r in enumerate(base)] for a in range(24)}
    target='0';fit_accounts,cal_accounts=W.P.partition(list(data),target)
    first=W.fit([r for a in fit_accounts for r in data[a]],'conditional')
    data[target]=[r|{'dr':1000000} for r in data[target]]
    for a in cal_accounts:data[a]=[r|{'dr':1000000} for r in data[a]]
    second=W.fit([r for a in fit_accounts for r in data[a]],'conditional')
    assert W.P.model_digest(first)==W.P.model_digest(second) and target not in first['accounts']


def test_missing_first_and_last_synthetic_reads_are_not_recreated():
    data=W.P.ordinary_world(W.rng(91));one=W.make_target(data,91,0,'baseline')
    full=W.synthetic_window(one,91,0,'full',23,30)
    sparse=W.synthetic_window(one,91,0,'every_third',23,30)
    assert sparse['hours']<full['hours'] and sparse['intervals']<full['intervals']


def test_protocol_and_temporal_source_limit_are_explicit():
    assert W.provenance(ROOT)['protocol_sha256']==W.PROTOCOL_SHA
    assert not W.source_contract(ROOT)['fit_values_available_before_test_verified']


def test_insufficient_fit_rejected_and_nonfinite_scores_cannot_pass():
    with pytest.raises(ValueError,match='support'):W.fit([], 'conditional')
    target={'status':'eligible','support':'high:short','scores':{'joint':np.nan}}
    with pytest.raises(ValueError,match='Nonfinite'):W.decision(target,[target]*20,'joint')
