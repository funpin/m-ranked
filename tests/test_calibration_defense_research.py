"""Scientific invariants, independent of the observed H32-H35 outcome."""
import importlib.util
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import minimize
from scipy.special import huber

SCRIPT=Path(__file__).resolve().parents[1]/'research/smart-engagement-2026-09/scripts/calibration_defense.py'
spec=importlib.util.spec_from_file_location('calibration_defense',SCRIPT)
C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)


def example():
    rows=[{'primary_account_id':str(i%3),'id':str(i)} for i in range(24)]
    early=np.column_stack([np.arange(24)+10,np.arange(24)+2]).astype(float)
    late=early*2
    late[5]*=20
    return rows,early,late,np.arange(18)


def test_heldout_values_never_enter_robust_fit_or_transform():
    rows,early,late,fit=example()
    a=C.References(rows,fit,early,late,True)
    ee,ll=C.P.inject(early,late,np.arange(18,24),1.,'early')
    b=C.References(rows,fit,ee,ll,True)
    assert a.center==b.center and a.sd==b.sd and a.scales==b.scales
    for x,y in zip(a.beta,b.beta):assert np.array_equal(x,y)


def test_irls_matches_independent_huber_objective_optimizer():
    rows,early,late,fit=example();model=C.References(rows,fit,early,late,True)
    for k,beta in enumerate(model.beta):
        x=model.design(rows,early,k)[fit];y=np.log1p(late[fit,k%2])
        delta=1.345*model.optimization[k]['huber_scale']
        def objective(b):return huber(delta,y-x@b).sum()+5*np.square(b[1:]).sum()
        def gradient(b):return -x.T@np.clip(y-x@b,-delta,delta)+np.r_[0,10*b[1:]]
        result=minimize(objective,np.zeros(x.shape[1]),jac=gradient,method='BFGS',options={'gtol':1e-8})
        assert model.optimization[k]['converged']
        assert objective(beta)==pytest.approx(result.fun,abs=1e-7)
        assert np.max(np.abs(gradient(beta)))<1e-6


def test_account_balancing_is_invariant_to_repeating_one_accounts_calibration():
    values=np.array([1.,2.,8.,9.]);groups=np.array(['a','a','b','b']);score=np.array([5.])
    indices=[0,1,2,3,2,3,2,3]
    for method,equal in [('account_balanced',True),('pooled',False)]:
        a=C.calibrate(score,values,groups,method)
        b=C.calibrate(score,values[indices],groups[indices],method)
        assert bool(np.allclose(a,b))==equal


def test_trim_lowers_threshold_but_its_minimum_rank_increases_as_sample_shrinks():
    values=np.arange(100.);score=np.arange(-1.,102.);groups=np.array(['a']*100)
    ordinary=C.calibrate(score,values,groups,'pooled')
    trimmed=C.calibrate(score,values,groups,'trim_top_10pct')
    assert np.all(trimmed[score<=89]<=ordinary[score<=89]+1e-12)
    assert np.all(trimmed[score>99]>ordinary[score>99])
    assert C.safe_quantile_bounds(values[:90],0)[1]<C.safe_quantile_bounds(values,0)[1]
    assert np.any((trimmed<=.05)&(ordinary>.05))


@pytest.mark.parametrize('values',[np.arange(8.),np.array([1.,1.,2.,3.,3.,3.,9.,12.])])
def test_order_statistic_bounds_cover_every_possible_contamination_identity(values):
    for m in (0,1,2,3):
        for alpha in (.05,.2,.5):
            lo,hi=C.safe_quantile_bounds(values,m,alpha)
            for selected in combinations(range(len(values)),len(values)-m):
                clean=values[list(selected)]
                exact=C.safe_quantile_bounds(clean,0,alpha)[1]
                assert lo<=exact<=hi


def test_small_sample_cannot_get_finite_safe_five_percent_threshold():
    assert C.safe_quantile_bounds(np.arange(18.),0)==(np.inf,np.inf)
    assert C.safe_quantile_bounds(np.arange(19.),0)==(18.,18.)
    with pytest.raises(ValueError):C.safe_quantile_bounds(np.arange(4.),4)


def test_history_selection_uses_identity_not_response_and_is_order_invariant():
    rows,early,late,fit=example();target={'0','1'}
    a=C.selected_history(rows,fit,target,1/3)
    b=C.selected_history(rows,fit[::-1],target,1/3)
    assert set(a)==set(b) and len(a)==4
    assert all(rows[i]['primary_account_id'] in target for i in a)
