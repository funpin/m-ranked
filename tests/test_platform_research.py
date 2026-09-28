"""Regression tests for invalid inference paths in H26-H29."""
import importlib.util
from pathlib import Path
import numpy as np
from datetime import datetime,timezone

SCRIPT=Path(__file__).resolve().parents[1]/'research/smart-engagement-2026-09/scripts/platform_validation.py'
spec=importlib.util.spec_from_file_location('platform_validation',SCRIPT)
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)


def point(h,v,quality='exact',r=3):
    return {'age_seconds':h*3600,'v':v,'vq':quality,'r':r,'rq':'exact','c':None,'s':None,'uncertain':False}


def test_missing_age_window_never_inferred_from_neighbor():
    reason,result=P.wave([point(72,100),point(95.99,110),point(120,160)])
    assert reason=='missing_window' and result is None


def test_wave_after_four_days_uses_actual_duration_and_not_missing_zeros():
    reason,result=P.wave([point(72,100),point(98,110),point(120,160)])
    assert reason=='eligible' and result['wave'] and result['age_start']>=96
    assert result['metric_deltas']=={'r':0}


def test_rounding_and_internal_resets_cannot_confirm_wave():
    assert P.wave([point(72,100,'rounded'),point(96,110),point(120,160)])[0]=='nonexact_or_uncertain'
    assert P.wave([point(72,100),point(90,90),point(96,110),point(120,160)])[0]=='negative_correction'


def test_ties_and_small_calibration_do_not_create_five_percent_signal():
    assert np.all(P.ranks([5,100],np.arange(18))>.05)
    assert P.ranks([100],np.arange(19))[0]==.05
    assert P.ranks([1],np.ones(100))[0]==1


def test_zero_observed_alerts_cannot_claim_zero_upper_risk():
    result=P.rate([False]*24,[str(i) for i in range(24)])
    assert result['rate']==0 and result['account_bootstrap']['ci95'] is None


def test_blocks_are_single_fixed_size_per_account_selected_without_outcomes():
    rows=[{'primary_account_id':a,'published_at':f'2026-09-{day:02d}','id':str(i)} for i,(a,day) in enumerate([('a',16),('a',13),('a',15),('a',14),('b',13),('b',14)])]
    idx,groups=P.blocks(rows,np.arange(6))
    assert groups.tolist()==['a'] and idx.tolist()==[[1,3,2]]


def test_distinct_days_use_moscow_day_and_require_three_days():
    dates=['2026-09-13T20:30:00+00:00','2026-09-13T21:30:00+00:00','2026-09-14T12:00:00+00:00','2026-09-15T09:00:00+00:00']
    rows=[{'primary_account_id':'a','published_at':d,'published':datetime.fromisoformat(d),'id':str(i)} for i,d in enumerate(dates)]
    idx,_=P.blocks(rows,np.arange(4),True)
    assert idx.tolist()==[[0,1,3]]
    idx,_=P.blocks(rows,np.arange(3),True)
    assert idx.shape==(0,3)


def test_small_block_reference_returns_abstention_not_zero_detection_rate():
    rows=[]
    for day in (6,14,21):
        for hour in (1,2,3):
            at=datetime(2026,9,day,hour,tzinfo=timezone.utc)
            rows.append({'primary_account_id':'a','published_at':at.isoformat(),'published':at,'id':str(len(rows)),
                         'endpoints':{24:{'v':10+hour,'r':2},72:{'v':20+hour,'r':3}}})
    result=P.repeated(rows)
    assert result['status']=='rank_resolution_insufficient'
    assert result['injections']=={} and result['common_clear_blocks'] is None
    assert result['baseline']['mean_components']['status'].startswith('abstain')


def test_smooth_shift_and_single_spike_have_different_block_scores():
    z=np.zeros((3,4));z[0,0]=3
    scores=P.block_scores(z,np.array([[0,1,2]]))
    assert scores['maximum_post'][0]==3 and scores['mean_components'][0]==1
    z[:,0]=1
    scores=P.block_scores(z,np.array([[0,1,2]]))
    assert scores['maximum_post'][0]==scores['mean_components'][0]==1


def test_held_out_targets_do_not_enter_model_or_its_scales():
    rows=[{'primary_account_id':'a'}]*8
    early=np.column_stack([np.arange(8)+10,np.arange(8)+2]).astype(float)
    late=early*2
    fit=np.arange(4);m=P.FourReferences(rows,fit,early,late)
    changed_early,changed_late=P.inject(early,late,np.arange(4,8),1.,'early')
    n=P.FourReferences(rows,fit,changed_early,changed_late)
    assert np.array_equal(m.scales,n.scales)
    for a,b in zip(m.beta,n.beta):assert np.array_equal(a,b)
    assert m.center==n.center and m.sd==n.sd


def test_injections_preserve_unselected_values_and_monotone_counts():
    early=np.array([[12,2],[31,0]],float);late=np.array([[21,4],[42,1]],float)
    for mode in ('late','early'):
        a,b=P.inject(early,late,np.array([0]),.3,mode)
        assert np.array_equal(a[1],early[1]) and np.array_equal(b[1],late[1])
        assert np.all(b>=a) and np.all(b==np.rint(b))
    assert np.array_equal(early,[[12,2],[31,0]])
