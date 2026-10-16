"""Бэктест прогноза М-Рейтинга: прогноз опубликованных месяцев против факта.

Читает наши агрегаты из базы (копия прода, только чтение) и официальный
JSON источника (скачанный файл ratings-2026.json), считает прогноз тем же
модулем, что и ночное задание, и печатает ошибки. Нужен, чтобы видеть, когда
пороги формулы уехали и пора выпускать новую версию.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api import rating_forecast as rf  # noqa: E402
from api.institution_profile import _students_by_institution  # noqa: E402
from api.sql import rating as sql  # noqa: E402

KEYS = {"social": "social", "max": "ok", "vk": "vk", "rutube": "rt"}


def official(source: dict, month: date) -> rf.BaseMonth:
    item = source["months"][month.month - 1]
    return rf.BaseMonth(period=rf.period_label(month), names={row["code"]: row["name"] for row in item["items"]},
                        scores={row["code"]: {category: row["scores"].get(key) for category, key in KEYS.items()}
                                for row in item["items"] if row.get("code")})


def institutions(connection, month: date, as_of: datetime) -> list[rf.InstitutionMonth]:
    start, end = rf.month_window(month)
    rows = connection.execute(sql.PLATFORM_MONTH, {"window_start": start, "window_end": end,
                                                   "mature_before": as_of - timedelta(days=3)}).fetchall()
    students, grouped = _students_by_institution(), {}
    for row in rows:
        entry = grouped.setdefault(row["institution_id"], {"code": row["code"], "name": row["name"], "platforms": {}})
        if row["platform"] is not None:
            entry["platforms"][row["platform"]] = rf.PlatformMonth(
                posts=row["posts"], viewed_posts=row["viewed_posts"], views=int(row["views"]),
                interactions=int(row["interactions"]), covered=bool(row["covered"]))
    return [rf.InstitutionMonth(key, value["code"], value["name"], (students.get(key) or {}).get("value"),
                                value["platforms"]) for key, value in grouped.items()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--months", required=True)
    arguments = parser.parse_args()
    source = json.loads(arguments.source.read_text(encoding="utf-8"))
    as_of = datetime.now(timezone.utc)
    with psycopg.connect(arguments.dsn, row_factory=dict_row) as connection:
        connection.execute("SET jit = off")
        for text in arguments.months.split(","):
            month = date.fromisoformat(f"{text}-01")
            previous = (month - timedelta(days=1)).replace(day=1)
            base, fact = official(source, previous), official(source, month)
            rows = rf.forecast(institutions(connection, month, as_of), base, rf.FORMULA_V1["defaultErrors"])
            print(f"== {fact.period} (база {base.period}), вузов {len(rows)}")
            for category in rf.CATEGORIES:
                predicted = {row["explanation"]["code"]: row["explanation"]["categories"][category]["score"] for row in rows}
                ranks = {row["explanation"]["code"]: row["explanation"]["categories"][category]["rank"] for row in rows}
                actual_pool = {code: score[category] for code, score in fact.scores.items() if score.get(category) is not None}
                actual_ranks = rf.rank_in_pool(actual_pool, fact.names)
                result = rf.evaluate(predicted, actual_pool, ranks, actual_ranks)
                print(f"  {category:7s} MAE {result['mae']:5.1f} | место: медиана {result['rankMedian']:5.1f}, "
                      f"p80 {result['rankP80']:3d} | ρ {result['spearman']:.2f} | топ-20 {result['top20Hits']}/{result['top20Total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
