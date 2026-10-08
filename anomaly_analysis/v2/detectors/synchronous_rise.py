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
VERSION = "2.2.2"
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
MIN_RISE = 20
# Соседний пост считается синхронным, если подъём у него в пределах часа.
TOLERANCE_HOURS = 1
MIN_SYNCHRONOUS_SIBLINGS = 2
# Широкий одновременный вброс: когда реакции в одном часу подросли сразу у
# многих постов аккаунта, порог каждого поста ниже. Совпадение у пяти и более
# постов старше 12 ч само по себе маловероятно, и доказательство несёт число
# постов, а не размер прироста одного. Так пропускались вбросы на маленьких
# аккаунтах: КГУ в MAX 24.09 — около двадцати постов разом, у постов от 21.09
# по +14…+19 при пороге 20.
WIDE_MIN_RISE = 10
WIDE_MIN_SIBLINGS = 4
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
    # Только реакции. Одновременный подъём просмотров старых постов органичен:
    # новый пост приводит людей в канал или на стену, и просмотры листаемых
    # старых постов растут разом. Проверка по просмотрам дала 834 поста с
    # признаком на тридцати пяти сутках — почти все такие.
    for metric, own_rows, sibling_rows in ((Metric.REACTIONS, own.reactions, siblings.reactions),):
        if metric not in prepared.metrics:
            continue
        subject = own_rows[0]
        taken: list[int] = []
        strong = _rises(subject, MIN_RISE)
        candidates = _rises(subject, WIDE_MIN_RISE) & (subject_ages >= MIN_AGE)
        if context.synchrony_from is not None:
            # До границы суточная база обрезана началом окна (у самого края —
            # пуста), и ровный темп выглядит подъёмом у всех постов разом.
            # Признаки отсюда уже найдены прежними анализами и переносятся.
            candidates &= own.hours * HOUR >= context.synchrony_from
        for hour in np.flatnonzero(candidates):
            # Подъём пары часов отмечается на втором часе, поэтому то же событие
            # может всплыть на час позже допуска.
            if any(abs(hour - other) <= TOLERANCE_HOURS + 1 for other in taken):
                continue
            synchronous, wide, eligible = 0, 0, 0
            window = slice(max(0, hour - TOLERANCE_HOURS), hour + TOLERANCE_HOURS + 1)
            for index in range(sibling_rows.shape[0]):
                if siblings.ages[index, hour] < MIN_AGE or np.isnan(sibling_rows[index, window]).all():
                    continue
                eligible += 1
                synchronous += bool(_rises(sibling_rows[index], MIN_RISE)[window].any())
                wide += bool(_rises(sibling_rows[index], WIDE_MIN_RISE)[window].any())
            if not (strong[hour] and synchronous >= MIN_SYNCHRONOUS_SIBLINGS):
                if wide < WIDE_MIN_SIBLINGS:
                    continue
                synchronous = wide
            start_age = float(own.hours[hour] * HOUR - published)
            growth = context.subscriber_growth(start_age - HOUR, start_age + 2 * HOUR)
            if growth is not None and growth > MAX_SUBSCRIBER_GROWTH:
                continue
            taken.append(int(hour))
            step_start, step_end = _step(prepared, metric, start_age)
            clock = datetime.fromtimestamp(own.hours[hour] * HOUR, tz=timezone.utc)
            strength = min(1.0, 0.4 + 0.15 * synchronous)
            # Подъём мог быть найден в паре «предыдущий час + этот» (рывок на
            # границе часа): прирост называется за ту же пару, а не «+0».
            single = float(np.nan_to_num(subject[hour]))
            rise = single if _rises_in(subject, WIDE_MIN_RISE)[hour] or hour == 0 \
                else single + float(np.nan_to_num(subject[hour - 1]))
            formula = (f"реакции подросли одновременно у {synchronous + 1} постов аккаунта "
                       f"(+{number(rise)} у этого) в час {clock:%d.%m %H:00} UTC; "
                       f"у {eligible - synchronous} других постов старше 12 ч — нет")
            signs.append(make_sign(PATTERN, FAMILY, prepared, metric, strength, step_start,
                                   step_end, SCALE, formula,
                                   {"kind": "synchrony", "posts": synchronous + 1, "quiet": eligible - synchronous,
                                    "hour": clock.isoformat()}, ("account_mentioned_externally",)))
    return tuple(signs)


def _step(prepared: PreparedSeries, metric: Metric, start_age: float) -> tuple[float, float]:
    """Промежуток между замерами с наибольшим приростом в часе подъёма и часе до него.

    Признак привязан к самому скачку, а не к часу: при редких замерах час почти
    целиком лежит в пропуске, и признак отбрасывался как неразборный, хотя скачок
    (КГУ в MAX 24.09: 06:56 → 07:01, +28) пойман соседними замерами. Если же
    прирост накоплен за пропуск, промежуток и есть пропуск, и признак
    отбрасывается по-прежнему.
    """
    series = prepared.series
    published = series.published_at
    best, result = 0.0, (start_age, start_age + HOUR)
    previous: tuple[float, float] | None = None
    for moment, value in zip(series.observed_at, series.values.get(metric, ()), strict=False):
        if value is None:
            continue
        age = (moment - published).total_seconds()
        if previous is not None and age > start_age - HOUR and previous[0] < start_age + HOUR \
                and value - previous[1] > best:
            best, result = value - previous[1], (previous[0], age)
        previous = (age, float(value))
    return result


def _rises(hourly: np.ndarray, minimum: float) -> np.ndarray:
    """Часы, где прирост резко выше медианы предыдущих суток того же поста.

    Почасовой ряд строится по замерам, и рывок за пять минут на границе часа
    делится между двумя часами (КГУ в MAX 24.09: +14 стали 11,6 и 4,2). Поэтому
    подъём ищется и в часе, и в паре «предыдущий + этот» с базой тоже по парам.
    """
    single = _rises_in(hourly, minimum)
    pairs = np.full(hourly.size, np.nan)
    pairs[1:] = hourly[1:] + hourly[:-1]
    return single | _rises_in(pairs, minimum, scale=2)


def _rises_in(hourly: np.ndarray, minimum: float, scale: int = 1) -> np.ndarray:
    result = np.zeros(hourly.size, dtype=bool)
    for hour in np.flatnonzero(np.nan_to_num(hourly, nan=0.0) >= minimum):
        history = hourly[max(0, hour - BASELINE_HOURS):hour]
        history = history[~np.isnan(history)]
        baseline = (max(float(np.median(history)), EMPTY_BASELINE * scale) if history.size
                    else EMPTY_BASELINE * scale)
        result[hour] = (hourly[hour] - baseline) / np.sqrt(baseline) >= MIN_Z
    return result
