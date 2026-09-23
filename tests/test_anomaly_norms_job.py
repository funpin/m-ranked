"""Ночной пересчёт норм без базы: отбор чистых постов, эталон, дрейф, первый запуск."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from anomaly_analysis.norms_job import NormJob, absolutely_clean, is_clean, load_reference
from anomaly_analysis.v2.domain import Level
from anomaly_analysis.v2.norms import NormStatus
from anomaly_analysis.v2.series import CollectionCadence, prepare
from anomaly_analysis.v2.reference import background
from anomaly_reference.mature_norms import synthetic_cases

CADENCE = CollectionCadence()
NOW = datetime(2026, 4, 1, tzinfo=timezone.utc)


class FakeStore:
    def __init__(self, series, levels=None, previous=None):
        self.series = {item.publication_id: item for item in series}
        self.levels = levels or {}
        self.previous = previous
        self.written = []

    def norm_candidates(self, since, until):
        rows = [{"publication_id": item.publication_id, "published_at": item.published_at,
                 "account_id": item.account_id, "platform": item.platform,
                 "level": self.levels.get(item.publication_id, (0, []))[0],
                 "signals": self.levels.get(item.publication_id, (0, []))[1]} for item in self.series.values()]
        return sorted(rows, key=lambda row: (row["platform"], str(row["account_id"]), row["published_at"]))

    def read_series(self, targets):
        return {target.publication_id: self.series[target.publication_id] for target in targets}

    def latest_accepted_norm_version(self):
        return None if self.previous is None else 1

    def read_norms(self, version, platform):
        return self.previous.get(platform) if self.previous else None

    def write_norm_version(self, model, status, norms, *, reference_failures=(), drift=None, previous_version_id=None):
        self.written.append({"status": status, "norms": {item.platform.platform: item for item in norms},
                             "failures": list(reference_failures), "drift": drift})
        return len(self.written)


def _background():
    return [item for platform in ("telegram", "vk", "max", "rutube")
            for items in background(platform).values() for item in items]


def test_clean_selection_rules():
    assert is_clean(0, []) and is_clean(1, [{"pattern": 10}])
    assert not is_clean(2, []) and not is_clean(1, [{"pattern": 9}])
    linear = synthetic_cases()["p01_linear_feed_vk"].subject
    organic = synthetic_cases()["honest_organic_vk"].subject
    assert not absolutely_clean(prepare(linear, linear.observed_at[-1], CADENCE))
    assert absolutely_clean(prepare(organic, organic.observed_at[-1], CADENCE))


def test_reference_is_loaded_with_its_expectations():
    # Без каталогов выгрузки задание берёт только синтетику, и вся она размечена.
    assert load_reference("") == []
    assert all(case.expected_min_level is not None for case in synthetic_cases().values())


def test_mature_norms_pass_the_reference_and_exclude_pumped_and_flagged_posts():
    reference = list(synthetic_cases().values())
    organic = _background()
    pumped = synthetic_cases()["p01_linear_feed_vk"].subject
    flagged = replace(organic[0], publication_id=UUID(int=77))
    store = FakeStore(organic + [pumped, flagged], levels={flagged.publication_id: (2, [])})
    version, status = NormJob(store, CADENCE, reference, clock=lambda: NOW).run()
    assert version == 1 and status is NormStatus.ACCEPTED, store.written[0]["failures"]
    norms = store.written[0]["norms"]
    # Подача ВК и пост уровня 2 в норму не попали: постов ровно столько, сколько органики.
    assert norms["vk"].platform.posts == sum(item.platform == "vk" for item in organic)
    assert norms["telegram"].platform.posts == sum(item.platform == "telegram" for item in organic)


def test_first_run_on_empty_history_gives_a_young_norm_that_is_still_accepted():
    store = FakeStore([])
    _, status = NormJob(store, CADENCE, list(synthetic_cases().values()), clock=lambda: NOW).run()
    assert status is NormStatus.ACCEPTED
    assert all(norm.platform.young for norm in store.written[0]["norms"].values())


def test_a_norm_that_hides_the_reference_is_rejected():
    reference = [replace(case, expected_min_level=Level.ARTIFICIAL_ACTIVITY_SIGNS)
                 for case in synthetic_cases().values() if case.case_id == "p09_burst_plateau_telegram"]
    store = FakeStore(_background())
    _, status = NormJob(store, CADENCE, reference, clock=lambda: NOW).run()
    assert status is NormStatus.REJECTED
    assert store.written[0]["failures"] == ["telegram:p09_burst_plateau_telegram"]


def test_sharp_shift_against_the_previous_accepted_norm_goes_to_review():
    organic = _background()
    first = FakeStore(organic)
    NormJob(first, CADENCE, [], clock=lambda: NOW).run()
    # Предыдущая принятая норма ВК считалась по аккаунтам с вдесятеро большей вовлечённостью.
    shifted = [replace(item, values={metric: tuple(None if value is None else value * (10 if metric.value != "views" else 1)
                                                   for value in column)
                                     for metric, column in item.values.items()})
               for item in organic]
    previous = FakeStore(shifted)
    NormJob(previous, CADENCE, [], clock=lambda: NOW).run()
    store = FakeStore(organic, previous=previous.written[0]["norms"])
    _, status = NormJob(store, CADENCE, [], clock=lambda: NOW).run()
    assert status is NormStatus.DRIFT_REVIEW and store.written[0]["drift"]["vk"]["shift_mads"] > 1
    assert first.written[0]["status"] is NormStatus.ACCEPTED
