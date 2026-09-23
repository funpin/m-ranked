"""Синхронные подъёмы на нескольких старых постах аккаунта (по образцу CopyCatch).

Старый пост живёт хвостом; когда в один и тот же час реакции подскакивают у
него и ещё у нескольких старых постов аккаунта, а подписчики не прибывают,
общий внешний толчок (упоминание в новостях) объясняет это хуже, чем
одновременная доставка.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import DAY, HOUR, PreparedSeries
from .base import DetectorContext, SiblingActivity, make_sign, number

ID = "synchronous_rise"
VERSION = "2.0.0"
PATTERN = 8
FAMILY = Family.SYNCHRONY
NEEDS_NORM = False

SCALE = timedelta(hours=1)
# «Старый» пост — старше двух суток: к этому возрасту органика уже в хвосте.
MIN_AGE = 2 * DAY
BASELINE_HOURS = 24
# Подъём — пуассоновский z от шести над медианой собственного хвоста за сутки.
MIN_Z = 6.0
MIN_RISE = 20
# Соседний пост считается синхронным, если подъём у него в пределах часа.
TOLERANCE_HOURS = 1
MIN_SYNCHRONOUS_SIBLINGS = 2
# Прирост подписчиков больше процента за окно — первым объяснением идёт
# внешний толчок, и признак не выставляется.
MAX_SUBSCRIBER_GROWTH = 0.01


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    siblings = context.siblings
    reactions = prepared.metrics.get(Metric.REACTIONS)
    if siblings is None or reactions is None or not siblings.hours.size:
        return ()
    published = prepared.series.published_at.timestamp()
    own = SiblingActivity.from_series((prepared.series,), siblings.hours[0] * HOUR,
                                      siblings.hours[-1] * HOUR + HOUR)
    if own is None:
        return ()
    subject = own.reactions[0]
    subject_ages = own.ages[0]
    signs = []
    for hour in np.flatnonzero(_rises(subject) & (subject_ages >= MIN_AGE)):
        synchronous, eligible = 0, 0
        for index in range(siblings.reactions.shape[0]):
            window = slice(max(0, hour - TOLERANCE_HOURS), hour + TOLERANCE_HOURS + 1)
            if siblings.ages[index, hour] < MIN_AGE or np.isnan(siblings.reactions[index, window]).all():
                continue
            eligible += 1
            synchronous += bool(_rises(siblings.reactions[index])[window].any())
        if synchronous < MIN_SYNCHRONOUS_SIBLINGS:
            continue
        start_age = float(own.hours[hour] * HOUR - published)
        growth = context.subscriber_growth(start_age - HOUR, start_age + 2 * HOUR)
        if growth is not None and growth > MAX_SUBSCRIBER_GROWTH:
            continue
        clock = datetime.fromtimestamp(own.hours[hour] * HOUR, tz=timezone.utc)
        strength = min(1.0, 0.4 + 0.15 * synchronous)
        formula = (f"реакции подросли одновременно у {synchronous + 1} постов аккаунта "
                   f"(+{number(subject[hour])} у этого) в час {clock:%d.%m %H:00} UTC; "
                   f"у {eligible - synchronous} других старых постов — нет")
        signs.append(make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age,
                               start_age + HOUR, SCALE, formula,
                               {"kind": "synchrony", "posts": synchronous + 1, "quiet": eligible - synchronous,
                                "hour": clock.isoformat()}, ("account_mentioned_externally",)))
    return tuple(signs)


def _rises(hourly: np.ndarray) -> np.ndarray:
    """Часы, где прирост резко выше медианы предыдущих суток того же поста."""
    result = np.zeros(hourly.size, dtype=bool)
    for hour in np.flatnonzero(np.nan_to_num(hourly, nan=0.0) >= MIN_RISE):
        history = hourly[max(0, hour - BASELINE_HOURS):hour]
        history = history[~np.isnan(history)]
        if history.size < BASELINE_HOURS // 2:
            continue
        baseline = max(float(np.median(history)), 0.5)
        result[hour] = (hourly[hour] - baseline) / np.sqrt(baseline) >= MIN_Z
    return result
