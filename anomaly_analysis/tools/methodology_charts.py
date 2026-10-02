"""Данные графиков раздела «Методология»: python -m anomaly_analysis.tools.methodology_charts.

Иллюстрации строятся теми же функциями анализатора на эталонных рядах
(`v2/reference.py`), на которых детекторы проверяются тестами, — числа на
графиках и формулы признаков берутся из настоящего вывода детектора, а не
рисуются от руки. Реальные агрегаты (уровни, признаки по площадкам, профиль
позднего отклика) читаются из сохранённых обезличенных файлов `research/`:
в этот файл не попадает ни одного идентификатора аккаунта или поста.

Выход детерминирован: повторный запуск на тех же входах даёт тот же JSON.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..v2.detectors.base import DetectorContext
from ..v2.domain import Metric, PostSeries
from ..v2.levels import assess
from ..v2.mature_reference import bundled_reference
from ..v2.norms import NormSet, build_norms
from ..v2.reference import background, synthetic_reference
from ..v2.schedule import ScheduleConfig
from ..v2.series import DAY, HOUR, CollectionCadence, prepare

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "frontend/content/methodology/analysis-charts.json"
TAIL_EVIDENCE = ROOT / "research/smart-engagement-2026-09/evidence/tail_ratio_2026-09-28.json"
PRODUCTION = ROOT / "research/smart-engagement-2026-09/evidence/production_levels_2026-09-29.json"
CADENCE = CollectionCadence()
V, R = Metric.VIEWS, Metric.REACTIONS


@lru_cache(maxsize=None)
def cases() -> dict[str, Any]:
    return {case.case_id: case for case in synthetic_reference()}


@lru_cache(maxsize=None)
def norms(platform: str) -> NormSet:
    posts = {account: [prepare(item, item.observed_at[-1], CADENCE) for item in items]
             for account, items in background(platform).items()}
    return build_norms(platform, posts, final_age=7 * DAY)


def _verdict(name: str):
    case = cases()[name]
    return case, assess(case.subject, case.siblings, norms=norms(case.subject.platform),
                        subscribers=case.subscribers)


def _sign(name: str, pattern: int):
    case, verdict = _verdict(name)
    sign = next(item for item in verdict.signs if item.pattern == pattern)
    return case, sign, verdict


def _age(series: PostSeries, at) -> float:
    return (at - series.published_at).total_seconds() / HOUR


def _cumulative(series: PostSeries, metric: Metric, hours: np.ndarray) -> np.ndarray:
    """Накопленное значение на часах — линейно между настоящими замерами, как в подготовке ряда."""
    ages = np.array([_age(series, at) for at in series.observed_at])
    values = np.array([np.nan if value is None else value for value in series.values[metric]], dtype=float)
    keep = np.isfinite(values)
    return np.interp(hours, ages[keep], values[keep], left=np.nan, right=np.nan)


def _round(value: float, digits: int = 1) -> float | None:
    return None if value is None or not math.isfinite(value) else round(float(value), digits)


def _sign_payload(sign, verdict) -> dict[str, Any]:
    return {"pattern": sign.pattern, "strength": round(sign.strength, 2), "formula": sign.formula,
            "level": int(verdict.level)}


def decay() -> dict[str, Any]:
    case = cases()["honest_organic_telegram"]
    prepared = prepare(case.subject, case.subject.observed_at[-1], CADENCE)
    fit = DetectorContext("telegram").early_fit(prepared, V)
    hours = np.arange(1, 73)
    actual = np.diff(_cumulative(case.subject, V, np.arange(0, 73)))
    model = fit.expected((hours - 1) * HOUR, hours * HOUR)
    return {"case": case.case_id, "b": round(fit.decay.b, 2), "c": round(fit.decay.c, 2),
            "points": [{"hour": int(hour), "actual": _round(value), "model": _round(expected)}
                       for hour, value, expected in zip(hours, actual, model)]}


def linear_feed() -> dict[str, Any]:
    case, sign, verdict = _sign("p01_linear_feed_vk", 1)
    hours = np.arange(0, 97, 2)
    start, end = sign.render["startAge"] / HOUR, sign.render["endAge"] / HOUR
    slope, intercept = sign.render["slope"], sign.render["intercept"]
    return {"sign": _sign_payload(sign, verdict), "start": round(start, 1), "end": round(end, 1),
            "points": [{"hour": int(hour), "views": _round(value, 0),
                        "fit": _round(intercept + slope * (hour - start), 0) if start <= hour <= end else None}
                       for hour, value in zip(hours, _cumulative(case.subject, V, hours))]}


def late_spike() -> dict[str, Any]:
    """Накопленные просмотры против ожидания собственной модели затухания после первых суток."""
    case, sign, verdict = _sign("p02_late_spike_telegram", 2)
    prepared = prepare(case.subject, case.subject.observed_at[-1], CADENCE)
    fit = DetectorContext("telegram", norms("telegram").for_account(case.subject.account_id)).early_fit(prepared, V)
    hours = np.arange(24, 121)
    actual = _cumulative(case.subject, V, hours)
    base = actual[0]
    expected = base + fit.expected(np.full(hours.size, 24 * HOUR), hours * HOUR)
    spread = math.exp(2 * fit.sigma_model)
    return {"sign": _sign_payload(sign, verdict),
            "points": [{"hour": int(hour), "actual": _round(value, 0), "model": _round(model, 0),
                        "band": [_round(base + (model - base) / spread, 0), _round(base + (model - base) * spread, 0)]}
                       for hour, value, model in zip(hours, actual, expected)]}


def gap_growth() -> dict[str, Any]:
    case, sign, verdict = _sign("p04_gap_growth_telegram", 4)
    series = case.subject
    points = [{"hour": round(_age(series, at), 2), "views": value}
              for at, value in zip(series.observed_at, series.values[V]) if 36 <= _age(series, at) <= 96]
    thin = points[::6] + [point for point in points if 58 <= point["hour"] <= 76]
    thin = sorted({point["hour"]: point for point in thin}.values(), key=lambda point: point["hour"])
    return {"sign": _sign_payload(sign, verdict), "gap": [60, 74],
            "expected": sign.render.get("expected"), "points": thin}


def catch_up() -> dict[str, Any]:
    """Прирост реакций по окнам против доли участка и пуассоновского коридора ±2√λ.

    Независимые живые реакции разбросаны по всему коридору; подгонка реакций под
    просмотры держится у самой линии ожидания — это и измеряет индекс дисперсии.
    """
    case, sign, verdict = _sign("p05_reactions_catch_up_vk", 5)
    edges = np.arange(96, 235, 6)
    views = np.diff(_cumulative(case.subject, V, edges))
    reactions = np.diff(_cumulative(case.subject, R, edges))
    share = reactions.sum() / views.sum()
    points = []
    for start, v, r in zip(edges[:-1], views, reactions):
        expected = share * v
        points.append({"window": f"{int(start // 24)}д{int(start % 24)}ч", "actual": _round(r),
                       "expected": _round(expected),
                       "band": [_round(max(0.0, expected - 2 * math.sqrt(expected))), _round(expected + 2 * math.sqrt(expected))]})
    return {"sign": _sign_payload(sign, verdict), "share": round(float(share), 4), "points": points}


def reactions_before_views() -> dict[str, Any]:
    case, sign, verdict = _sign("p06_reactions_before_views_telegram", 6)
    edges = np.arange(30, 55)
    views = np.diff(_cumulative(case.subject, V, edges))
    reactions = np.diff(_cumulative(case.subject, R, edges))
    return {"sign": _sign_payload(sign, verdict),
            "points": [{"hour": int(hour), "views": _round(100 * v / np.nanmax(views)),
                        "reactions": _round(100 * r / np.nanmax(reactions))}
                       for hour, v, r in zip(edges[1:], views, reactions)]}


def reactions_exceed_views() -> dict[str, Any]:
    case, sign, verdict = _sign("p07_reactions_exceed_views_max", 7)
    hours = np.arange(20, 45, 0.5)
    return {"sign": _sign_payload(sign, verdict),
            "points": [{"hour": float(hour), "views": _round(v, 0), "reactions": _round(r, 0)}
                       for hour, v, r in zip(hours, _cumulative(case.subject, V, hours),
                                             _cumulative(case.subject, R, hours))]}


def synchronous_rise() -> dict[str, Any]:
    case, sign, verdict = _sign("p08_synchronous_rise_telegram", 8)
    event = sign.interval.start
    def increments(series: PostSeries) -> np.ndarray:
        base = _age(series, event)
        edges = base + np.arange(-6, 8)
        return np.nan_to_num(np.diff(_cumulative(series, R, edges)))
    together = sum(increments(item) for item in case.siblings[:4])
    quiet = sum(increments(item) for item in case.siblings[4:])
    own = increments(case.subject)
    return {"sign": _sign_payload(sign, verdict),
            "points": [{"hour": int(offset), "own": _round(a, 0), "together": _round(b, 0), "quiet": _round(c, 0)}
                       for offset, a, b, c in zip(range(-5, 8), own, together, quiet)]}


def burst_plateau() -> dict[str, Any]:
    case, sign, verdict = _sign("p09_burst_plateau_telegram", 9)
    edges = np.arange(40, 73)
    views = np.diff(_cumulative(case.subject, V, edges))
    return {"sign": _sign_payload(sign, verdict), "peak": _round(np.nanmax(views), 0),
            "points": [{"hour": int(hour), "views": _round(value, 0)} for hour, value in zip(edges[1:], views)]}


def erv() -> dict[str, Any]:
    case, sign, verdict = _sign("p10_high_erv_vk", 10)
    return {"sign": _sign_payload(sign, verdict), "post": sign.render.get("erv"),
            "median": sign.render.get("median"), "low": sign.render.get("low"), "high": sign.render.get("high")}


def late_engagement() -> dict[str, Any]:
    case, sign, verdict = _sign("p13_late_engagement_max", 13)
    hours = np.arange(0, 13 * 24 + 1, 6)
    return {"sign": _sign_payload(sign, verdict), "earlyRate": sign.render["earlyRate"],
            "lateRate": sign.render["lateRate"], "ratio": sign.render["ratio"],
            "points": [{"hour": int(hour), "views": _round(v, 0), "reactions": _round(r, 0)}
                       for hour, v, r in zip(hours, _cumulative(case.subject, V, hours),
                                             _cumulative(case.subject, R, hours))]}


def mature_reference() -> dict[str, Any]:
    """Ожидание и граница действующего ориентира для условного поста типичного аккаунта."""
    bundle = bundled_reference()
    reference = bundle.references[-1]
    account = sorted(reference.account_counts, key=lambda item: reference.components[0].effects[item])[
        len(reference.account_counts) // 2]
    early = {V: 1500, R: 40}
    rows = []
    for component in reference.components:
        prediction = component.prediction(account, early[component.metric])
        rows.append({"metric": component.metric.value, "conditional": component.conditional,
                     "expected": round(math.expm1(prediction)),
                     "upper": math.floor(math.expm1(prediction + reference.cutoff * component.scale))})
    return {"version": reference.version, "fit": reference.fit_count, "calibration": reference.calibration_count,
            "accounts": len(reference.account_counts), "cutoff": round(reference.cutoff, 3),
            "early": {"views": early[V], "reactions": early[R]}, "rows": rows,
            "scopes": [{"version": item.version, "from": item.available_at.date().isoformat(),
                        "until": item.expires_at.date().isoformat()} for item in bundle.references]}


def schedule() -> dict[str, Any]:
    config = ScheduleConfig()
    ages = [0, 1, 2, 3, 4, 5, 6, 7, 10, 14, 20, 30]
    rows = []
    for day in ages:
        age = day * DAY + 1
        rows.append({"day": day,
                     "collect": round(float(CADENCE.expected_step_seconds("telegram", np.array([age]))[0]) / 60, 1),
                     "collectRutube": round(float(CADENCE.expected_step_seconds("rutube", np.array([age]))[0]) / 60, 1),
                     "analyze": round(_interval(config, "telegram", age) / 60, 1),
                     "analyzeRutube": round(_interval(config, "rutube", age) / 60, 1)})
    return {"points": rows}


def _interval(config: ScheduleConfig, platform: str, age: float) -> float:
    from ..v2.schedule import interval
    return interval(config, platform, age)


def build() -> dict[str, Any]:
    tail = json.loads(TAIL_EVIDENCE.read_text(encoding="utf-8"))
    production = json.loads(PRODUCTION.read_text(encoding="utf-8"))
    return {
        "note": "Иллюстрации — эталонные ряды v2/reference.py и вывод настоящих детекторов; "
                "реальные агрегаты — обезличенные файлы research/smart-engagement-2026-09/evidence.",
        "decay": decay(), "linearFeed": linear_feed(), "lateSpike": late_spike(), "gapGrowth": gap_growth(),
        "catchUp": catch_up(), "reactionsBeforeViews": reactions_before_views(),
        "reactionsExceedViews": reactions_exceed_views(), "synchronousRise": synchronous_rise(),
        "burstPlateau": burst_plateau(), "erv": erv(), "lateEngagement": late_engagement(),
        "matureReference": mature_reference(), "schedule": schedule(),
        "tail": {"computedFor": tail["computedFor"], "posts": tail["posts"],
                 "platforms": {name: {key: value[key] for key in ("accounts", "statuses", "cohort", "postsWithLedger",
                                                                     "pattern13Posts", "pattern13Accounts", "histogram")
                                      if key in value}
                               for name, value in tail["platforms"].items()},
                 "sensitivity": tail["sensitivity"]},
        "production": production,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    arguments.output.write_text(json.dumps(build(), ensure_ascii=False, separators=(",", ":")) + "\n",
                                encoding="utf-8")


if __name__ == "__main__":
    main()
