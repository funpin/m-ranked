"""Зрелые нормы для эталона: строятся из синтетического фона площадок.

Эталон проверяется так же, как его проверяет ночное задание: при принятой
норме площадки, а для аккаунта с двадцатью чистыми постами — при его
собственной норме, заякоренной к площадке.
"""
from __future__ import annotations

from functools import lru_cache

from anomaly_analysis.tools.reference_format import ReferenceCase
from anomaly_analysis.v2.norms import NormSet, build_account_norm, build_norms
from anomaly_analysis.v2.series import DAY, CollectionCadence, prepare

from anomaly_analysis.v2.reference import background, synthetic_reference

CADENCE = CollectionCadence()
# Фон отслеживается десять суток: доля итога считается на седьмых.
FINAL_AGE = 7 * DAY


def _prepared(series):
    return prepare(series, series.observed_at[-1], CADENCE)


@lru_cache(maxsize=None)
def platform_norms(platform: str) -> NormSet:
    posts = {account: [_prepared(item) for item in items] for account, items in background(platform).items()}
    return build_norms(platform, posts, final_age=FINAL_AGE)


def norms_for(case: ReferenceCase) -> NormSet:
    norms = platform_norms(case.subject.platform)
    if len(case.siblings) >= 20:
        own = build_account_norm(norms.platform, case.subject.account_id,
                                 [_prepared(item) for item in case.siblings], final_age=FINAL_AGE)
        if own is not None:
            return NormSet(norms.platform, {case.subject.account_id: own})
    return norms


@lru_cache(maxsize=1)
def _synthetic() -> tuple[ReferenceCase, ...]:
    return tuple(synthetic_reference())


def synthetic_cases() -> dict[str, ReferenceCase]:
    return {case.case_id: case for case in _synthetic()}
