"""Синхронные подъёмы на нескольких старых постах аккаунта (по образцу CopyCatch).

Старый пост живёт хвостом; когда в один и тот же час реакции подскакивают у
него и ещё у нескольких старых постов аккаунта, а подписчики не прибывают,
общий внешний толчок (упоминание в новостях) объясняет это хуже, чем
одновременная доставка.

Второй режим — медленная волна: реакции не скачут за час, а несколько часов
подряд ровно капают сразу на многих старых постах (Московский Политех в MAX
06.10: 28 постов возрастом до девяти суток по 2–4 реакции в час десять часов,
реакций к просмотрам 26 % при обычных 1–2 %). Каждый час ниже порога подъёма,
доказательство несут сумма за окно, число постов и реакции сверх просмотров.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from ..domain import Family, Metric, Sign
from ..series import DAY, HOUR, PreparedSeries
from .base import DetectorContext, SiblingActivity, make_sign, number

ID = "synchronous_rise"
VERSION = "2.3.0"
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
# Медленная волна: прирост за окно WAVE_HOURS против собственного хвоста поста
# за сутки до окна — тот же пуассоновский z, но по сумме, а не по часу. Хвост
# должен быть известен (полусутки замеров), иначе у края окна агрегатов пустая
# база снова превратила бы ровный темп в волну.
WAVE_HOURS = 6
WAVE_MIN_RISE = 8
WAVE_MIN_SIBLINGS = 6
WAVE_MIN_KNOWN_HOURS = 3
WAVE_MIN_HISTORY_HOURS = 12
# Волну подтверждают соседи с полусуточной историей; сам пост, если волна по
# аккаунту уже подтверждена, может иметь и короче — у MAX пробелы сбора часто
# оставляют за сутки шесть-десять покрытых часов (Политех 06.10: из 28 постов
# волны полную историю имели восемь).
WAVE_MIN_SUBJECT_HISTORY_HOURS = 6
# В волне реакции опережают просмотры: доля реакций на новый просмотр у постов
# волны хотя бы втрое выше доли тех же постов вне окна. Внешний толчок
# (упоминание, рассылка) приводит людей, и просмотры растут вместе с реакциями.
WAVE_MIN_ENGAGEMENT_RATIO = 3.0
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
        signs.extend(_waves(prepared, context, own, subject, sibling_rows, taken))
    return tuple(signs)


def _wave_rise(hourly: np.ndarray, end: int,
               min_history: int = WAVE_MIN_HISTORY_HOURS) -> tuple[float, float] | None:
    """Прирост за окно, кончающееся часом `end`, и ожидание по хвосту поста.

    None — окно или сутки до него почти не покрыты замерами: судить не о чем."""
    start = end - WAVE_HOURS + 1
    if start < min_history:
        return None
    window = hourly[start:end + 1]
    known = window[~np.isnan(window)]
    history = hourly[max(0, start - BASELINE_HOURS):start]
    history = history[~np.isnan(history)]
    if known.size < WAVE_MIN_KNOWN_HOURS or history.size < min_history:
        return None
    baseline = max(float(np.median(history)), EMPTY_BASELINE)
    return float(known.sum()), baseline * known.size


def _waving(hourly: np.ndarray, end: int, min_history: int = WAVE_MIN_HISTORY_HOURS) -> bool:
    measured = _wave_rise(hourly, end, min_history)
    if measured is None:
        return False
    rise, expected = measured
    return rise >= WAVE_MIN_RISE and (rise - expected) / np.sqrt(expected) >= MIN_Z


def _waves(prepared: PreparedSeries, context: DetectorContext, own, subject: np.ndarray,
           sibling_rows: np.ndarray, taken: list[int]) -> list[Sign]:
    """Медленная синхронная волна: окна, где реакции росли сразу у многих постов."""
    siblings = context.siblings
    published = prepared.series.published_at.timestamp()
    own_views = own.views[0]
    signs: list[Sign] = []
    last_end = -WAVE_HOURS
    for end in range(WAVE_HOURS - 1, subject.size):
        start = end - WAVE_HOURS + 1
        if end - last_end < WAVE_HOURS or own.ages[0, start] < MIN_AGE:
            continue
        if context.synchrony_from is not None and own.hours[start] * HOUR < context.synchrony_from:
            continue
        # Резкий подъём в том же окне уже описан почасовым режимом.
        if any(start - 1 <= hour <= end + 1 for hour in taken) \
                or not _waving(subject, end, WAVE_MIN_SUBJECT_HISTORY_HOURS):
            continue
        waving = [index for index in range(sibling_rows.shape[0])
                  if siblings.ages[index, start] >= MIN_AGE and _waving(sibling_rows[index], end)]
        if len(waving) < WAVE_MIN_SIBLINGS:
            continue
        rows = np.vstack([subject, sibling_rows[waving]])
        views = np.vstack([own_views, siblings.views[waving]])
        inside = np.zeros(subject.size, dtype=bool)
        inside[start:end + 1] = True
        wave_reactions, wave_views = np.nansum(rows[:, inside]), np.nansum(views[:, inside])
        usual_reactions, usual_views = np.nansum(rows[:, ~inside]), np.nansum(views[:, ~inside])
        usual = usual_reactions / usual_views if usual_views > 0 else None
        wave = wave_reactions / wave_views if wave_views > 0 else np.inf
        if usual is None or usual <= 0 or wave < WAVE_MIN_ENGAGEMENT_RATIO * usual:
            continue
        start_age = float(own.hours[start] * HOUR - published)
        end_age = float(own.hours[end] * HOUR + HOUR - published)
        growth = context.subscriber_growth(start_age - HOUR, end_age)
        if growth is not None and growth > MAX_SUBSCRIBER_GROWTH:
            continue
        last_end = end
        rise, expected = _wave_rise(subject, end, WAVE_MIN_SUBJECT_HISTORY_HOURS)  # type: ignore[misc]
        first = datetime.fromtimestamp(own.hours[start] * HOUR, tz=timezone.utc)
        last = datetime.fromtimestamp(own.hours[end] * HOUR + HOUR, tz=timezone.utc)
        times = "∞" if not np.isfinite(wave) else f"{number(wave / usual)}"
        formula = (f"реакции росли одновременно у {len(waving) + 1} постов аккаунта "
                   f"{first:%d.%m %H:00}–{last:%H:00} UTC (+{number(rise)} у этого за {WAVE_HOURS} ч "
                   f"при обычных ~{number(expected)}); реакций на новый просмотр в {times} раза больше обычного")
        strength = min(1.0, 0.4 + 0.05 * len(waving))
        signs.append(make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age,
                               timedelta(hours=WAVE_HOURS), formula,
                               {"kind": "synchrony_wave", "posts": len(waving) + 1, "hour": first.isoformat(),
                                "hours": WAVE_HOURS}, ("account_mentioned_externally",)))
    return signs


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
