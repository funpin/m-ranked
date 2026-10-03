"""«Находки»: пороги и эталон расчёта индекса к норме аккаунта.

SQL в api/sql/findings.py считает то же самое; эти функции закрепляют
семантику в модульных тестах и служат эталоном для проверки SQL на базе.
"""
from __future__ import annotations

from decimal import Decimal
from statistics import median
from typing import Iterable

NORM_WINDOW_DAYS = 30
MIN_NORM_SAMPLE = 10
INTERACTION_NORM_FLOOR = 5
VIEW_NORM_FLOOR = 50
FINDING_MIN_INDEX = Decimal("1.5")
FINDING_MIN_INTERACTIONS = 10
AGE_HOURS = (24, 12, 6, 3, 1)
FINDINGS_PERIOD_DAYS = {"1d": 1, "7d": 7, "30d": 30}
FINDING_TYPES = ("text", "photo", "album", "video", "other")
MAIN_TYPES = ("text", "photo", "album", "video")
PAGE_CAP = 200
GROUP_POSTS = 3


def type_bucket(publication_type: str) -> str:
    return publication_type if publication_type in MAIN_TYPES else "other"


def norm(values: Iterable[int | None]) -> tuple[Decimal | None, int]:
    known = [value for value in values if value is not None]
    if not known:
        return None, 0
    return Decimal(str(median(known))), len(known)


def index(value: int | None, norm_value: Decimal | None, sample: int,
          floor: int) -> Decimal | None:
    if value is None or norm_value is None or sample < MIN_NORM_SAMPLE:
        return None
    return Decimal(value) / max(norm_value, Decimal(floor))


def is_finding(interaction_index: Decimal | None, interactions: int | None) -> bool:
    return (interaction_index is not None and interactions is not None
            and interaction_index >= FINDING_MIN_INDEX
            and interactions >= FINDING_MIN_INTERACTIONS)
