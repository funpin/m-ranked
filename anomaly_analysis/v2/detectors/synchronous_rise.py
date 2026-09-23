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
VERSION = "2.1.0"
PATTERN = 8
FAMILY = Family.SYNCHRONY
NEEDS_NORM = False

SCALE = timedelta(hours=1)
# «Старый» пост — старше двенадцати часов: первая волна уже сошла, и подъём
# сравнивается с собственным хвостом. Двое суток отсекали самое частое —
# одновременный вброс на посты последних дней.
MIN_AGE = 12 * HOUR
BASELINE_HOURS = 24
# База — медиана собственного хвоста за сутки; пустая история не отменяет
# суждение. Требование полусуток истории отсекало вброс вскоре после
# возобновления сбора (так пропущен вброс 02.09 на постах Московского
# Политеха через час после простоя). Прирост часа известен, только если
# известен уровень предыдущего часа, поэтому накопленное за простой в подъём
# не попадает; защиту несут возраст поста, порог подъёма и два синхронных соседа.
EMPTY_BASELINE = 0.5
# Подъём — пуассоновский z от шести над медианой собственного хвоста за сутки.
MIN_Z = 6.0
# Минимальный прирост часа по метрике: просмотров в каждом посте на порядок больше.
MIN_RISE = {Metric.REACTIONS: 20, Metric.VIEWS: 150}
NAMES = {Metric.REACTIONS: "реакции", Metric.VIEWS: "просмотры"}
# Соседний пост считается синхронным, если подъём у него в пределах часа.
TOLERANCE_HOURS = 1
MIN_SYNCHRONOUS_SIBLINGS = 2
# Прирост подписчиков больше процента за окно — первым объяснением идёт
# внешний толчок, и признак не выставляется.
MAX_SUBSCRIBER_GROWTH = 0.01


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    siblings = context.siblings
    if siblings is None or not siblings.hours.size:
        return ()
    published = prepared.series.published_at.timestamp()
    own = SiblingActivity.from_series((prepared.series,), siblings.hours[0] * HOUR,
                                      siblings.hours[-1] * HOUR + HOUR)
    if own is None:
        return ()
    subject_ages = own.ages[0]
    signs = []
    for metric, own_rows, sibling_rows in ((Metric.REACTIONS, own.reactions, siblings.reactions),
                                           (Metric.VIEWS, own.views, siblings.views)):
        if metric not in prepared.metrics or (metric is Metric.VIEWS and prepared.metrics[metric].source_counter):
            continue
        subject = own_rows[0]
        taken: list[int] = []
        for hour in np.flatnonzero(_rises(subject, MIN_RISE[metric]) & (subject_ages >= MIN_AGE)):
            if any(abs(hour - other) <= TOLERANCE_HOURS for other in taken):
                continue
            synchronous, eligible = 0, 0
            for index in range(sibling_rows.shape[0]):
                window = slice(max(0, hour - TOLERANCE_HOURS), hour + TOLERANCE_HOURS + 1)
                if siblings.ages[index, hour] < MIN_AGE or np.isnan(sibling_rows[index, window]).all():
                    continue
                eligible += 1
                synchronous += bool(_rises(sibling_rows[index], MIN_RISE[metric])[window].any())
            if synchronous < MIN_SYNCHRONOUS_SIBLINGS:
                continue
            start_age = float(own.hours[hour] * HOUR - published)
            growth = context.subscriber_growth(start_age - HOUR, start_age + 2 * HOUR)
            if growth is not None and growth > MAX_SUBSCRIBER_GROWTH:
                continue
            taken.append(int(hour))
            clock = datetime.fromtimestamp(own.hours[hour] * HOUR, tz=timezone.utc)
            strength = min(1.0, 0.4 + 0.15 * synchronous)
            formula = (f"{NAMES[metric]} подросли одновременно у {synchronous + 1} постов аккаунта "
                       f"(+{number(subject[hour])} у этого) в час {clock:%d.%m %H:00} UTC; "
                       f"у {eligible - synchronous} других постов старше 12 ч — нет")
            signs.append(make_sign(PATTERN, FAMILY, prepared, metric, strength, start_age,
                                   start_age + HOUR, SCALE, formula,
                                   {"kind": "synchrony", "posts": synchronous + 1, "quiet": eligible - synchronous,
                                    "hour": clock.isoformat()}, ("account_mentioned_externally",)))
    return tuple(signs)


def _rises(hourly: np.ndarray, minimum: float) -> np.ndarray:
    """Часы, где прирост резко выше медианы предыдущих суток того же поста."""
    result = np.zeros(hourly.size, dtype=bool)
    for hour in np.flatnonzero(np.nan_to_num(hourly, nan=0.0) >= minimum):
        history = hourly[max(0, hour - BASELINE_HOURS):hour]
        history = history[~np.isnan(history)]
        baseline = max(float(np.median(history)), EMPTY_BASELINE) if history.size else EMPTY_BASELINE
        result[hour] = (hourly[hour] - baseline) / np.sqrt(baseline) >= MIN_Z
    return result
