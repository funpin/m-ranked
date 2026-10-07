"""Синхронный подъём у левого края окна агрегатов аккаунта.

Работник держит агрегаты за трое суток и переносит признаки 8, начавшиеся
раньше «начало окна + сутки». В той же полосе суточная база подъёма обрезана
(у края — пустая), и ровный темп выглядел подъёмом у всех постов разом. Такой
признак записывался и со следующего анализа переносился навсегда (ЮЗГУ ВК
№74388: «+4 у этого» силой 1.0 через трое суток после события).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.detectors import DetectorContext, SiblingActivity, synchronous_rise
from anomaly_analysis.v2.domain import Interval, Metric, PostSeries, Sign
from anomaly_analysis.v2.levels import assess, sign_payload
from anomaly_analysis.v2.series import HOUR, CollectionCadence, prepare

ACCOUNT = UUID("00000000-0000-4000-8000-00000000a002")
WINDOW_START = datetime(2026, 10, 4, 13, 0, tzinfo=timezone.utc)
PUBLISHED = WINDOW_START - timedelta(days=2)
RATE = 6   # реакций в час: пара часов даёт 12 — выше порога широкого подъёма
HOURS = 30


def _subject() -> PostSeries:
    minutes = range(-120, HOURS * 60 + 1, 15)
    instants = tuple(WINDOW_START + timedelta(minutes=minute) for minute in minutes)
    reactions = tuple(RATE * 48 + RATE * minute // 60 for minute in minutes)
    return PostSeries(UUID(int=1), ACCOUNT, "vk", PUBLISHED, False, instants,
                      {Metric.VIEWS: tuple(10 * value for value in reactions), Metric.REACTIONS: reactions})


def _activity() -> SiblingActivity:
    first = int(WINDOW_START.timestamp() // HOUR)
    rows = [{"publication_id": UUID(int=10 + sibling), "published_at": PUBLISHED, "hour": first + hour,
             "reactions": RATE * (48 + hour), "views": 10 * RATE * (48 + hour)}
            for sibling in range(5) for hour in range(-1, HOURS + 1)]
    activity = SiblingActivity.from_hourly(rows, first, first + HOURS)
    assert activity is not None
    return activity


def _rises(context: DetectorContext) -> list[str]:
    subject = _subject()
    prepared = prepare(subject, WINDOW_START + timedelta(hours=HOURS), CollectionCadence())
    return [sign.render["hour"] for sign in synchronous_rise.detect(prepared, context)
            if sign.metric is Metric.REACTIONS]


def test_a_steady_pace_at_the_window_edge_looked_like_a_synchronous_rise():
    # Механизм ошибки: без границы у края окна пустая база даёт «подъём».
    assert _rises(DetectorContext("vk", None, _activity()))


def test_no_synchronous_rise_is_found_before_the_carried_boundary():
    boundary = WINDOW_START + timedelta(hours=synchronous_rise.BASELINE_HOURS)
    context = DetectorContext("vk", None, _activity(), synchrony_from=boundary.timestamp())
    assert _rises(context) == []


def test_assess_passes_the_boundary_to_the_detector():
    boundary = WINDOW_START + timedelta(hours=synchronous_rise.BASELINE_HOURS)

    def synchrony(**extra):
        verdict = assess(_subject(), analyzed_at=WINDOW_START + timedelta(hours=HOURS), activity=_activity(),
                         **extra)
        return [sign for sign in verdict.signs if sign.pattern == synchronous_rise.PATTERN]

    assert synchrony()
    assert synchrony(synchrony_from=boundary) == []


def test_the_worker_does_not_detect_where_it_carries():
    from test_anomaly_worker import FakeStore, _row, _worker

    subject = _subject()
    now = WINDOW_START + timedelta(hours=72)   # окно работника — трое суток

    class Store(FakeStore):
        def read_activity(self, accounts, since, until, published_since):
            assert since == WINDOW_START
            return {ACCOUNT: _activity()}

    store = Store({subject.publication_id: subject}, [_row(subject, now)])
    _worker(store, now).run_once()
    (write,) = store.written
    assert write.verdict is not None
    assert not [sign for sign in write.verdict.signs if sign.pattern == synchronous_rise.PATTERN]


def _backfill(monkeypatch, *flags) -> list:
    import sys
    from anomaly_analysis import backfill
    from anomaly_analysis.v2.store import DueRow

    subject = _subject()
    # Артефакт края окна, записанный прежним работником: признак 8 в час, где
    # при полной суточной базе подъёма нет.
    hour = WINDOW_START + timedelta(hours=1)
    artefact = sign_payload(Sign(
        synchronous_rise.PATTERN, synchronous_rise.FAMILY, Metric.REACTIONS, 1.0, Interval(hour, hour + timedelta(hours=1)),
        synchronous_rise.SCALE, "реакции подросли одновременно у 6 постов аккаунта",
        {"kind": "synchrony", "posts": 6, "quiet": 0, "hour": hour.isoformat(),
         "measurementMode": "exact_quality_v1"}, ("account_mentioned_externally",)))
    written = []

    class Store:
        def __init__(self, dsn):
            pass

        def latest_accepted_norm_version(self):
            return None

        def backfill_accounts(self, since):
            return [ACCOUNT]

        def backfill_targets(self, account, since):
            return [DueRow(subject.publication_id, subject.published_at, since, None, None, None, 0, (artefact,))]

        def read_activity(self, accounts, since, until, published_since):
            return {}

        def read_subscribers(self, accounts, since, until):
            return {}

        def read_series(self, targets):
            return {subject.publication_id: subject}

        def write_states(self, writes):
            written.extend(writes)

    monkeypatch.setenv("MRANKED_STORAGE_PATH", "/private/tmp" if sys.platform == "darwin" else "/tmp")
    monkeypatch.setattr(backfill, "PostgresAnomalyStore", Store)
    monkeypatch.setenv("ANOMALY_DATABASE_URL", "postgresql://example.invalid/x")
    monkeypatch.setattr(sys, "argv", ["backfill", "--days", "35", *flags])
    backfill.main()
    (write,) = written
    return [sign for sign in write.verdict.signs if sign.pattern == synchronous_rise.PATTERN]


def test_backfill_keeps_previous_synchrony_by_default(monkeypatch):
    assert len(_backfill(monkeypatch)) == 1


def test_backfill_can_redetect_synchrony_inside_its_window(monkeypatch):
    # Агрегаты на всё окно дают полную базу: признак 8 находится заново, а
    # прежний внутри окна не переносится — так снимаются артефакты края.
    assert _backfill(monkeypatch, "--redetect-synchrony") == []
