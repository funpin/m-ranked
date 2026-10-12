"""Поток одной реакции: один вид реакции приходит отдельно от остальных.

Telegram отдаёт состав реакций по видам, и у поста есть собственная
контрольная группа — его прочие реакции. Живая аудитория ставит разные
реакции в сходной пропорции всё время: доля каждого вида в новых реакциях
окна близка к его доле вне окна. Заказанная пачка обычно выбирает один вид и
идёт своим темпом. Пермский Политех в Telegram 07.10.2026: прочие реакции
набрали 42 за первый час вместе с просмотрами и встали, а «🙈» шла ровно по
~5 за пять минут ещё два часа и оборвалась — 110 из 122 новых реакций окна
при доле 30 % до него.

Нулевая гипотеза: новые реакции окна — биномиальная выборка с долей вида
вне окна (до и после, со сглаживанием +1/+2). Признак — когда вид набирает в
окне не меньше 30 реакций и 80 % новых, а вероятность такого перекоса при
этой доле ничтожна. Вид, который у поста преобладает всё время (траурный
пост, канал с одной разрешённой реакцией), нулевую гипотезу не нарушает.
Сравнение — по концам окна: форма прироста внутри не утверждается.

На постах Telegram 12.09–08.10.2026 (7 445, копия прода 12.10) выраженный
признак — у 21 поста, слабый — у 5; 17 из 26 уже имели уровень 3 по другим
признакам (КБГУ — пакеты «😍» по 40–50 в первые полчаса, РГСУ — «😁» по 400, МАИ —
«🗿» +1 090 за полночь), уровень поднялся у шести.
"""
from __future__ import annotations

from datetime import timedelta
import math

import numpy as np
from scipy.stats import binom

from ..domain import Family, Metric, Sign
from ..series import HOUR, PreparedSeries
from .base import DetectorContext, age_text, make_sign, number

ID = "reaction_stream"
VERSION = "1.0.0"
PATTERN = 17
FAMILY = Family.COMPOSITION
NEEDS_NORM = False

# Состав читается за первые сутки (store.KINDS_HOURS): пачки приходят тогда.
HORIZON = 24 * HOUR
MIN_STEP = 15 * 60
MAX_SPAN = 6 * HOUR
MIN_STREAM = 30
# У заказанных пачек на выборке доля вида в окне 88–100 %; 71–74 % давали
# посты, где ядро аудитории с первых минут предпочитает «❤» (МФТИ, ЧувГУ).
MIN_SHARE = 0.8
# Доля вида вне окна должна опираться хотя бы на десяток реакций: иначе
# «фон» из одной-двух реакций ничего не говорит о вкусах аудитории.
MIN_OUTSIDE = 10
# Ноль в момент публикации, если первый замер не позже часа (как у эпизода).
ORIGIN_WITHIN = HOUR
# −log₁₀ p → сила: от 8 — слабый сигнал, от 15 — выраженная аномалия.
LEVELS = ((15.0, 0.75), (8.0, 0.55))
# Виды, чьё число не реакция зрителя: платные звёзды и непрочитанные.
SKIPPED_PREFIXES = ("paid:", "unknown:")
SHOWN_SURPRISE_CAP = 99.0
MODE = "reaction_stream_v1"


def detect(prepared: PreparedSeries, context: DetectorContext) -> tuple[Sign, ...]:
    series = prepared.series
    if series.platform != "telegram" or not series.reaction_kinds:
        return ()
    points = _points(prepared)
    if len(points) < 3:
        return ()
    found = best_stream(points)
    if found is None:
        return ()
    surprise = found["surprise"]
    strength = next((value for limit, value in LEVELS if surprise >= limit), 0.0)
    if not strength:
        return ()
    shown = min(surprise, SHOWN_SURPRISE_CAP)
    outside_share = found["outside_key"] / max(found["outside_all"], 1)
    formula = (f"«{found['key']}»: {number(found['key_delta'])} из {number(found['all_delta'])} новых реакций "
               f"({found['key_delta'] / found['all_delta']:.0%}) за t ∈ [{age_text(found['start'])}; "
               f"{age_text(found['end'])}] при доле {outside_share:.0%} вне окна "
               f"(−log₁₀ p {'≥ ' if surprise > SHOWN_SURPRISE_CAP else '= '}{shown:.0f}); "
               f"прочие реакции за то же время +{number(found['all_delta'] - found['key_delta'])}")
    render = {"kind": "stream", "reaction": found["key"], "keyDelta": int(found["key_delta"]),
              "allDelta": int(found["all_delta"]), "outsideShare": round(outside_share, 4),
              "surprise": round(shown, 2), "mode": MODE}
    return (make_sign(PATTERN, FAMILY, prepared, Metric.REACTIONS, strength, found["start"], found["end"],
                      timedelta(seconds=found["end"] - found["start"]), formula, render,
                      ("single_reaction_call", "content_invites_reaction")),)


def _points(prepared: PreparedSeries) -> list[tuple[float, dict[str, int]]]:
    """Замеры с составом в первые сутки, через 15 минут; ноль публикации, если он рядом."""
    series = prepared.series
    published = series.published_at
    rows = []
    for at, kinds in zip(series.observed_at, series.reaction_kinds):
        age = (at - published).total_seconds()
        if kinds is None or at > prepared.analyzed_at or age > HORIZON:
            continue
        rows.append((age, {key: value for key, value in kinds.items() if not key.startswith(SKIPPED_PREFIXES)}))
    if rows and 0 < rows[0][0] <= ORIGIN_WITHIN:
        rows.insert(0, (0.0, {}))
    thinned, last = [], -math.inf
    for index, row in enumerate(rows):
        if row[0] - last >= MIN_STEP or index == len(rows) - 1:
            thinned.append(row)
            last = row[0]
    return thinned


def best_stream(points: list[tuple[float, dict[str, int]]]) -> dict | None:
    keys = sorted({key for _, kinds in points for key in kinds})
    if not keys:
        return None
    ages = np.array([age for age, _ in points])
    counts = np.array([[kinds.get(key, 0) for key in keys] for _, kinds in points], dtype=float)
    totals = counts.sum(axis=1)
    best = None
    # Все окна с началом i сразу: перебор в цикле стоил 2,5 мс на пост.
    for i in range(len(points) - 1):
        stop = int(np.searchsorted(ages, ages[i] + MAX_SPAN, side="right"))
        if stop <= i + 1:
            continue
        delta = counts[i + 1:stop] - counts[i]
        k = delta.argmax(axis=1)
        rows = np.arange(delta.shape[0])
        key_delta = delta[rows, k]
        # Снятые реакции других видов не делают поток сильнее: считается прирост.
        all_delta = np.clip(delta, 0, None).sum(axis=1)
        ends = np.arange(i + 1, stop)
        outside_key = counts[i, k] + counts[-1, k] - counts[ends, k]
        outside_all = totals[i] + totals[-1] - totals[ends]
        ok = ((key_delta >= MIN_STREAM) & (all_delta > 0) & (key_delta >= MIN_SHARE * all_delta)
              & (outside_all >= MIN_OUTSIDE))
        if not ok.any():
            continue
        idx = np.flatnonzero(ok)
        share = (outside_key[idx] + 1) / (outside_all[idx] + 2)
        tail = binom.logsf(key_delta[idx] - 1, all_delta[idx], share)
        surprise = np.where(np.isfinite(tail), -tail / math.log(10), math.inf)
        pick = int(np.argmax(surprise))
        if best is None or surprise[pick] > best["surprise"]:
            row = idx[pick]
            best = {"key": keys[int(k[row])], "start": float(ages[i]), "end": float(ages[ends[row]]),
                    "key_delta": float(key_delta[row]), "all_delta": float(all_delta[row]),
                    "outside_key": float(outside_key[row]), "outside_all": float(outside_all[row]),
                    "surprise": float(surprise[pick])}
    return best
