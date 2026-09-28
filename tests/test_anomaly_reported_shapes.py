from dataclasses import replace
import json
from pathlib import Path

import pytest

from test_bounded_reaction_burst import subject, detect
from test_anomaly_collection_log import series
from anomaly_analysis.v2.domain import Level, Metric
from anomaly_analysis.v2.levels import assess, compact
from anomaly_analysis.norms_job import is_clean

CASES = json.loads((Path(__file__).parent / 'fixtures/anomaly_reported_shapes.json').read_text())
R, V = Metric.REACTIONS, Metric.VIEWS


@pytest.mark.parametrize('case', CASES, ids=lambda item: item['account'])
def test_real_unconfirmed_shapes_are_visible_and_cannot_enter_the_norm(case):
    s = subject(case)
    result = assess(s)
    assert result.level is Level.WEAK_SIGNAL
    assert result.signs and all(sign.render.get('reportedOnly') for sign in result.signs)
    assert all('burstLower' not in sign.render and 'plateauEvidence' not in sign.render for sign in result.signs)
    payload = compact(result)
    assert not is_clean(payload['level'], payload['signals'])
    assert len(payload['quality']['summary']) <= 600
    assert all(len(sign['formula']) <= 400 for sign in payload['signals'])


@pytest.mark.parametrize('platform', ['telegram', 'vk', 'max', 'rutube'])
def test_repost_candidate_uses_own_reactions_without_source_views(platform):
    s = series([(1, 10000, 1), (6, 10000, 40)] + [(m, 10000, 40) for m in range(11, 247, 5)], platform=platform)
    s = replace(s, is_repost=True, values={R: s.values[R]}, qualities={R: s.qualities[R]})
    signs = detect(s)
    assert signs and all(sign.strength == .5 and sign.metric is R for sign in signs)


@pytest.mark.parametrize('issue', ['missing', 'mismatch', 'paid', 'unknown_component', 'uncertain', 'reset', 'sparse', 'invalid'])
def test_untrusted_or_missing_evidence_cannot_supply_reported_shape(issue):
    s = subject(CASES[2])
    if issue == 'missing': s = replace(s, reaction_breakdowns=())
    if issue == 'mismatch': s = replace(s, reaction_breakdowns=({'👍': 1},) * len(s.observed_at))
    if issue in {'paid', 'unknown_component'}:
        key = 'paid:star' if issue == 'paid' else 'unknown:web'
        s = replace(s, reaction_breakdowns=tuple({key: value} for value in s.values[R]))
    if issue == 'uncertain': s = replace(s, interval_uncertain=(True,) * len(s.observed_at))
    if issue == 'invalid': s = replace(s, qualities={R: ('invalid',) * len(s.observed_at), V: s.qualities[V]})
    if issue == 'reset':
        values = list(s.values[R]); values[16] = 0
        s = replace(s, values={**s.values, R: tuple(values)}, reaction_breakdowns=tuple({'👍': v} if v else {} for v in values))
    if issue == 'sparse':
        from test_anomaly_initial_plateaus import slice_series
        s = slice_series(s, [0, 13, len(s.observed_at) - 1])
    assert not detect(s)
