from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import UUID

import numpy as np
import pytest

from anomaly_analysis.v2.domain import PostSeries,Metric,Sign,Family,Interval
from anomaly_analysis.v2.series import prepare,CollectionCadence
from anomaly_analysis.v2.store import series_from_rows
from anomaly_analysis.v2.levels import assess,sign_payload
from anomaly_analysis.v2.detectors.base import SiblingActivity
from anomaly_analysis.v2.worker import _carried
from anomaly_analysis.tools.reference_format import case_payload,parse_case

T=datetime(2026,9,1,tzinfo=timezone.utc)
V,R=Metric.VIEWS,Metric.REACTIONS


def measured(qualities,uncertain=None):
    n=len(qualities)
    return PostSeries(UUID(int=1),UUID(int=2),'max',T,False,
        tuple(T+timedelta(minutes=5*i) for i in range(n)),
        {V:tuple(100+10*i for i in range(n)),R:tuple(5+i for i in range(n))},
        qualities={V:tuple(qualities),R:('exact',)*n},
        interval_uncertain=(False,)*n if uncertain is None else uncertain)


def test_partial_quality_map_is_not_permission_to_assume_other_metrics_exact():
    s=replace(measured(['exact']*3),qualities={V:('exact',)*3})
    assert s.exact_values(V)==(100,110,120) and s.exact_values(R)==(None,)*3
    with pytest.raises(TypeError):s.qualities[V]=('exact',)*3
    with pytest.raises(ValueError):replace(s,qualities={V:('exact',)})
    with pytest.raises(ValueError):replace(s,interval_uncertain=(False,1,False))


def test_rounded_unknown_and_uncertain_points_cannot_make_precise_grid():
    for q in ('rounded','unknown','degraded','invalid','suspected_reset'):
        s=measured([q]*20);p=prepare(s,s.observed_at[-1],CollectionCadence())
        assert V not in p.metrics and R in p.metrics
        assert 'non_exact_counters' in assess(s).quality.codes
    s=measured(['exact']*20,uncertain=(True,)*20)
    assert not prepare(s,s.observed_at[-1],CollectionCadence()).metrics
    assert not assess(s).signs and 'uncertain_observations' in assess(s).quality.codes
    assert 'no_precise_metrics' in assess(s).quality.codes


def test_single_bad_interior_read_is_not_bridged_into_grid_or_gap_growth():
    s=measured(['exact']*13)
    qs=list(s.qualities[V]);qs[6]='rounded';s=replace(s,qualities={**s.qualities,V:tuple(qs)})
    p=prepare(s,s.observed_at[-1],CollectionCadence())
    v=p.metrics[V];g=v.grids[timedelta(hours=1)]
    assert not g.usable.any()
    assert v.gaps and all(not gap.count_change_trusted for gap in v.gaps)
    assert v.coverage<1
    # Need at least two output hours for this adapter.
    s=replace(s,observed_at=tuple(T+timedelta(minutes=10*i) for i in range(13)))
    a=SiblingActivity.from_series([s],T.timestamp(),s.observed_at[-1].timestamp())
    assert np.isnan(a.views).all() and np.isfinite(a.reactions).all()


def test_future_bad_quality_does_not_change_past_preparation_codes():
    s=measured(['exact']*12+['rounded'])
    p=prepare(s,s.observed_at[-2],CollectionCadence())
    assert not p.quality_codes


def test_external_loader_carries_flags_and_fails_closed_if_uncertainty_absent():
    row={'id':UUID(int=1),'primary_account_id':UUID(int=2),'platform':'telegram',
         'published_at':T,'is_repost':False,'observed_at':T,
         'views_count':1200,'views_quality':'rounded','reactions_count':8,'reactions_quality':'exact',
         'comments_count':None,'comments_quality':'unknown','shares_count':None,'shares_quality':'unknown',
         'interval_uncertain':False}
    s=series_from_rows([row]);assert s.values[V]==(1200,) and s.qualities[V]==('rounded',)
    assert s.exact_values(V)==(None,) and s.exact_values(R)==(8,)
    del row['interval_uncertain'];assert series_from_rows([row]).exact_values(R)==(None,)


def test_reference_roundtrip_preserves_precision_and_legacy_export_abstains():
    s=measured(['rounded','exact','unknown'],uncertain=(False,True,False))
    payload=case_payload('x','export','example',s)
    out=parse_case(payload).subject
    assert out.qualities==s.qualities and out.interval_uncertain==s.interval_uncertain
    del payload['posts'][0]['qualities'];del payload['posts'][0]['interval_uncertain']
    out=parse_case(payload).subject
    assert out.exact_values(V)==(None,)*3 and not assess(out).signs


def test_legacy_synchrony_cannot_survive_a_quality_semantics_change():
    sign=Sign(8,Family.SYNCHRONY,R,.9,Interval(T,T+timedelta(hours=1)),timedelta(hours=1),'test')
    payload=sign_payload(sign);row=SimpleNamespace(signals=[payload])
    assert _carried(row,T+timedelta(days=1))==()
    payload['render']['measurementMode']='exact_quality_v1'
    assert len(_carried(row,T+timedelta(days=1)))==1


def test_hourly_input_keeps_bad_read_and_stale_baseline_unknown():
    first=int(T.timestamp()/3600)
    rows=[{'publication_id':UUID(int=1),'published_at':T-timedelta(days=7),
           'hour':first+offset,'views':value,'reactions':value}
          for offset,value in [(-4,10),(0,20),(1,None),(2,40),(3,50)]]
    a=SiblingActivity.from_hourly(rows,first,first+4)
    assert np.isnan(a.views[0,:3]).all()
    assert a.views[0,3]==10


def test_dropped_leading_and_trailing_reads_reduce_coverage():
    s=measured(['rounded']+['exact']*11+['rounded'])
    p=prepare(s,s.observed_at[-1],CollectionCadence())
    assert p.metrics[V].coverage==pytest.approx(10/12)
    assert p.metrics[R].coverage==1
