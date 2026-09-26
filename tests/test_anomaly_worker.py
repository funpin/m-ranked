"""Работник v2 на поддельном хранилище: пачка, отсрочка, ошибки, нормы, догонка, метрики."""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

from anomaly_analysis.metrics import write_textfile
from anomaly_analysis.v2.domain import Level
from anomaly_analysis.v2.schedule import ScheduleConfig
from anomaly_analysis.v2.series import CollectionCadence
from anomaly_analysis.v2.store import DueRow, Progress
from anomaly_analysis.v2.worker import Worker
from anomaly_reference.mature_norms import synthetic_cases


class FakeStore:
    def __init__(self, series, due, *, norm_version=None):
        self.series = series
        self.due = list(due)
        self.norm_version = norm_version
        self.written, self.postponed, self.rechecks = [], [], []
        self.series_reads: list = []
        self.progress_enabled = True

    def seed_new(self, now, window, limit):
        return 0

    def latest_accepted_norm_version(self):
        return self.norm_version

    def read_norms(self, version, platform):
        return None

    def schedule_norm_recheck(self, version, now, window):
        self.rechecks.append(version)
        return 0

    def queue_state(self, now):
        return (0.0, len(self.due))

    def claim_due(self, now, limit):
        taken = [row for row in self.due if row.next_due_at <= now][:limit]
        return sorted(taken, key=lambda row: row.published_at, reverse=True)

    def read_progress(self, rows):
        # Считается из тех же рядов, что читает read_series, — как в базе.
        if not self.progress_enabled:
            return {}
        found = {}
        for row in rows:
            subject = self.series.get(row.publication_id)
            if subject is None:
                continue
            new = [at for at in subject.observed_at if at > row.last_point_observed_at]
            found[row.publication_id] = Progress(subject.platform, len(new), new[0] if new else None,
                                                 subject.observed_at[-1] if subject.observed_at else None)
        return found

    def read_series(self, targets):
        self.series_reads.extend(target.publication_id for target in targets)
        return {target.publication_id: self.series[target.publication_id]
                for target in targets if target.publication_id in self.series}

    def read_activity(self, accounts, since, until, published_since):
        return {}

    def read_subscribers(self, accounts, since, until):
        return {}

    def write_states(self, writes):
        self.written.extend(writes)
        # Выполненный анализ снимает пост с очереди до нового срока, как в базе.
        for write in writes:
            self.due = [replace(row, next_due_at=write.next_due_at, analyzed_at=write.analyzed_at,
                                last_point_observed_at=write.last_point_observed_at or row.last_point_observed_at)
                        if row.publication_id == write.publication_id else row for row in self.due]
        # Замороженный пост в очередь больше не попадает — так работает индекс NOT frozen.
        frozen = {write.publication_id for write in writes if write.frozen}
        self.due = [row for row in self.due if row.publication_id not in frozen]
        return sum(write.verdict is not None and write.verdict.level > 0 for write in writes)

    def postpone(self, items):
        self.postponed.extend(items)
        for publication_id, due in items:
            self.due = [replace(row, next_due_at=due) if row.publication_id == publication_id else row
                        for row in self.due]


def _row(series, due_at):
    return DueRow(series.publication_id, series.published_at, due_at, None, None, None, 0, ())


def _worker(store, now):
    return Worker(store, ScheduleConfig(), CollectionCadence(), clock=lambda: now)


def test_a_batch_is_analyzed_and_errors_stay_with_their_post():
    cases = synthetic_cases()
    linear = cases["p01_linear_feed_vk"].subject
    organic = cases["honest_organic_max"].subject
    now = linear.observed_at[-1]
    missing = UUID(int=404)
    store = FakeStore({linear.publication_id: linear, organic.publication_id: organic}, [
        _row(linear, now), _row(organic, now),
        DueRow(missing, now - timedelta(days=1), now, None, None, None, 2, ()),
    ])
    assert _worker(store, now).run_once() == 3
    by_id = {write.publication_id: write for write in store.written}
    assert by_id[linear.publication_id].verdict.level >= Level.PRONOUNCED_ANOMALY
    assert by_id[organic.publication_id].verdict.level == Level.NONE
    failed = by_id[missing]
    assert failed.error_code == "series_unavailable" and failed.next_due_at == now + timedelta(minutes=4)


def test_without_three_new_points_the_post_is_only_postponed():
    subject = synthetic_cases()["honest_organic_vk"].subject
    now = subject.observed_at[-1]
    row = DueRow(subject.publication_id, subject.published_at, now, now - timedelta(hours=1),
                 subject.observed_at[-2], None, 0, ())
    store = FakeStore({subject.publication_id: subject}, [row])
    _worker(store, now).run_once()
    assert not store.written and store.postponed and store.postponed[0][1] > now
    # Отложен без чтения ряда: новых точек мало видно и без него.
    assert store.series_reads == []


def test_postponing_without_the_series_decides_exactly_like_the_series():
    cases = synthetic_cases()
    rows, series = [], {}
    for name in ("honest_organic_vk", "honest_organic_telegram", "p01_linear_feed_vk", "honest_organic_max"):
        subject = cases[name].subject
        series[subject.publication_id] = subject
        points = subject.observed_at
        now = points[-1] + timedelta(minutes=20)
        # Прошлая точка: последняя, предпоследняя, три назад и далеко в прошлом —
        # от «новых точек нет» до «пора анализировать» и «сбор возобновился».
        for index, back in enumerate((1, 2, 4, len(points) // 2)):
            rows.append(DueRow(UUID(int=len(rows) + 1), subject.published_at, now, now - timedelta(hours=2),
                               points[-back], None, 0, ()))
            series[rows[-1].publication_id] = replace(subject, publication_id=rows[-1].publication_id)
    outcomes = []
    for enabled in (True, False):
        for row in rows:
            store = FakeStore(series, [row])
            store.progress_enabled = enabled
            _worker(store, row.next_due_at).run_once()
            outcomes.append((row.publication_id, tuple(store.postponed),
                             tuple((write.next_due_at, write.reason) for write in store.written)))
    half = len(outcomes) // 2
    assert outcomes[:half] == outcomes[half:]
    assert any(item[1] for item in outcomes[:half]) and any(item[2] for item in outcomes[:half])


def test_catch_up_analyzes_each_overdue_post_once():
    subject = synthetic_cases()["honest_organic_telegram"].subject
    now = subject.published_at + timedelta(days=12)
    # Пост просрочен на трое суток простоя: один анализ сейчас, повторов нет.
    store = FakeStore({subject.publication_id: subject}, [_row(subject, now - timedelta(days=3))])
    worker = _worker(store, now)
    worker.run_once()
    worker.run_once()
    assert len(store.written) == 1 and store.written[0].next_due_at == now + timedelta(hours=3)


def test_end_of_window_freezes_and_a_new_norm_triggers_a_recheck(tmp_path):
    subject = synthetic_cases()["honest_organic_rutube"].subject
    now = subject.published_at + timedelta(days=31)
    store = FakeStore({subject.publication_id: subject}, [_row(subject, now)], norm_version=7)
    worker = _worker(store, now)
    path = tmp_path / "anomaly.prom"
    worker.publish = lambda metrics: write_textfile(path, metrics.samples())
    worker.run_once()
    assert store.written[0].frozen and store.written[0].reason == "final"
    assert store.rechecks == [7] and store.written[0].norm_version_id == 7
    worker.run_once()
    assert store.rechecks == [7]
    text = path.read_text()
    assert 'mranked_anomaly_analyses_total{outcome="frozen"} 1' in text
    assert "mranked_anomaly_norm_version 7" in text and "mranked_anomaly_last_completion_unixtime" in text
