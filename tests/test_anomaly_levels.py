"""Сборка уровня v2 и глоссарий ADR-006 для всех текстов вывода."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from anomaly_analysis.v2.detectors import DetectorContext
from anomaly_analysis.v2.domain import Family, Interval, Level, Metric, Sign
from anomaly_analysis.v2 import levels
from anomaly_analysis.v2.levels import (
    ALTERNATIVES, DISCLAIMER, LEVEL_LABELS, MAX_SIGNS, QUALITY_TEXTS, SYMBOLS, TITLES, YOUNG_NORM_CAP,
    assess, compact, level_for, run_detectors, verdict,
)
from anomaly_analysis.v2.series import CollectionCadence, prepare
from anomaly_reference.mature_norms import norms_for, synthetic_cases

START = datetime(2026, 3, 2, 9, tzinfo=timezone.utc)
# Запрещённые без независимого доказательства формулировки ADR-006.
FORBIDDEN = ("накрут", "мошен", "фальсиф", "боты подтвержд", "нечестн", "доказанн", "виновн", "fraud")


def sign(pattern: int, family: Family, strength: float, *, hours=(30, 40), norm=None, start=START) -> Sign:
    return Sign(pattern, family, Metric.VIEWS, strength,
                Interval(start + timedelta(hours=hours[0]), start + timedelta(hours=hours[1])),
                timedelta(hours=1), "Δ = 1", norm_confidence=norm)


@pytest.mark.parametrize("signs,expected", [
    ((), Level.NONE),
    ((sign(10, Family.CROSS_METRIC, 0.3),), Level.NONE),
    ((sign(10, Family.CROSS_METRIC, 0.3), sign(2, Family.SHAPE, 0.25)), Level.WEAK_SIGNAL),
    ((sign(10, Family.CROSS_METRIC, 0.5),), Level.WEAK_SIGNAL),
    ((sign(1, Family.VELOCITY, 0.8),), Level.PRONOUNCED_ANOMALY),
    ((sign(2, Family.SHAPE, 0.8), sign(9, Family.SHAPE, 0.9)), Level.PRONOUNCED_ANOMALY),
    ((sign(1, Family.VELOCITY, 0.8), sign(6, Family.CROSS_METRIC, 0.75)), Level.ARTIFICIAL_ACTIVITY_SIGNS),
])
def test_levels_come_from_agreement_of_families(signs, expected):
    assert level_for(signs) is expected


def _prepared(name="honest_organic_telegram"):
    case = synthetic_cases()[name]
    return prepare(case.subject, case.subject.observed_at[-1], CollectionCadence())


def test_young_norm_caps_signs_that_depend_on_it():
    prepared = _prepared()
    context = DetectorContext("telegram")
    young = verdict(prepared, context, [sign(2, Family.SHAPE, 0.95, norm=0.2)], {})
    assert young.level is Level.WEAK_SIGNAL and young.signs[0].strength == YOUNG_NORM_CAP
    mature = verdict(prepared, context, [sign(2, Family.SHAPE, 0.95, norm=0.9)], {})
    assert mature.level is Level.PRONOUNCED_ANOMALY
    absolute = verdict(prepared, context, [sign(1, Family.VELOCITY, 0.95)], {})
    assert absolute.level is Level.PRONOUNCED_ANOMALY


def test_signs_on_unanalyzable_intervals_are_dropped_except_the_gap_pattern():
    prepared = _prepared("honest_gaps_telegram")
    context = DetectorContext("telegram")
    inside, published = (31, 37), prepared.series.published_at
    dropped = verdict(prepared, context, [sign(1, Family.VELOCITY, 0.9, hours=inside, start=published)], {})
    assert dropped.level is Level.NONE and dropped.quality.unanalyzable
    kept = verdict(prepared, context, [sign(4, Family.SHAPE, 0.9, hours=inside, norm=0.9, start=published)], {})
    assert kept.level is Level.PRONOUNCED_ANOMALY


def test_reposts_run_only_the_two_absolute_cross_metric_checks():
    prepared = _prepared("honest_repost_of_foreign_telegram")
    _, versions = run_detectors(prepared, DetectorContext("telegram"))
    assert set(versions) == {"reactions_before_views", "reactions_exceed_views"}
    assert "repost_source_counter" in assess(prepared.series).quality.codes


def test_compact_output_is_bounded_sorted_and_worded():
    prepared = _prepared()
    signs = [sign(pattern, Family.SHAPE, 0.3 + 0.05 * index)
             for index, pattern in enumerate((1, 2, 4, 5, 6, 7, 8, 9, 10))]
    payload = compact(verdict(prepared, DetectorContext("telegram"), signs, {"x": "1"}))
    strengths = [item["strength"] for item in payload["signals"]]
    assert len(strengths) == MAX_SIGNS and strengths == sorted(strengths, reverse=True)
    assert payload["levelLabel"] == LEVEL_LABELS[payload["level"]]
    assert all(item["symbol"] == SYMBOLS[item["pattern"]] for item in payload["signals"])
    assert isinstance(payload["quality"]["summary"], str) and payload["disclaimer"] == DISCLAIMER


def test_every_alternative_code_used_by_a_detector_has_a_text():
    for case in synthetic_cases().values():
        result = assess(case.subject, case.siblings, norms=norms_for(case), subscribers=case.subscribers)
        for item in compact(result)["signals"]:
            assert item["alternatives"] and all(alternative["text"] for alternative in item["alternatives"])


def test_glossary_of_adr_006_holds_for_every_text_and_formula():
    texts = [*ALTERNATIVES.values(), *TITLES.values(), *LEVEL_LABELS.values(), *QUALITY_TEXTS.values(),
             DISCLAIMER]
    for case in synthetic_cases().values():
        result = assess(case.subject, case.siblings, norms=norms_for(case), subscribers=case.subscribers)
        texts.extend(sign.formula for sign in result.signs)
        texts.append(compact(result)["quality"]["summary"])
    for text in texts:
        lowered = text.lower()
        assert not any(word in lowered for word in FORBIDDEN), text


def test_all_symbols_from_the_plan_are_distinct():
    assert len(set(SYMBOLS.values())) == len(SYMBOLS) == 9
    assert np.all([pattern in TITLES for pattern in SYMBOLS])
    assert levels.STRONG > YOUNG_NORM_CAP >= levels.MEDIUM
