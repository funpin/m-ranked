"""Пересобрать зафиксированный 72-часовой ориентир признаков 11/12 по протоколу H36.

Ориентир живёт 28 суток после доступности; за трое суток до конца срока
предупреждает `MRankedAnomalyReferenceNeedsRenewal`. Новый файл кладётся
рядом с прежними (`anomaly_analysis/v2/references/max_*.json`), а не вместо
них: пост получает самый свежий ориентир, чья область покрывает его
публикацию, а сохранённые выводы продолжают ссылаться на свою версию.

Вход — компактная read-only выгрузка конечных точек
(`operations/sql/mature-reference-endpoints.sql`), по строке JSON на пост.
Протокол прежний (research/smart-engagement-2026-09/RELEASE.md): ridge
log(1+Y72) со штрафом 10 и индикаторами аккаунта, для условной компоненты —
стандартизованный log(1+Y24); масштаб — IQR остатков, не меньше 0,05; общий
порог — порядковая статистика максимума четырёх остатков на калибровке,
ранг (1 + число не меньших)/(n+1) ≤ 0,05. Аккаунт входит, если у него не
меньше пяти пригодных постов обучения; обучение и калибровка — не меньше
ста постов каждая. Отбора по прежним выводам анализа нет.

    python -m anomaly_analysis.tools.renew_mature_reference endpoints.jsonl.gz \\
        --version max-2026-09b-v1 --fit 2026-09-13 2026-09-17 --calibration 2026-09-20 2026-09-24 \\
        --available-at 2026-09-27 --output anomaly_analysis/v2/references/max_2026_09b.json

Даты — UTC, правая граница исключена. Файл проверяется тем же
`MatureReference.from_payload`, что и при запуске работника.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from ..v2.mature_reference import MatureReference

LIFETIME = timedelta(days=28)
MIN_ACCOUNT_POSTS = 5
MIN_FOLD = 100
PENALTY = 10.0
MIN_SCALE = 0.05
LEVEL = 0.05


def reason(row: Mapping[str, Any]) -> str:
    """Почему пост не годится в ориентир; «eligible» — годится."""
    if row["known_decrease"]:
        return "known_decrease"
    points = row["points"] or []
    if len(points) != 2 or any(point.get("observed_at") is None for point in points):
        return "missing_window"
    if any(point.get(metric) is None or point.get(metric + "q") != "exact" or point.get("uncertain") is not False
           for point in points for metric in ("v", "r")):
        return "nonexact_endpoint"
    return "eligible"


def fit(rows: Sequence[Mapping[str, Any]], *, version: str, fit_window: tuple[datetime, datetime],
        calibration_window: tuple[datetime, datetime], available_at: datetime,
        expires_at: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """Артефакт и отчёт о составе; ValueError — данных недостаточно."""
    def fold(row) -> str | None:
        published = datetime.fromisoformat(row["published_at"])
        if fit_window[0] <= published < fit_window[1]:
            return "fit"
        if calibration_window[0] <= published < calibration_window[1]:
            return "cal"
        return None

    reasons = Counter((fold(row), reason(row)) for row in rows)
    eligible = [row for row in rows if fold(row) and reason(row) == "eligible"]
    counts = Counter(row["primary_account_id"] for row in eligible if fold(row) == "fit")
    accounts = sorted(account for account, count in counts.items() if count >= MIN_ACCOUNT_POSTS)
    train = [row for row in eligible if fold(row) == "fit" and row["primary_account_id"] in accounts]
    calibration = [row for row in eligible if fold(row) == "cal" and row["primary_account_id"] in accounts]
    if min(len(train), len(calibration)) < MIN_FOLD:
        raise ValueError(f"insufficient fit/calibration: {len(train)}/{len(calibration)}")

    def matrix(records, conditional: bool, metric: str, center: float, sd: float):
        columns = [np.ones(len(records))]
        if conditional:
            columns.append((np.log1p([row["points"][0][metric] for row in records]) - center) / sd)
        columns.extend(np.array([row["primary_account_id"] == account for row in records], float)
                       for account in accounts)
        return np.column_stack(columns)

    components, scores = [], []
    for conditional in (True, False):
        for metric, name in (("v", "views"), ("r", "reactions")):
            early = np.log1p([row["points"][0][metric] for row in train])
            center, sd = float(early.mean()), max(float(early.std()), 1e-8)
            x = matrix(train, conditional, metric, center, sd)
            y = np.log1p([row["points"][1][metric] for row in train])
            penalty = PENALTY * np.eye(x.shape[1])
            penalty[0, 0] = 0
            beta = np.linalg.solve(x.T @ x + penalty, x.T @ y)
            residual = y - x @ beta
            scale = max(float(np.quantile(residual, .75) - np.quantile(residual, .25)), MIN_SCALE)
            prediction = matrix(calibration, conditional, metric, center, sd) @ beta
            scores.append((np.log1p([row["points"][1][metric] for row in calibration]) - prediction) / scale)
            offset = 2 if conditional else 1
            components.append({
                "conditional": conditional, "metric": name, "intercept": float(beta[0]),
                "slope": float(beta[1]) if conditional else 0.0, "center": center, "sd": sd, "scale": scale,
                "effects": {account: float(beta[index + offset]) for index, account in enumerate(accounts)},
            })
    joint = np.maximum(0, np.array(scores).max(axis=0))
    cutoff = float(np.sort(joint)[math.ceil((len(calibration) + 1) * (1 - LEVEL)) - 1])
    artifact = {
        "schema_version": "1.0.0", "reference_version": version, "platform": "max",
        "fit_start": fit_window[0].isoformat(), "calibration_end": calibration_window[1].isoformat(),
        "available_at": available_at.isoformat(), "expires_at": expires_at.isoformat(),
        "fit_count": len(train), "calibration_count": len(calibration),
        "account_counts": {account: counts[account] for account in accounts},
        "cutoff": cutoff, "components": components,
    }
    report = {
        "fit": len(train), "calibration": len(calibration), "accounts": len(accounts),
        "calibration_flagged": int((joint > cutoff).sum()),
        "reasons": {f"{key[0]}:{key[1]}": value for key, value in sorted(reasons.items(), key=str)},
    }
    return artifact, report


def _day(value: str) -> datetime:
    return datetime.combine(date.fromisoformat(value), time(0), timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--fit", nargs=2, required=True, metavar=("FROM", "UNTIL"))
    parser.add_argument("--calibration", nargs=2, required=True, metavar=("FROM", "UNTIL"))
    parser.add_argument("--available-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    raw = gzip.decompress(arguments.input.read_bytes())
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    available = _day(arguments.available_at)
    fit_window = (_day(arguments.fit[0]), _day(arguments.fit[1]))
    calibration_window = (_day(arguments.calibration[0]), _day(arguments.calibration[1]))
    # Все калибровочные посты должны достичь 72 часов до доступности ориентира.
    if calibration_window[1] + timedelta(hours=72) > available:
        raise SystemExit("available-at must follow the calibration window by at least 72 hours")
    artifact, report = fit(rows, version=arguments.version, fit_window=fit_window,
                           calibration_window=calibration_window, available_at=available,
                           expires_at=available + LIFETIME)
    artifact["input_sha256"] = hashlib.sha256(raw).hexdigest()
    MatureReference.from_payload(artifact)
    arguments.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
