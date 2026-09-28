from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import math
from uuid import UUID

import pytest

from anomaly_analysis.v2.domain import Family, Level, Metric, PostSeries
from anomaly_analysis.v2.levels import assess, compact, level_for
from anomaly_analysis.v2.mature_reference import MatureReference, bundled_reference, endpoints

T=datetime(2026,9,21,tzinfo=timezone.utc)
A=UUID(int=10)
V,R=Metric.VIEWS,Metric.REACTIONS


def reference_payload():
    components=[]
    for conditional in (True,False):
        for metric,count in (('views',100),('reactions',10)):
            components.append(dict(conditional=conditional,metric=metric,intercept=math.log1p(count),
                                   slope=1. if conditional else 0.,center=math.log1p(count),sd=1.,scale=.1,
                                   effects={str(A):0.}))
    return dict(schema_version='1.0.0',reference_version='test-v1',platform='max',
                fit_start='2026-09-06T00:00:00+00:00',calibration_end='2026-09-17T00:00:00+00:00',
                available_at='2026-09-20T00:00:00+00:00',expires_at='2026-10-18T00:00:00+00:00',
                fit_count=100,calibration_count=100,account_counts={str(A):100},cutoff=2.,components=components)


@pytest.fixture
def reference():return MatureReference.from_payload(reference_payload())


def series(early=(100,10),late=(1000,100),hours=(24,72)):
    return PostSeries(UUID(int=1),A,'max',T,False,tuple(T+timedelta(hours=h) for h in hours),
                      {V:(early[0],late[0]),R:(early[1],late[1])},
                      qualities={V:('exact','exact'),R:('exact','exact')},interval_uncertain=(False,False))


def test_two_references_are_one_weak_family_even_for_huge_counts(reference):
    s=series(late=(10**12,10**11))
    signs=reference.detect(s,T+timedelta(hours=72))
    assert {x.pattern for x in signs}=={11,12}
    assert {x.family for x in signs}=={Family.VELOCITY}
    assert level_for(signs)==Level.WEAK_SIGNAL
    assert all(x.strength==.5 and x.render['observed']>x.render['upper'] for x in signs)
    assert all(x.alternatives for x in signs)
    result=assess(s,reference=reference)
    assert {11,12}<={x.pattern for x in result.signs}
    assert result.detector_versions['mature_reference_model']=='test-v1'
    json.dumps(compact(result),allow_nan=False)


def test_early_scaled_growth_can_be_absorbed_by_conditional_but_not_history(reference):
    signs=reference.detect(series(early=(1000,100),late=(1000,100)),T+timedelta(hours=72))
    assert {x.pattern for x in signs}=={11}


@pytest.mark.parametrize('quality',['rounded','unknown','invalid','suspected_reset'])
def test_any_imprecise_endpoint_abstains_without_zero_or_interpolation(reference,quality):
    s=series();s=replace(s,qualities={V:('exact',quality),R:('exact','exact')})
    assert reference.detect(s,T+timedelta(hours=72))==()


def test_latest_bad_read_is_not_replaced_by_older_exact_read(reference):
    s=series();s=replace(s,observed_at=tuple(T+timedelta(hours=h) for h in (24,70,72)),
        values={V:(100,900,1000),R:(10,90,100)},qualities={V:('exact','exact','unknown'),R:('exact',)*3},
        interval_uncertain=(False,)*3)
    assert endpoints(s,T+timedelta(hours=72))[1]=='nonexact_endpoint'


def test_known_drop_prevents_signal_even_if_final_count_has_recovered(reference):
    s=series();s=replace(s,observed_at=tuple(T+timedelta(hours=h) for h in (23,24,72)),
        values={V:(200,100,1000),R:(10,10,100)},qualities={V:('exact',)*3,R:('exact',)*3},
        interval_uncertain=(False,)*3)
    assert endpoints(s,T+timedelta(hours=72))[1]=='known_decrease'
    assert reference.detect(s,T+timedelta(hours=72))==()


@pytest.mark.parametrize('changes',[
    {'platform':'vk'},{'platform':'telegram'},{'platform':'rutube'},
    {'account_id':UUID(int=99)},{'is_repost':True},
    {'interval_uncertain':(False,True)}, {'qualities':{}},
    {'published_at':T-timedelta(days=5)}, {'published_at':T+timedelta(days=40)},
])
def test_platform_time_precision_and_account_scope_fail_closed(reference,changes):
    assert reference.detect(replace(series(),**changes),T+timedelta(days=100))==()


def test_checkpoint_is_not_examined_early_and_later_data_cannot_change_it(reference):
    s=series()
    assert reference.detect(s,T+timedelta(hours=71,minutes=59))==()
    expected=reference.detect(s,T+timedelta(hours=72))
    future=replace(s,observed_at=(*s.observed_at,T+timedelta(days=10)),
        values={V:(100,1000,1),R:(10,100,1)},qualities={V:('exact',)*3,R:('exact',)*3},
        interval_uncertain=(False,)*3)
    assert reference.detect(future,T+timedelta(days=10))==expected


def test_window_bounds_and_no_future_endpoint(reference):
    for hours in ((20.9,72),(24.1,72),(24,65.9),(24,72.1)):
        assert reference.detect(series(hours=hours),T+timedelta(hours=73))==()
    assert reference.detect(series(hours=(21,66)),T+timedelta(hours=72))


def test_tie_at_joint_threshold_does_not_fire(reference):
    s=series(late=(200,20))
    score=max((math.log1p(s.values[c.metric][-1])-c.prediction(A,s.values[c.metric][0]))/c.scale
              for c in reference.components)
    assert replace(reference,cutoff=score).detect(s,T+timedelta(hours=72))==()


@pytest.mark.parametrize('mutate',[
    lambda p:p.update(calibration_count=19),lambda p:p.update(cutoff=float('nan')),
    lambda p:p.update(platform='vk'),lambda p:p.update(available_at='2026-09-20'),
    lambda p:p.update(expires_at=p['available_at']),lambda p:p['components'][0].update(scale=0),
    lambda p:p['components'][0].update(effects={}),lambda p:p['components'].pop(),
])
def test_corrupt_or_uncalibrated_artifact_is_rejected(mutate):
    payload=deepcopy(reference_payload());mutate(payload)
    with pytest.raises(ValueError):MatureReference.from_payload(payload)


def test_release_artifact_is_loadable_and_cached():
    ref=bundled_reference()
    assert ref is bundled_reference() and ref.fit_count>=100 and ref.calibration_count>=100
    assert ref.platform=='max' and len(ref.components)==4
