"""Работник анализа v2: очередь по таблице периодичности, пачки по 50 постов.

Цикл: поставить в очередь новые посты окна → взять 50 самых свежих
просроченных → прочитать их ряды одним запросом → решить по расписанию →
подготовить ряды, прогнать детекторы, собрать уровень → записать состояния,
а журнал — только при смене вывода. Ошибка одного поста не роняет пачку: у
поста код ошибки и отступ повтора, у остальных — обычная запись.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import time
from typing import Callable, Mapping, Sequence
from uuid import UUID

import numpy as np

from .detectors.synchronous_rise import BASELINE_HOURS
from .domain import PostSeries
from .levels import assess, sign_from_payload
from .norms import NormSet
from .schedule import ScheduleConfig, plan, retry_after, stretch_for_lag
from .series import GAP_FACTOR, HOUR, CollectionCadence
from .store import DueRow, PostgresAnomalyStore, SeriesTarget, StateWrite

PLATFORMS = ("telegram", "vk", "max", "rutube")
SYNCHRONY_PATTERN = 8


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    batch_size: int = 50
    seed_limit: int = 500
    # Синхронность смотрит на последние трое суток агрегатов аккаунта; агрегат
    # аккаунта и его подписчики живут в кэше час — они общие для всех его постов.
    activity_lookback_seconds: int = 72 * 3600
    account_cache_seconds: int = 3600

    def __post_init__(self) -> None:
        if not 1 <= self.batch_size <= 200 or self.seed_limit < 1:
            raise ValueError("worker batch bounds are invalid")


class AnalysisError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _AccountCache:
    ttl: float
    entries: dict[UUID, tuple[float, object]] = field(default_factory=dict)

    def missing(self, accounts: Sequence[UUID], clock: float) -> list[UUID]:
        return [account for account in accounts
                if account not in self.entries or clock - self.entries[account][0] > self.ttl]

    def put(self, values: Mapping[UUID, object], accounts: Sequence[UUID], clock: float, empty) -> None:
        for account in accounts:
            self.entries[account] = (clock, values.get(account, empty))

    def get(self, account: UUID):
        entry = self.entries.get(account)
        return None if entry is None else entry[1]


@dataclass
class WorkerMetrics:
    outcomes: Counter = field(default_factory=Counter)
    levels: Counter = field(default_factory=Counter)
    signals: Counter = field(default_factory=Counter)
    log_entries: int = 0
    seeded: int = 0
    due_backlog: int = 0
    queue_lag_seconds: float = 0.0
    stretch: float = 1.0
    norm_version: int = 0
    last_batch_size: int = 0
    last_batch_seconds: float = 0.0
    last_completion: float = 0.0

    def samples(self):
        for outcome in ("analyzed", "postponed", "failed", "frozen"):
            yield "analyses_total", "counter", {"outcome": outcome}, self.outcomes[outcome]
        for level in range(4):
            yield "verdicts_total", "counter", {"level": str(level)}, self.levels[level]
        for pattern in (1, 2, 4, 5, 6, 7, 8, 9, 10):
            yield "signals_total", "counter", {"pattern": str(pattern)}, self.signals[pattern]
        yield "log_entries_total", "counter", {}, self.log_entries
        yield "seeded_total", "counter", {}, self.seeded
        yield "due_backlog", "gauge", {}, self.due_backlog
        yield "queue_lag_seconds", "gauge", {}, self.queue_lag_seconds
        yield "interval_stretch", "gauge", {}, self.stretch
        yield "norm_version", "gauge", {}, self.norm_version
        yield "last_batch_size", "gauge", {}, self.last_batch_size
        yield "last_batch_seconds", "gauge", {}, self.last_batch_seconds
        yield "last_completion_unixtime", "gauge", {}, self.last_completion


class Worker:
    def __init__(self, store: PostgresAnomalyStore, schedule: ScheduleConfig, cadence: CollectionCadence,
                 config: WorkerConfig = WorkerConfig(), *,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 publish: Callable[[WorkerMetrics], None] = lambda metrics: None) -> None:
        self.store = store
        self.schedule = schedule
        self.cadence = cadence
        self.config = config
        self.clock = clock
        self.publish = publish
        self.metrics = WorkerMetrics()
        self.norm_version: int | None = None
        self.norms: dict[str, NormSet] = {}
        self._activity = _AccountCache(config.account_cache_seconds)
        self._subscribers = _AccountCache(config.account_cache_seconds)

    def run_once(self) -> int:
        started = time.monotonic()
        now = self.clock()
        self.metrics.seeded += self.store.seed_new(now, self.schedule.seed_seconds, self.config.seed_limit)
        self._refresh_norms(now)
        lag, backlog = self.store.queue_state(now)
        stretch = stretch_for_lag(self.schedule, lag)
        self.metrics.queue_lag_seconds, self.metrics.due_backlog, self.metrics.stretch = lag, backlog, stretch
        due = self.store.claim_due(now, self.config.batch_size)
        if due:
            self._analyze(due, now, stretch)
        self.metrics.last_batch_size = len(due)
        self.metrics.last_batch_seconds = time.monotonic() - started
        self.metrics.last_completion = time.time()
        self.publish(self.metrics)
        return len(due)

    def _refresh_norms(self, now: datetime) -> None:
        version = self.store.latest_accepted_norm_version()
        if version is None or version == self.norm_version:
            return
        self.norms = {platform: norms for platform in PLATFORMS
                      if (norms := self.store.read_norms(version, platform)) is not None}
        self.norm_version = version
        self.metrics.norm_version = version
        # Новая принятая норма — перепроверка всех незамороженных постов, растянутая по окну.
        self.store.schedule_norm_recheck(version, now, self.schedule.recheck_window_seconds)

    def _analyze(self, due: Sequence[DueRow], now: datetime, stretch: float) -> None:
        series = self.store.read_series([SeriesTarget(row.publication_id, row.published_at) for row in due])
        accounts = sorted({item.account_id for item in series.values()}, key=str)
        window_start = now - timedelta(seconds=self.config.activity_lookback_seconds)
        self._load_accounts(accounts, now, window_start)
        writes: list[StateWrite] = []
        postponed: list[tuple[UUID, datetime]] = []
        for row in due:
            try:
                subject = series.get(row.publication_id)
                if subject is None or not subject.observed_at:
                    raise AnalysisError("series_unavailable")
                decision = self._plan(row, subject, now, stretch)
                if not decision.analyze:
                    postponed.append((row.publication_id, decision.next_due_at))
                    self.metrics.outcomes["postponed"] += 1
                    continue
                verdict = assess(
                    subject, norms=self.norms.get(subject.platform),
                    subscribers=self._subscribers.get(subject.account_id) or (), analyzed_at=now,
                    cadence=self.cadence, norm_version=self.norm_version,
                    activity=self._activity.get(subject.account_id),
                    carried=_carried(row, window_start + timedelta(hours=BASELINE_HOURS)))
                writes.append(StateWrite(
                    row.publication_id, row.published_at, now, decision.next_due_at, verdict=verdict,
                    analyzed_points=len(subject.observed_at), last_point_observed_at=subject.observed_at[-1],
                    norm_version_id=self.norm_version, frozen=decision.frozen,
                    lag_seconds=max(0, int((now - row.next_due_at).total_seconds())), reason=decision.reason))
                self.metrics.outcomes["frozen" if decision.frozen else "analyzed"] += 1
                self.metrics.levels[int(verdict.level)] += 1
                for sign in verdict.signs:
                    self.metrics.signals[sign.pattern] += 1
            except Exception as error:  # ошибка одного поста не должна останавливать пачку
                code = error.code if isinstance(error, AnalysisError) else "analysis_failed"
                writes.append(StateWrite(row.publication_id, row.published_at, now,
                                         now + retry_after(row.attempts), error_code=code))
                self.metrics.outcomes["failed"] += 1
        self.metrics.log_entries += self.store.write_states(writes)
        self.store.postpone(postponed)

    def _plan(self, row: DueRow, subject: PostSeries, now: datetime, stretch: float):
        last = row.last_point_observed_at
        new = [at for at in subject.observed_at if last is None or at > last]
        step = self.cadence.expected_step_seconds(
            subject.platform, _ages(subject, (now,)))[0]
        resumed = bool(last and new and (new[0] - last).total_seconds() > GAP_FACTOR * step)
        stale = (now - subject.observed_at[-1]).total_seconds() > GAP_FACTOR * step
        return plan(self.schedule, platform=subject.platform, published_at=subject.published_at, now=now,
                    new_points=len(new), analyzed_before=row.analyzed_at is not None,
                    resumed_after_gap=resumed, stale=stale, stretch=stretch,
                    norm_recheck=self.norm_version is not None and row.norm_version_id != self.norm_version)

    def _load_accounts(self, accounts: Sequence[UUID], now: datetime, window_start: datetime) -> None:
        clock = time.monotonic()
        published_since = now - timedelta(seconds=self.schedule.track_seconds + 24 * HOUR)
        missing = self._activity.missing(accounts, clock)
        if missing:
            self._activity.put(self.store.read_activity(missing, window_start, now, published_since),
                               missing, clock, None)
        missing = self._subscribers.missing(accounts, clock)
        if missing:
            self._subscribers.put(self.store.read_subscribers(missing, published_since, now),
                                  missing, clock, [])


def _ages(series: PostSeries, moments) -> np.ndarray:
    return np.array([(moment - series.published_at).total_seconds() for moment in moments])


def _carried(row: DueRow, detectable_from: datetime):
    """Признаки синхронности прежнего вывода, которые уже нельзя найти заново."""
    carried = []
    for payload in row.signals:
        if int(payload.get("pattern", 0)) != SYNCHRONY_PATTERN:
            continue
        sign = sign_from_payload(payload)
        if sign.interval.start < detectable_from:
            carried.append(sign)
    return tuple(carried)
