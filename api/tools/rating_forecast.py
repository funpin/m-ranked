"""Ночной снимок прогноза М-Рейтинга по соцсетям.

Каждую ночь считает текущий месяц (бегущая оценка) и прошлый, если
официального за него ещё нет (итоговый прогноз), и помечает итоговыми снимки
месяцев, которые источник уже опубликовал. Ретроспектива (--retrospective)
считается разово при выкатке: по месяцу, со статусом retrospective.

Агрегаты читает пул чтения; баллы базового месяца и запись снимка — через
функции миграции 0084 под api_write_admin. Задание фоновое (CPUWeight=10):
агрегация месяца по 75 вузам на копии прода — меньше секунды.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .. import rating_forecast as rf
from ..config import Settings
from ..db import Database
from ..institution_profile import _students_by_institution
from ..sql import rating as sql

logger = logging.getLogger("rating-forecast")


def parse_retrospective(value: str) -> list[date]:
    first, _, last = value.partition("..")
    start, end = (date.fromisoformat(f"{item}-01") for item in (first, last or first))
    if end < start:
        raise ValueError("retrospective range is reversed")
    months, current = [], start
    while current <= end:
        months.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return months


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


async def _published(database: Any) -> dict[date, str]:
    published: dict[date, str] = {}
    for row in await database.admin_fetch_all("SELECT period FROM rating.official_periods()"):
        try:
            published[rf.period_month(row["period"])] = row["period"]
        except ValueError:
            logger.warning("неизвестный период официального рейтинга: %r", row["period"])
    return published


async def _base(database: Any, period: str) -> rf.BaseMonth:
    rows = await database.admin_fetch_all(
        "SELECT code,name,social_score,max_score,vk_score,rutube_score,consolidated_score"
        " FROM rating.official_period_scores(%(period)s)", {"period": period})
    return rf.BaseMonth(period=period, names={row["code"]: row["name"] for row in rows}, scores={
        row["code"]: {"social": _number(row["social_score"]), "max": _number(row["max_score"]),
                      "vk": _number(row["vk_score"]), "rutube": _number(row["rutube_score"]),
                      "consolidated": _number(row["consolidated_score"])} for row in rows})


async def _institutions(database: Any, month: date, as_of: datetime) -> list[rf.InstitutionMonth]:
    start, end = rf.month_window(month)
    rows = await database.fetch_all(sql.PLATFORM_MONTH, {
        "window_start": start, "window_end": min(end, as_of),
        "mature_before": as_of - timedelta(days=rf.FORMULA_V1["matureAfterDays"])})
    students = _students_by_institution()
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"platforms": {}})
    for row in rows:
        entry = grouped[row["institution_id"]]
        entry.update(code=row["code"], name=row["name"])
        if row["platform"] is None:
            continue
        # Зрелые посты — если они есть; иначе все (начало месяца).
        mature = row["mature_posts"] > 0
        entry["platforms"][row["platform"]] = rf.PlatformMonth(
            posts=row["posts"],
            viewed_posts=row["mature_posts"] if mature else row["viewed_posts"],
            views=int(row["mature_views"] if mature else row["views"]),
            interactions=int(row["mature_interactions"] if mature else row["interactions"]),
            covered=bool(row["covered"]))
    return [rf.InstitutionMonth(institution_id=key, code=value["code"], name=value["name"],
                                students=(students.get(key) or {}).get("value"), platforms=value["platforms"])
            for key, value in sorted(grouped.items(), key=lambda item: item[1]["code"])]


async def _errors(database: Any, month: date, published: dict[date, str]) -> dict[str, float]:
    """Типичные ошибки — по последнему опубликованному месяцу, где есть снимок."""
    defaults = dict(rf.FORMULA_V1["defaultErrors"])
    for candidate in sorted((item for item in published if item < month), reverse=True)[:3]:
        rows = await database.fetch_all(sql.PUBLISHED_SNAPSHOT_SCORES, {
            "formula_key": rf.FORMULA_KEY, "window_start": rf.month_window(candidate)[0],
            "period": published[candidate]})
        if not rows:
            continue
        predicted: dict[str, dict[str, float]] = defaultdict(dict)
        actual: dict[str, dict[str, float | None]] = defaultdict(dict)
        for row in rows:
            if row["predicted"] is not None:
                predicted[row["institution_id"]][row["category"]] = row["predicted"]
            actual[row["institution_id"]][row["category"]] = row["actual"]
        return rf.typical_errors(predicted, actual, defaults)
    return defaults


async def _forecast_month(database: Any, month: date, status: str, as_of: datetime,
                          published: dict[date, str]) -> dict | None:
    base_month = rf.base_month_for(month, published)
    if base_month is None:
        logger.warning("нет опубликованного базового месяца для %s — пропуск", month.isoformat())
        return None
    base = await _base(database, published[base_month])
    # Месяц перед базовым — чтобы узнать нули источника два месяца подряд.
    prior_month = rf.base_month_for(base_month, published)
    prior = await _base(database, published[prior_month]) if prior_month else None
    if prior is not None:
        base = rf.BaseMonth(period=base.period, scores=base.scores, names=base.names, prior=prior.scores)
    if not base.scores:
        logger.warning("базовый месяц %s пуст — пропуск", base.period)
        return None
    scale, early = (1.0, False) if status == "retrospective" else rf.running_scale(month, as_of)
    institutions = await _institutions(database, month, as_of)
    errors = await _errors(database, month, published)
    results = rf.forecast(institutions, base, errors, scale=scale)
    start, end = rf.month_window(month)
    window_end = min(end, as_of)
    parameters = {"status": status, "basePeriod": base.period, "period": rf.period_label(month),
                  "priorPeriod": prior.period if prior is not None else None,
                  "errors": errors, "postsScale": round(scale, 4), "early": early,
                  "formulaVersion": rf.FORMULA_V1["version"]}
    digest = hashlib.sha256(json.dumps({"month": month.isoformat(), "parameters": parameters,
                                        "results": results}, sort_keys=True, default=str).encode()).hexdigest()
    body = {"formulaKey": rf.FORMULA_KEY, "version": rf.FORMULA_V1["version"],
            "windowStart": start.astimezone(timezone.utc).isoformat(),
            "windowEnd": window_end.astimezone(timezone.utc).isoformat(),
            "asOf": as_of.astimezone(timezone.utc).isoformat(),
            "startedAt": as_of.astimezone(timezone.utc).isoformat(),
            "inputHash": digest, "parameters": parameters, "results": results}
    row = await database.admin_fetch_one("SELECT ops_and_admin.record_rating_forecast(%(payload)s::jsonb) AS result",
                                         {"payload": json.dumps(body, ensure_ascii=False)})
    logger.info("снимок %s (%s): %d вузов, заменено %s", month.isoformat(), status, len(results),
                row["result"]["replaced"])
    return row["result"]


async def run(database: Any, as_of: datetime, *, retrospective: list[date] | None = None) -> list[dict]:
    published = await _published(database)
    targets = ([(month, "retrospective") for month in retrospective] if retrospective
               else rf.months_to_forecast(as_of, published))
    recorded = []
    for month, status in targets:
        result = await _forecast_month(database, month, status, as_of, published)
        if result is not None:
            recorded.append(result)
    if not retrospective:
        for month in sorted(published)[-2:]:
            await database.admin_fetch_one(
                "SELECT ops_and_admin.finalize_rating_forecast(%(formula_key)s, %(window_start)s) AS result",
                {"formula_key": rf.FORMULA_KEY, "window_start": rf.month_window(month)[0]})
    return recorded


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="rating_forecast")
    parser.add_argument("--retrospective", type=parse_retrospective, default=None)
    arguments = parser.parse_args(argv)
    database = Database(Settings())
    await database.open()
    try:
        await run(database, datetime.now(timezone.utc), retrospective=arguments.retrospective)
        return 0
    except Exception as error:
        logger.error("прогноз М-Рейтинга не посчитан: %s", type(error).__name__)
        return 1
    finally:
        await database.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(_main(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
