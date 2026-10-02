"""Temporal source audit, sparse-window evidence and independent context sampling."""
from pathlib import Path
import copy
from datetime import timedelta
import sys

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research/smart-engagement-2026-09/scripts'))
import readiness_audit as A


def match(at,same=True):return {'created_at':at,'same_values':same}


def test_created_at_cutoffs_are_strict_and_timezone_aware():
    assert A.classify([match('2026-09-20T20:59:59.999999Z')])=='exact_before_fit_cutoff'
    assert A.classify([match('2026-09-21T00:00:00+03:00')])=='exact_late'
    assert A.classify([match('2026-09-28T00:00:00Z')])=='exact_after_panel_cutoff'


def test_old_time_never_repairs_missing_ambiguous_or_changed_identity():
    m=match('2026-09-01T00:00:00Z')
    assert A.classify([])=='missing'
    assert A.classify([m,m])=='ambiguous'
    assert A.classify([m|{'same_values':False}])=='changed_values'
    assert A.classify([match(None)])=='unknown_time'


def batch():return {'batch_id':0,'account':'a','requested':2,'input_sha256':'hash'}


def manifest():return {'batches':[batch()], 'requested':2,'accounts':1}


def response():return batch()|{'query_time':'2026-09-28T12:00:00Z','counts':{'exact_before_fit_cutoff':2}}


def test_complete_endpoint_match_is_not_full_replay_or_commit_proof():
    result=A.temporal_report(manifest(),[response()])
    assert result['selected_rows_before_cutoff_gate']
    assert not result['full_historical_replay_verified'] and not result['analyzer_commit_visibility_verified']


def test_missing_batches_and_empty_audit_stay_unknown():
    r=A.temporal_report(manifest(),[])
    assert r['missing_batches']==[0] and r['audited']==0 and not r['selected_rows_before_cutoff_gate']
    r=A.temporal_report({'batches':[],'requested':0,'accounts':0},[])
    assert not r['selected_rows_before_cutoff_gate']


@pytest.mark.parametrize('change',[{'input_sha256':'other'},{'requested':3},{'counts':{'exact_before_fit_cutoff':3}},{'counts':{'new':2}}])
def test_invalid_raw_audit_cannot_pass(change):
    with pytest.raises(ValueError):A.temporal_report(manifest(),[response()|change])


def test_replayed_batch_cannot_double_count_availability():
    with pytest.raises(ValueError,match='Duplicate'):A.temporal_report(manifest(),[response(),response()])


def endpoint():
    return {'publication_id':'00000000-0000-0000-0000-000000000001','published_month':'2026-09-01',
        'observed_at':'2026-09-14T00:00:00+03:00','revision':1,'r':10,'v':100}


def test_query_has_bounded_index_keys_and_does_not_replace_versions():
    sql,b=A.query_batch('00000000-0000-0000-0000-000000000002',[endpoint()],0)
    assert 'BEGIN READ ONLY' in sql and "statement_timeout='15s'" in sql and 'LIMIT 3' in sql
    assert 's.published_month=x.published_month' in sql and 's.observed_at=x.observed_at' in sql
    assert 's.correction_sequence=x.revision' in sql and 'UPDATE ' not in sql and 'DELETE ' not in sql
    assert b['requested']==1 and b['input_sha256']==A.digest([endpoint()])
    for rows in ([],[endpoint()]*501):
        with pytest.raises(ValueError):A.query_batch('00000000-0000-0000-0000-000000000002',rows,0)


def test_context_selection_ignores_names_scores_and_counter_values():
    cohort=[{'id':str(i),'title':'visible name'} for i in range(20)]
    posts=[{'post':{'id':f'{a}:{j}','primary_account_id':str(a),'is_repost':False,
        'published_at':'2026-09-15T00:00:00+03:00','publication_type':'text'},'daily':[{'r':a*j}]} for a in range(20) for j in range(5)]
    first=A.select_cards(posts,cohort)
    for c in cohort:c.update(title='another name',score=100000)
    for p in posts:p['daily']=[{'r':1000000,'v':1}]
    assert A.select_cards(posts,cohort)==first and len(first['accounts'])==12 and len(first['cards'])==24
    assert len({c['post'] for c in first['cards']})==24


def test_sparse_three_day_grid_cannot_prove_two_days_within_week():
    origin=A.T.dt('2026-08-31T00:00:00+03:00')
    intervals=[(origin+timedelta(days=p),origin+timedelta(days=p+3)) for p in range(4)]
    assert A.I.minimum_days(intervals)==1
    longer=[(origin+timedelta(days=p),origin+timedelta(days=p+3)) for p in range(11)]
    assert A.I.minimum_days(longer)>=2


def test_larger_window_keeps_known_bounds_without_manufacturing_reads():
    base=A.P.ordinary_world(A.rng(66,9,1));one=A.G.alter(base,0,'small_daily30',A.rng(66,9,2))
    origin=A.T.dt('2026-08-31T00:00:00+03:00')
    posts,truth=A.I.paths(one,origin,'every_third',A.rng(7).random((31,A.P.NPOSTS)),A.rng(8).integers(0,3,A.P.NPOSTS))
    prepared,_=A.I.prepare(posts);previous=(0,0)
    for length in A.LENGTHS:
        end=origin+timedelta(days=30);start=end-timedelta(days=length)
        w=A.W.extract(prepared,start,end,source_verified=True)['target']
        actual=[v for v in truth if start<=v['at']<end]
        assert previous[0]<=w['net_r']<=sum(v['dr'] for v in actual)
        assert previous[1]<=w['minimum_growth_days']<=len({v['at'].date() for v in actual})
        previous=(w['net_r'],w['minimum_growth_days'])


def cards():return {'cards':[{'card_id':'B02-01','post':'p','account':'a','published_at':'2026-09-15','type':'text'}]}


def test_review_packet_never_fills_independent_answers_or_invents_campaign():
    raw=[{'requested_post':'p','post':'p','account':'a','public_url':'https://max.ru/example/123'}]
    report=A.prepare_review(cards(),raw);packet=A.render_packet(report)
    assert report['independent_reviews_completed']==0 and report['campaigns_confirmed'] is None
    assert report['cards'][0]['reviewer1'] is None and report['cards'][0]['status']=='catalog_url_not_fetched'
    assert 'https://max.ru/example/123' in packet and 'score' not in packet and 'joint' not in packet


def test_review_missing_wrong_identity_and_untrusted_urls_are_unknown():
    assert A.prepare_review(cards(),[])['cards'][0]['public_url'] is None
    for url in ('https://elsewhere.invalid/post','http://max.ru/post','https://user:password@max.ru/post'):
        r=A.prepare_review(cards(),[{'requested_post':'p','post':'p','account':'a','public_url':url}])
        assert r['cards'][0]['public_url'] is None
    r=A.prepare_review(cards(),[{'requested_post':'p','post':'other','account':'a','public_url':'https://max.ru/post'}])
    assert r['cards'][0]['status']=='identity_mismatch'


def test_registered_protocol():assert A.provenance(ROOT)['protocol_sha256']==A.PROTOCOL_SHA
