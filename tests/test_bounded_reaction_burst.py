from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
from uuid import UUID

import pytest

from anomaly_analysis.v2.detectors import DetectorContext, bounded_reaction_burst
from anomaly_analysis.v2.detectors.bounded_reaction_burst import reaction_bounds
from anomaly_analysis.v2.domain import Level, Metric, PostSeries
from anomaly_analysis.v2.levels import assess, compact
from anomaly_analysis.v2.series import CollectionCadence, prepare
from anomaly_analysis.tools.reference_format import case_payload, parse_case
from anomaly_reference.mature_norms import synthetic_cases

V, R = Metric.VIEWS, Metric.REACTIONS
CASES = json.loads((Path(__file__).parent / 'fixtures/anomaly_reaction_bursts.json').read_text())


def subject(case):
    p, m = case['points'], case['publication']
    return PostSeries(UUID(m['publicationId']), UUID(int=2), m['platform'],
                      datetime.fromisoformat(m['publishedAt']), m['repost'],
                      tuple(datetime.fromisoformat(r['observed_at']) for r in p),
                      {V: tuple(r['v'] for r in p), R: tuple(r['r'] for r in p)},
                      qualities={V: tuple(r['vq'] for r in p), R: tuple(r['rq'] for r in p)},
                      interval_uncertain=tuple(r['uncertain'] for r in p),
                      reaction_breakdowns=tuple(r['breakdown'] for r in p))


def detect(s):
    return bounded_reaction_burst.detect(prepare(s, s.observed_at[-1], CollectionCadence()),
                                         DetectorContext(s.platform))


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['account'])
def test_observed_obvious_bursts_survive_rounding_and_incomplete_early_model(case):
    s = subject(case)
    result = assess(s)
    assert result.level >= Level.PRONOUNCED_ANOMALY
    signs = [item for item in result.signs if item.render.get('kind') == 'bounded_burst']
    assert signs and all(item.render['burstLower'] >= 20 for item in signs)
    assert 'bounded_reaction_counts' in result.quality.codes
    assert all(item.render['timingUnknown'] is True for item in signs)
    # Neither counts nor their precision are silently changed to exact.
    assert all(q == 'rounded' for q in s.qualities[R])
    assert json.loads(json.dumps(compact(result), ensure_ascii=False))['level'] >= 2


def test_repost_lower_bound_exceeds_a_thousand_without_using_repost_views():
    s = subject(CASES[0])
    assert s.is_repost
    s = replace(s, values={R: s.values[R]}, qualities={R: s.qualities[R]})
    assert max(sign.render['burstLower'] for sign in detect(s)) >= 1000


def test_five_minute_burst_is_not_diluted_into_a_quiet_fifteen_minute_window():
    signs = detect(subject(CASES[4]))
    assert any(sign.scale.total_seconds() < 15*60 and sign.render['burstLower'] >= 125
               for sign in signs)


@pytest.mark.parametrize('quality', ['unknown', 'invalid', 'estimated', 'suspected_reset', 'degraded'])
def test_unknown_or_failed_precision_is_never_promoted(quality):
    s = subject(CASES[0])
    s = replace(s, qualities={m: (quality,)*len(s.observed_at) for m in (V,R)})
    assert detect(s) == ()


def test_missing_breakdowns_uncertainty_and_mismatched_totals_abstain():
    s = subject(CASES[0])
    for changed in (
        replace(s, reaction_breakdowns=()),
        replace(s, interval_uncertain=(True,)*len(s.observed_at)),
        replace(s, reaction_breakdowns=({'👍': 1},)*len(s.observed_at)),
    ):
        assert detect(changed) == ()


def test_telegram_compact_semantics_are_not_applied_to_other_platforms():
    for platform in ('vk', 'max', 'rutube'):
        assert detect(replace(subject(CASES[0]), platform=platform)) == ()


def test_component_bounds_do_not_infer_precision_from_the_sum():
    assert reaction_bounds(1121, 'rounded', {'🗿':1090,'❤':15,'👀':8,'👍':7,'🤣':1}) == (1107,1135)
    assert reaction_bounds(1121, 'rounded', {'🗿':1000,'❤':121}) == (120,2122)
    assert reaction_bounds(0, 'rounded', {}) == (0,0)
    assert reaction_bounds(0, 'rounded', None) is None
    assert reaction_bounds(5, 'rounded', {'paid:star':5}) is None
    assert reaction_bounds(5, 'rounded', {'unknown:web':5}) is None
    assert reaction_bounds(5, 'rounded', {'👍':0,'❤':5}) is None


def test_bounds_cover_each_decimal_compact_display_precision():
    from collector_runtime.public_web import parse_compact_count, compact_count_display_unit
    for text in ('53', '1K', '1.0K', '1.04K', '1.234K', '12M', '1.25M', '1B'):
        count, unit = parse_compact_count(text), compact_count_display_unit(text)
        low, high = reaction_bounds(count, 'rounded', {'👍':count})
        assert low <= max(0,count-unit) and high >= count+unit


def test_no_confirmation_is_invented_from_future_points():
    s = subject(CASES[1])
    at = s.observed_at[4]
    p = prepare(s, at, CollectionCadence())
    assert bounded_reaction_burst.detect(p, DetectorContext(s.platform)) == ()


def test_rounded_honest_organic_forward_and_rhythm_controls():
    for name, case in synthetic_cases().items():
        if not name.startswith('honest_') or case.subject.platform != 'telegram':
            continue
        s = case.subject
        # Keep each displayed value and widen its permitted range, never make
        # the synthetic control more precise than the underlying exact series.
        s = replace(s, qualities={m: ('rounded',)*len(s.observed_at) for m in s.values},
                    reaction_breakdowns=tuple(None if r is None else {} if r==0 else {'👍':r}
                                              for r in s.values[R]))
        assert not detect(s), name


def test_reference_roundtrip_preserves_the_evidence():
    s = subject(CASES[0])
    restored = parse_case(case_payload('public', 'export', 'public counter evidence', s)).subject
    assert restored.reaction_breakdowns == s.reaction_breakdowns
    assert detect(restored)


@pytest.mark.parametrize('platform', ['telegram', 'vk', 'max', 'rutube'])
def test_early_count_comparison_works_for_exact_counters_on_every_platform(platform):
    s = subject(CASES[1])
    s = replace(s, platform=platform, qualities={m: ('exact',)*len(s.observed_at) for m in (V,R)},
                reaction_breakdowns=())
    assert any(sign.render.get('mode') == 'early_ratio' for sign in detect(s))


def test_actual_breakdown_alignment_is_validated():
    s = subject(CASES[0])
    with pytest.raises(ValueError, match='not aligned'):
        replace(s, reaction_breakdowns=({'👍': 1},))


@pytest.mark.parametrize('problem', ['invalid', 'uncertain', 'correction'])
def test_intervening_bad_reaction_read_cannot_be_bridged(problem):
    from datetime import timedelta
    times = tuple(datetime.fromisoformat('2026-01-01T00:00:00+00:00') + timedelta(hours=i/2)
                  for i in range(31))
    reactions = [30 if i < 18 else 1030 for i in range(31)]
    qualities = ['exact'] * 31
    uncertain = [False] * 31
    if problem == 'invalid':
        qualities[17] = 'invalid'
    elif problem == 'uncertain':
        uncertain[17] = True
    else:
        reactions[17] = 20
    s = PostSeries(UUID(int=1), UUID(int=2), 'telegram', times[0], False, times,
                   {R: tuple(reactions)}, qualities={R: tuple(qualities)},
                   interval_uncertain=tuple(uncertain))
    assert detect(s) == ()
