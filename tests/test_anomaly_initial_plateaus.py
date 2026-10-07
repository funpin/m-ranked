from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

import numpy as np
import pytest

from test_bounded_reaction_burst import subject, detect
from test_anomaly_collection_log import series
from anomaly_analysis.v2.detectors import DetectorContext, bounded_reaction_burst, burst_plateau, reactions_exceed_views
from anomaly_analysis.v2.domain import Level, Metric
from anomaly_analysis.v2.levels import assess, compact, level_for
from anomaly_analysis.v2.series import CollectionCadence, prepare

V, R = Metric.VIEWS, Metric.REACTIONS
CASES = json.loads((Path(__file__).parent/'fixtures/anomaly_initial_plateaus.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda c:c['account'])
def test_real_early_packs_are_visible_without_an_account_norm(case):
    s = subject(case)
    result = assess(s)
    assert int(result.level) == case['expected_level']
    assert level_for(result.signs) is result.level
    if case['expected_level'] == 3:
        assert any(sign.render.get('plateauEvidence') for sign in result.signs)
    else:
        assert all(sign.strength == .5 and sign.render.get('roundingLimited') for sign in result.signs)
        assert not any(sign.render.get('plateauEvidence') or 'burstLower' in sign.render for sign in result.signs)
    assert all(sign.interval.start >= s.observed_at[0] for sign in result.signs)
    payload = compact(result)
    assert len(payload['quality']['summary']) <= 600
    assert all(len(sign['formula']) <= 400 for sign in payload['signals'])


def slice_series(s, indexes):
    return replace(s, observed_at=tuple(s.observed_at[i] for i in indexes),
                   values={m:tuple(values[i] for i in indexes) for m,values in s.values.items()},
                   qualities={m:tuple(values[i] for i in indexes) for m,values in s.qualities.items()},
                   interval_uncertain=tuple(s.interval_uncertain[i] for i in indexes),
                   reaction_breakdowns=tuple(s.reaction_breakdowns[i] for i in indexes) if s.reaction_breakdowns else ())


def test_pack_already_present_at_first_read_is_not_invented_as_a_zero_to_count_jump():
    s = subject(CASES[0])
    s = slice_series(s, range(1, len(s.observed_at)))
    signs = detect(s)
    initial = [sign for sign in signs if sign.render.get('mode') == 'initial_plateau']
    assert initial and initial[0].interval.start == s.observed_at[0]
    assert initial[0].render['beforeRange'][0] > 0
    assert 'Рост до первого замера не наблюдался' in initial[0].formula
    assert level_for(initial) is Level.ARTIFICIAL_ACTIVITY_SIGNS


@pytest.mark.parametrize('amount,expected', [(12,2),(25,3),(40,3),(111,3)])
@pytest.mark.parametrize('platform', ['telegram','vk','max','rutube'])
def test_small_early_packs_are_not_normalized_away(amount,expected,platform):
    s = series([(1,30,0),(6,60,amount)] + [(m,60+(m-6)*2,amount) for m in range(11,247,5)],platform=platform)
    p = prepare(s,s.observed_at[-1],CollectionCadence())
    # Even an arbitrary channel norm cannot suppress this absolute pattern.
    signs = bounded_reaction_burst.detect(p,DetectorContext(platform,norm=object()))
    assert int(level_for(signs)) == expected


def test_same_pack_is_found_later_without_needing_an_early_baseline():
    s = series([(1,30,0),(6,60,40)] + [(m,60+(m-6)*2,40) for m in range(11,247,5)])
    s = replace(s, observed_at=tuple(at+timedelta(days=2) for at in s.observed_at))
    assert level_for(detect(s)) is Level.ARTIFICIAL_ACTIVITY_SIGNS


@pytest.mark.parametrize('problem',['short_tail','sparse_tail','unknown','uncertain','no_view_growth','reset','late_first_read'])
def test_inadequate_or_incompatible_evidence_cannot_become_a_confirmed_plateau(problem):
    s = subject(CASES[0])
    if problem == 'short_tail': s = slice_series(s,range(6))
    if problem == 'sparse_tail': s = slice_series(s,[0,1,len(s.observed_at)-1])
    if problem == 'unknown': s = replace(s,qualities={m:('unknown',)*len(s.observed_at) for m in (V,R)})
    if problem == 'uncertain': s = replace(s,interval_uncertain=(True,)*len(s.observed_at))
    if problem == 'no_view_growth': s = replace(s,values={**s.values,V:(244,)*len(s.observed_at)})
    if problem == 'reset':
        values=list(s.values[R]); values[10]=0
        s=replace(s,values={**s.values,R:tuple(values)},qualities={**s.qualities,R:('exact',)*len(values)},reaction_breakdowns=())
    if problem == 'late_first_read': s=slice_series(s,range(5,len(s.observed_at)))
    assert not any(sign.render.get('plateauEvidence') for sign in detect(s))


def test_gradual_coupled_organic_start_is_not_a_pack_even_at_high_engagement():
    s=series([(m,int(500*(1-np.exp(-m/70))),int(220*(1-np.exp(-m/70)))) for m in range(1,247,5)],platform='telegram')
    assert not detect(s)


@pytest.mark.parametrize('kind',['overlap','exact','paid','unknown','repost','uncertain'])
def test_telegram_order_is_visible_but_respects_counter_evidence(kind):
    s=series([(6,104,110)],platform='telegram')
    if kind == 'overlap':
        s=replace(s,qualities={V:('rounded',),R:('rounded',)},reaction_breakdowns=({'👍':110},))
    if kind == 'paid': s=replace(s,reaction_breakdowns=({'paid:star':110},))
    if kind == 'unknown': s=replace(s,qualities={V:('unknown',),R:('exact',)})
    if kind == 'repost': s=replace(s,is_repost=True)
    if kind == 'uncertain': s=replace(s,interval_uncertain=(True,))
    result=assess(s)
    # Просмотры репоста — его собственные: правило 1:1 действует и для него.
    if kind in {'overlap','exact','repost'}:
        assert result.level is Level.WEAK_SIGNAL
        assert result.signs[0].pattern == 7
        assert result.signs[0].render['boundsOverlap'] == (kind=='overlap')
    else:
        assert not reactions_exceed_views.detect(prepare(s,s.observed_at[-1],CollectionCadence()),DetectorContext('telegram'))


@pytest.mark.parametrize('platform',['telegram','vk','max','rutube'])
def test_short_significant_late_view_burst_has_highest_level(platform):
    points=[(m,100+int(m/5),0) for m in range(0,601,5)]
    points += [(m,1220,0) for m in range(605,851,5)]
    s=series(points,platform=platform)
    result=assess(s)
    assert result.level is Level.ARTIFICIAL_ACTIVITY_SIGNS
    assert any(sign.metric is V and sign.render.get('plateauEvidence') for sign in result.signs)
    assert level_for(result.signs) is result.level
    # Stretching the same rise across a polling gap cannot preserve priority.
    s=slice_series(s,[i for i,p in enumerate(points) if p[0]<=510 or p[0]>=605])
    signs=burst_plateau.detect(prepare(s,s.observed_at[-1],CollectionCadence()),DetectorContext(platform))
    assert not any(sign.render.get('plateauEvidence') for sign in signs)
