"""Эталон анализа v2: синтетика и выгруженные реальные ряды.

Синтетика строится кодом модуля при каждом прогоне, файлов у неё нет.
Выгруженные реальные ряды лежат вне репозитория и берутся из
`ANOMALY_REFERENCE_DIRS`, если переменная задана. Каждый случай проверяется
при зрелой норме, как его проверяет ночное задание перед принятием версии.
"""
from __future__ import annotations

import os

import pytest

from anomaly_analysis.v2.domain import SIGN_PATTERNS, Level
from anomaly_analysis.v2.levels import YOUNG_NORM_CAP, assess, reference_assessor
from anomaly_analysis.v2.norms import ReferencePost, check_reference
from anomaly_analysis.norms_job import load_reference
from anomaly_analysis.v2.reference import rendered
from anomaly_reference.mature_norms import norms_for, platform_norms, synthetic_cases

CASES = list(synthetic_cases().values()) + load_reference(os.environ.get("ANOMALY_REFERENCE_DIRS", ""))


def test_generator_is_deterministic() -> None:
    """Разметка держится на том, что ряды не меняются между прогонами."""
    assert list(rendered()) == list(rendered())


def test_synthetic_reference_covers_every_pattern_and_honest_case() -> None:
    synthetic = list(synthetic_cases().values())
    assert set().union(*(case.expected_patterns for case in synthetic)) == SIGN_PATTERNS
    honest = [case for case in synthetic if not case.expected_patterns]
    assert len(honest) >= 10
    assert all(case.expected_max_level <= Level.WEAK_SIGNAL for case in honest)
    assert {case.subject.platform for case in honest} == {"telegram", "vk", "max", "rutube"}
    assert any(case.subject.is_repost for case in honest)
    # Сильные формы со скриншотов владельца — высший уровень.
    for name in ("owner_vk_497246_linear_with_leading_likes", "owner_vk_reaction_jumps_on_decayed_post"):
        assert synthetic_cases()[name].expected_min_level == Level.ARTIFICIAL_ACTIVITY_SIGNS


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_reference_case(case) -> None:
    if case.expected_min_level is None or case.expected_max_level is None:
        pytest.skip("выгруженный ряд ещё не размечен")
    verdict = assess(case.subject, case.siblings, norms=norms_for(case), subscribers=case.subscribers)
    found = {sign.pattern for sign in verdict.signs}
    assert case.expected_min_level <= verdict.level <= case.expected_max_level, (verdict.level, found)
    assert case.expected_patterns <= found, found
    # Без нормы признаки, опирающиеся на неё, не сильнее среднего: высокий
    # уровень тогда дают только абсолютные детекторы.
    young = assess(case.subject, case.siblings, subscribers=case.subscribers)
    assert all(sign.strength <= YOUNG_NORM_CAP for sign in young.signs if sign.norm_confidence is not None)


def test_reference_check_accepts_the_mature_norm() -> None:
    for platform in ("telegram", "vk", "max", "rutube"):
        cases = [ReferencePost(name, case.subject, case.siblings, case.expected_min_level)
                 for name, case in synthetic_cases().items()
                 if case.subject.platform == platform and len(case.siblings) < 20]
        assert check_reference(platform_norms(platform), cases, reference_assessor()).passed, platform
