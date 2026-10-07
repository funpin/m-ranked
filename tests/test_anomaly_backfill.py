"""A partial backfill must never advertise a safe resume cursor."""
from types import SimpleNamespace
from uuid import UUID

import pytest

from anomaly_analysis import backfill
from anomaly_reference.mature_norms import synthetic_cases


class Store:
    def __init__(self, missing=False):
        self.accounts = [UUID(int=1), UUID(int=2), UUID(int=3)]
        self.subject = synthetic_cases()["honest_organic_max"].subject
        self.missing = missing
        self.visited, self.writes = [], []

    def latest_accepted_norm_version(self):
        return None

    def backfill_accounts(self, since):
        return self.accounts

    def backfill_targets(self, account, since):
        self.visited.append(account)
        return [SimpleNamespace(publication_id=self.subject.publication_id, signals=(),
                                published_at=self.subject.published_at)]

    def read_activity(self, *args):
        return {}

    def read_subscribers(self, *args):
        return {}

    def read_series(self, targets):
        return {} if self.missing else {self.subject.publication_id: self.subject}

    def write_states(self, writes):
        self.writes.extend(writes)


def setup(monkeypatch, store, *args):
    monkeypatch.setattr(backfill, "PostgresAnomalyStore", lambda dsn: store)
    monkeypatch.setenv("ANOMALY_DATABASE_URL", "unused-test-dsn")
    monkeypatch.setattr(backfill.shutil, "disk_usage", lambda p: SimpleNamespace(total=10**12, free=9*10**11))
    monkeypatch.setattr(backfill.os, "statvfs", lambda p: SimpleNamespace(f_files=10000, f_favail=9000))
    monkeypatch.setattr("sys.argv", ["backfill", *args])


def test_bounded_resume_and_reference_rollback(monkeypatch, caplog):
    store = Store()
    setup(monkeypatch, store, "--max-accounts", "1", "--after-account", str(store.accounts[0]),
          "--disable-mature-reference")
    # The rollback must not even load a potentially missing release artifact.
    monkeypatch.setattr(backfill, "bundled_reference", lambda: pytest.fail("rollback loaded reference"))
    with caplog.at_level("INFO"):
        backfill.main()
    assert store.visited == [store.accounts[1]]
    assert len(store.writes) == 1
    assert "mature_reference_model" not in store.writes[0].verdict.detector_versions
    assert f"account_id={store.accounts[1]}" in caplog.text
    assert "backfill finished analyzed=1 failed=0" in caplog.text


@pytest.mark.parametrize("missing", [False, True])
def test_failure_stops_before_next_account_without_completed_cursor(monkeypatch, caplog, missing):
    store = Store(missing=missing)
    setup(monkeypatch, store)
    def fail(*args, **kwargs):
        raise ValueError("detector failure")
    monkeypatch.setattr(backfill, "assess", fail)
    with caplog.at_level("INFO"), pytest.raises(SystemExit) as result:
        backfill.main()
    assert result.value.code == 1
    assert store.visited == [store.accounts[0]]
    assert "backfill account incomplete" in caplog.text
    assert "backfill account 1/" not in caplog.text
    assert "backfill finished" not in caplog.text
