"""Снимки «Нашего рейтинга» — шаг ночного задания прогноза М-Рейтинга.

Отдельного таймера нет (решение владельца 20.11.2026): рейтинг считается тем же
прогоном, что прогноз (`api.tools.rating_forecast`, 01:47), и той же кнопкой
загрузки М-Рейтинга. Каждую ночь — бегущий текущий месяц; до 7-го числа
включительно — ещё и итог прошлого месяца (просмотры последних постов
докапливаются); с 8-го прошлый месяц закрывается: остаётся последний снимок.
Месяцы раньше formula.firstMonth не считаются (решение владельца: с ноября 2026).

Агрегат читает пул чтения, запись — ops_and_admin.record_rating_forecast под
api_write_admin, как у прогноза. Сбой снимка не мешает прогнозу.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .. import own_rating as own, rating_forecast as rf
from ..institution_profile import _students_by_institution
from ..sql import own_rating as sql

logger = logging.getLogger("rating-forecast")


def first_month(formula: dict[str, Any] = own.FORMULA_CURRENT) -> date:
    return date.fromisoformat(f"{formula['firstMonth']}-01")


def months_to_rate(as_of: datetime, formula: dict[str, Any] = own.FORMULA_CURRENT) -> tuple[list[tuple[date, str]], date | None]:
    """Месяцы снимка и месяц, который пора закрыть."""
    today = as_of.astimezone(rf.MOSCOW).date()
    current = today.replace(day=1)
    previous = (current - timedelta(days=1)).replace(day=1)
    targets: list[tuple[date, str]] = []
    close: date | None = None
    if previous >= first_month(formula):
        if today.day <= formula["closeAfterDay"]:
            targets.append((previous, "final"))
        else:
            close = previous
    if current >= first_month(formula):
        targets.append((current, "running"))
    return targets, close


def account_month(row: dict[str, Any], formula: dict[str, Any] = own.FORMULA_CURRENT) -> own.AccountMonth:
    # Зрелые посты — если они есть; иначе все (первые дни месяца), как в прогнозе.
    mature = row["mature_posts"] > 0
    rule = formula["lateExcess"]
    profiles = row["profiles"] or 0
    late = (row["late_share"] if row["late_share"] is not None and profiles >= rule["minProfiles"]
            and row["confident"] >= rule["majority"] * profiles else None)
    prefix = "mature_" if mature else ""
    return own.AccountMonth(
        platform=row["platform"], covered_days=float(row["covered_days"]), posts=int(row["posts"]),
        active_days=int(row["active_days"]),
        viewed_posts=int(row["mature_posts"] if mature else row["viewed_posts"]),
        views=int(row[f"{prefix}views"]), interactions=int(row[f"{prefix}interactions"]),
        pack_views=int(row[f"{prefix}pack_views"]), pack_reactions=int(row[f"{prefix}pack_reactions"]),
        late_share=float(late) if late is not None else None,
        evenness=row["evenness"], median_reactions=row["median_reactions"], residuals=int(row["residuals"] or 0))


def institutions(names: list[dict[str, Any]], rows: list[dict[str, Any]],
                 formula: dict[str, Any] = own.FORMULA_CURRENT) -> list[own.InstitutionMonth]:
    students = _students_by_institution()
    accounts: dict[str, list[own.AccountMonth]] = {}
    for row in rows:
        accounts.setdefault(row["institution_id"], []).append(account_month(row, formula))
    return [own.InstitutionMonth(institution_id=item["institution_id"], name=item["name"],
                                 students=(students.get(item["institution_id"]) or {}).get("value"),
                                 accounts=tuple(accounts.get(item["institution_id"], ())))
            for item in names]


async def rate_month(database: Any, month: date, status: str, as_of: datetime,
                     formula: dict[str, Any] = own.FORMULA_CURRENT) -> dict | None:
    start, end = rf.month_window(month)
    window_end = min(end, as_of)
    parameters = {"window_start": start, "window_end": window_end,
                  "mature_before": as_of - timedelta(days=formula["matureAfterDays"])}
    rows = await database.fetch_all(sql.OWN_ACCOUNTS, parameters)
    names = await database.fetch_all(sql.OWN_INSTITUTIONS)
    elapsed = (window_end - start).total_seconds() / 86400
    days = calendar.monthrange(month.year, month.month)[1]
    results = own.compute(institutions(names, rows, formula), elapsed_days=elapsed, days_in_month=days, formula=formula)
    snapshot = {"status": status, "period": rf.period_label(month), "formulaVersion": formula["version"],
                "elapsedDays": round(elapsed, 2), "institutions": len(names), "ranked": len(results)}
    digest = hashlib.sha256(json.dumps({"month": month.isoformat(), "parameters": snapshot, "results": results},
                                       sort_keys=True, default=str).encode()).hexdigest()
    body = {"formulaKey": own.FORMULA_KEY, "version": formula["version"],
            "windowStart": start.astimezone(timezone.utc).isoformat(),
            "windowEnd": window_end.astimezone(timezone.utc).isoformat(),
            "asOf": as_of.astimezone(timezone.utc).isoformat(),
            "startedAt": as_of.astimezone(timezone.utc).isoformat(),
            "inputHash": digest, "parameters": snapshot, "results": results}
    row = await database.admin_fetch_one("SELECT ops_and_admin.record_rating_forecast(%(payload)s::jsonb) AS result",
                                         {"payload": json.dumps(body, ensure_ascii=False)})
    logger.info("наш рейтинг %s (%s): %d из %d вузов", month.isoformat(), status, len(results), len(names))
    return row["result"]


async def run(database: Any, as_of: datetime, *, retrospective: list[date] | None = None) -> list[dict]:
    """Снимки «Нашего рейтинга». Ошибка пишется в журнал и не прерывает прогноз."""
    recorded: list[dict] = []
    try:
        if retrospective:
            targets = [(month, "retrospective") for month in retrospective if month >= first_month()]
            close = None
        else:
            targets, close = months_to_rate(as_of)
        for month, status in targets:
            result = await rate_month(database, month, status, as_of)
            if result is not None:
                recorded.append(result)
        if close is not None:
            await database.admin_fetch_one(
                "SELECT ops_and_admin.finalize_rating_forecast(%(formula_key)s, %(window_start)s) AS result",
                {"formula_key": own.FORMULA_KEY, "window_start": rf.month_window(close)[0]})
    except Exception as error:  # noqa: BLE001 — наш рейтинг вторичен к прогнозу
        logger.error("наш рейтинг не записан: %s", type(error).__name__)
    return recorded
