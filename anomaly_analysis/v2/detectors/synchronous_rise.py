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
VERSION = "2.4.0"
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
# Молодой пост внутри волны. Сравнивать его с собственным хвостом нельзя —
# хвоста ещё нет, а после волны у поста MAX набирается сотня просмотров за
# сутки, и обрыв реакций на ней недоказуем. Московский Политех в MAX,
# 06.10 17:00 – 07.10 14:00: реакции разом получали 18–29 постов возрастом до
# девяти суток, а посты, опубликованные в эти часы, признака не получали
# вовсе (уровни 0–1 при 100–120 реакциях на ~1 000 просмотров против
# обычных 10–25). Волну подтверждают старые посты, как и прежде; молодой
# пост — её участник, если его доля реакций на новый просмотр в окне хотя
# бы вчетверо выше доли других постов аккаунта в их первые сутки до волны.
# Молодой пост сравнивается с молодыми: у старых постов доля в хвосте в
# разы ниже, чем в первые часы (ADR-015), и сравнение с ними объявило бы
# участником любой свежий пост. Часы ближе полусуток к окну в базу не
# входят: волна идёт и до найденного окна.
YOUNG_MIN_RATIO = 4.0
YOUNG_MIN_REACTIONS = 15
YOUNG_BASE_AGE = 24 * HOUR
YOUNG_BASE_GAP_HOURS = 12
YOUNG_BASE_MIN_VIEWS = 300
# Доказательство участника слабее собственного подъёма старого поста: сила
# не выше выраженной аномалии, уровень 3 — только вместе с другим семейством.
YOUNG_MAX_STRENGTH = 0.75


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
        if end - last_end < WAVE_HOURS:
            continue
        young = own.ages[0, start] < MIN_AGE
        # Граница переноса сравнивается с началом самого признака: у молодого
        # поста оно не раньше публикации. Иначе в часы между началом окна и
        # публикацией признак не искался бы и не переносился (перенос — по
        # началу признака, worker._carried).
        begins = max(own.hours[start] * HOUR, published) if young else own.hours[start] * HOUR
        if context.synchrony_from is not None and begins < context.synchrony_from:
            continue
        # Резкий подъём в том же окне уже описан почасовым режимом.
        if any(start - 1 <= hour <= end + 1 for hour in taken):
            continue
        if young:
            # Участник волны: пост существовал в окне и набрал в нём реакции.
            known = ~np.isnan(subject[start:end + 1])
            if known.sum() < WAVE_MIN_KNOWN_HOURS \
                    or np.nansum(subject[start:end + 1]) < YOUNG_MIN_REACTIONS:
                continue
        elif not _waving(subject, end, WAVE_MIN_SUBJECT_HISTORY_HOURS):
            continue
        waving = [index for index in range(sibling_rows.shape[0])
                  if siblings.ages[index, start] >= MIN_AGE and _waving(sibling_rows[index], end)]
        if len(waving) < WAVE_MIN_SIBLINGS:
            continue
        inside = np.zeros(subject.size, dtype=bool)
        inside[start:end + 1] = True
        # Волну доказывают старые посты; молодой пост в её долях не участвует.
        rows = sibling_rows[waving] if young else np.vstack([subject, sibling_rows[waving]])
        views = siblings.views[waving] if young else np.vstack([own_views, siblings.views[waving]])
        wave_reactions, wave_views = np.nansum(rows[:, inside]), np.nansum(views[:, inside])
        usual_reactions, usual_views = np.nansum(rows[:, ~inside]), np.nansum(views[:, ~inside])
        usual = usual_reactions / usual_views if usual_views > 0 else None
        wave = wave_reactions / wave_views if wave_views > 0 else np.inf
        if usual is None or usual <= 0 or wave < WAVE_MIN_ENGAGEMENT_RATIO * usual:
            continue
        if young:
            own_reactions, own_seen = np.nansum(subject[inside]), np.nansum(own_views[inside])
            share = own_reactions / own_seen if own_seen > 0 else np.inf
            base = _young_share(siblings, start - YOUNG_BASE_GAP_HOURS)
            if base is None or base <= 0 or share < YOUNG_MIN_RATIO * base:
                continue
        start_age = float(own.hours[start] * HOUR - published)
        end_age = float(own.hours[end] * HOUR + HOUR - published)
        growth = context.subscriber_growth(start_age - HOUR, end_age)
        if growth is not None and growth > MAX_SUBSCRIBER_GROWTH:
            continue
        last_end = end
        first = datetime.fromtimestamp(own.hours[start] * HOUR, tz=timezone.utc)
        last = datetime.fromtimestamp(own.hours[end] * HOUR + HOUR, tz=timezone.utc)
        times = "∞" if not np.isfinite(wave) else f"{number(wave / usual)}"
        render = {"kind": "synchrony_wave", "posts": len(waving) + 1, "hour": first.isoformat(), "hours": WAVE_HOURS}
        if young:
            # Начало окна для молодого поста — не раньше публикации.
            start_age = max(start_age, 0.0)
            ratio = "∞" if not np.isfinite(share) else number(share / base)
            formula = (f"реакции росли одновременно у {len(waving)} старых постов аккаунта "
                       f"{first:%d.%m %H:00}–{last:%H:00} UTC (реакций на новый просмотр в {times} раза больше "
                       f"обычного); этот пост опубликован рядом с волной и в те же часы получил "
                       f"+{number(own_reactions)} реакций на +{number(own_seen)} просмотров — в {ratio} раза "
                       f"больше, чем свежие посты аккаунта до волны")
            strength = min(YOUNG_MAX_STRENGTH, 0.4 + 0.05 * len(waving))
            render["member"] = "young"
        else:
            rise, expected = _wave_rise(subject, end, WAVE_MIN_SUBJECT_HISTORY_HOURS)  # type: ignore[misc]
            formula = (f"реакции росли одновременно у {len(waving) + 1} постов аккаунта "
                       f"{first:%d.%m %H:00}–{last:%H:00} UTC (+{number(rise)} у этого за {WAVE_HOURS} ч "
                       f"при обычных ~{number(expected)}); реакций на новый просмотр в {times} раза больше обычного")
            strength = min(1.0, 0.4 + 0.05 * len(waving))
        signs.append(make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, start_age, end_age,
                               timedelta(hours=WAVE_HOURS), formula, render, ("account_mentioned_externally",)))
    return signs


def _young_share(siblings: SiblingActivity, before: int) -> float | None:
    """Доля реакций на новый просмотр у постов аккаунта в их первые сутки, в часах до `before`."""
    if before <= 0:
        return None
    ages = siblings.ages[:, :before]
    reactions, views = siblings.reactions[:, :before], siblings.views[:, :before]
    mask = (ages >= 0) & (ages < YOUNG_BASE_AGE) & ~np.isnan(reactions) & ~np.isnan(views)
    seen = float(views[mask].sum())
    return float(reactions[mask].sum()) / seen if seen >= YOUNG_BASE_MIN_VIEWS else None


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
