"""Ночной пересчёт норм анализа v2.

Короткое задание раз в сутки: отобрать чистые посты окна, построить нормы
аккаунтов и площадок, проверить новую версию эталоном и дрейфом и записать
её одной транзакцией. Принятую норму никогда не подменяет непроверенная:
отклонённая версия и версия на разборе дрейфа записываются для истории, а
работник остаётся на последней принятой.

Чистый пост — без признаков абсолютных детекторов и без уровня 2–3 в
текущем выводе, не репост и не эталон. Абсолютные детекторы прогоняются
здесь заново: на первом запуске вывода ещё нет, а норма всё равно не должна
выучить механическую подачу.

    ANOMALY_DATABASE_URL=... python -m anomaly_analysis.norms_job
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import groupby
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import UUID

from .metrics import write_textfile
from .tools.reference_format import ReferenceCase, parse_case
from .v2.detectors import ABSOLUTE_DETECTORS, DetectorContext
from .v2.domain import Level
from .v2.levels import WEAK, reference_assessor
from .v2.norms import (
    NORM_MODEL_VERSION, Drift, NormSet, NormStatus, ReferenceCheck, ReferencePost, build_account_norm,
    check_reference, combine, drift, raw_account_norm,
)
from .v2.reference import synthetic_reference
from .v2.series import DAY, CollectionCadence, prepare
from .v2.store import SERIES_BATCH, PostgresAnomalyStore, SeriesTarget

PLATFORMS = ("telegram", "vk", "max", "rutube")
ABSOLUTE_PATTERNS = frozenset({1, 6, 7, 8, 9})
NORM_RELATIVE_PATTERNS = frozenset({2, 4, 5, 10})
# Шестьдесят суток публикаций: посты второй половины окна отслежены целиком,
# на них считается доля итога за тридцать дней.
DEFAULT_WINDOW_DAYS = 60
FINAL_AGE = 30 * DAY
DEFAULT_REFERENCE_DIRS = ""

log = logging.getLogger("anomaly_analysis.norms_job")


def is_clean(level: int, signals: Iterable[Mapping[str, Any]]) -> bool:
    """Годится ли пост в норму по его текущему выводу."""
    return level <= Level.WEAK_SIGNAL and not any(int(item.get("pattern", 0)) in ABSOLUTE_PATTERNS
                                                   for item in signals)


def absolutely_clean(prepared) -> bool:
    """Абсолютные детекторы молчат — ни одного признака хотя бы слабой силы."""
    context = DetectorContext(prepared.series.platform)
    return not any(sign.strength >= WEAK for detector in ABSOLUTE_DETECTORS
                   for sign in detector.detect(prepared, context))


def load_reference(directories: str, root: Path = Path(".")) -> list[ReferenceCase]:
    cases = []
    for directory in filter(None, directories.split(":")):
        for path in sorted((root / directory).glob("*.json")):
            case = parse_case(json.loads(path.read_text(encoding="utf-8")))
            if case.expected_min_level is not None:
                cases.append(case)
    return cases


def reference_posts(cases: Iterable[ReferenceCase], norms: NormSet,
                    cadence: CollectionCadence) -> tuple[list[ReferencePost], dict[UUID, NormSet]]:
    """Эталон площадки и нормы, при которых его проверять.

    Пока норма молода, признаки относительно неё не сильнее слабого сигнала —
    случаи, которые держатся только на них, требовать от молодой нормы нельзя.
    Честные случаи проверяются сверху всегда.
    """
    posts, norms_by_case = [], {}
    for case in cases:
        if case.subject.platform != norms.platform.platform:
            continue
        required = case.expected_min_level
        if norms.platform.young and case.expected_patterns and case.expected_patterns <= NORM_RELATIVE_PATTERNS:
            required = Level.NONE
        case_norms = norms
        if len(case.siblings) >= 20:
            own = build_account_norm(norms.platform, case.subject.account_id,
                                     [prepare(item, item.observed_at[-1], cadence) for item in case.siblings],
                                     final_age=7 * DAY)
            if own is not None:
                case_norms = NormSet(norms.platform, {case.subject.account_id: own})
        posts.append(ReferencePost(case.case_id, case.subject, case.siblings, required, case.expected_max_level))
        norms_by_case[case.subject.publication_id] = case_norms
    return posts, norms_by_case


def decide(checks: Mapping[str, ReferenceCheck], drifts: Mapping[str, Drift]) -> tuple[NormStatus, list[str]]:
    failures = [f"{platform}:{case}" for platform, check in sorted(checks.items()) for case in check.failures]
    if failures:
        return NormStatus.REJECTED, failures
    if any(item.sharp for item in drifts.values()):
        return NormStatus.DRIFT_REVIEW, []
    return NormStatus.ACCEPTED, []


class NormJob:
    def __init__(self, store: PostgresAnomalyStore, cadence: CollectionCadence, reference: Sequence[ReferenceCase],
                 *, window_days: int = DEFAULT_WINDOW_DAYS,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.store = store
        self.cadence = cadence
        self.reference = list(reference)
        self.window_days = window_days
        self.clock = clock
        self.summary: dict[str, dict[str, float]] = {}

    def run(self) -> tuple[int, NormStatus]:
        now = self.clock()
        reference_ids = {case.subject.publication_id for case in self.reference}
        candidates = self.store.norm_candidates(now - timedelta(days=self.window_days), now)
        norm_sets = {platform: combine(platform, {}) for platform in PLATFORMS}
        for platform, rows in groupby(candidates, key=lambda row: row["platform"]):
            raw = {}
            for account, items in groupby(rows, key=lambda row: row["account_id"]):
                clean = [row for row in items if row["publication_id"] not in reference_ids
                         and is_clean(int(row["level"]), row["signals"] or ())]
                posts = self._clean_series(clean)
                if posts:
                    # Ряды аккаунта отпускаются сразу: в памяти только его маленькая норма.
                    raw[account] = raw_account_norm(platform, account, posts, final_age=FINAL_AGE)
            norm_sets[platform] = combine(platform, raw)
        previous = self.store.latest_accepted_norm_version()
        assessor = reference_assessor(self.cadence)
        checks, drifts = {}, {}
        for platform, norms in norm_sets.items():
            posts, norms_by_case = reference_posts(self.reference, norms, self.cadence)
            checks[platform] = check_reference(
                norms, posts, lambda subject, siblings, used: assessor(subject, siblings,
                                                                       norms_by_case[subject.publication_id]))
            before = self.store.read_norms(previous, platform) if previous is not None else None
            drifts[platform] = drift(norms.platform, before.platform if before else None)
            self.summary[platform] = {"posts": norms.platform.posts, "accounts": len(norms.accounts),
                                      "confidence": norms.platform.confidence}
        status, failures = decide(checks, drifts)
        version = self.store.write_norm_version(
            NORM_MODEL_VERSION, status, list(norm_sets.values()), reference_failures=failures,
            drift={platform: {"shift_mads": round(item.max_shift_mads, 4),
                              "exponent_shift": round(item.max_exponent_shift, 4)}
                   for platform, item in drifts.items()},
            previous_version_id=previous)
        log.info("norm version %s: %s (%s)", version, status.value, ", ".join(failures) or "reference passed")
        return version, status

    def _clean_series(self, rows: Sequence[Mapping[str, Any]]):
        posts = []
        for start in range(0, len(rows), SERIES_BATCH):
            batch = rows[start:start + SERIES_BATCH]
            series = self.store.read_series([SeriesTarget(row["publication_id"], row["published_at"])
                                             for row in batch])
            for item in series.values():
                if not item.observed_at:
                    continue
                prepared = prepare(item, item.observed_at[-1], self.cadence)
                if absolutely_clean(prepared):
                    posts.append(prepared)
        return posts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("ANOMALY_DATABASE_URL is required")
    window = int(os.environ.get("ANOMALY_NORM_WINDOW_DAYS", str(DEFAULT_WINDOW_DAYS)))
    # Синтетический эталон строится в памяти из кода модуля; из каталогов
    # читаются только выгруженные реальные ряды, которым не место в публичном
    # репозитории.
    reference = synthetic_reference() + load_reference(
        os.environ.get("ANOMALY_REFERENCE_DIRS", DEFAULT_REFERENCE_DIRS))
    metrics_value = os.environ.get("ANOMALY_NORMS_METRICS_FILE", "").strip()
    started = time.monotonic()
    job = NormJob(PostgresAnomalyStore(dsn), CollectionCadence.from_environment(os.environ), reference,
                  window_days=window)
    version, status = job.run()
    samples = [("norm_last_run_unixtime", "gauge", {}, time.time()),
               ("norm_run_seconds", "gauge", {}, time.monotonic() - started),
               ("norm_latest_version", "gauge", {}, version),
               ("norm_reference_cases", "gauge", {}, len(reference))]
    samples += [("norm_latest_status", "gauge", {"status": item.value}, float(item is status)) for item in NormStatus]
    for platform, values in sorted(job.summary.items()):
        samples += [(f"norm_{key}", "gauge", {"platform": platform}, value) for key, value in values.items()]
    write_textfile(Path(metrics_value) if metrics_value else None, samples)


if __name__ == "__main__":
    main()
