"""The scheduled research rollup must stay opt-in and bounded."""

from __future__ import annotations

import json
from datetime import date, timedelta
from uuid import UUID

import pytest

from anomaly_analysis import m0_rollup_job


ACCOUNT = UUID("00000000-0000-4000-8000-000000000001")


def test_disabled_rollup_does_not_touch_the_database(monkeypatch, capsys):
    monkeypatch.delenv("ANOMALY_M0_ROLLUP_ENABLED", raising=False)
    monkeypatch.setattr(m0_rollup_job.psycopg, "connect",
                        lambda *_args, **_kwargs: pytest.fail("unexpected database read"))
    m0_rollup_job.main()
    assert json.loads(capsys.readouterr().out)["status"] == "disabled"


def test_plan_requires_every_opted_in_account_and_limits_catchup():
    today = date(2026, 9, 27)
    with pytest.raises(ValueError, match="UUIDs"):
        m0_rollup_job._accounts(f"{ACCOUNT},")
    with pytest.raises(ValueError, match="absent"):
        m0_rollup_job._plan([], (ACCOUNT,), today)
    assert m0_rollup_job._plan([(ACCOUNT, "telegram")], (ACCOUNT,), today) == (
        ("telegram", (ACCOUNT,), today - timedelta(days=6),
         today + timedelta(days=1)),
    )


def test_enabled_rollup_checks_database_and_invokes_bounded_writer(monkeypatch, capsys):
    monkeypatch.setenv("ANOMALY_M0_ROLLUP_ENABLED", "true")
    monkeypatch.setenv("ANOMALY_M0_ACCOUNT_IDS", str(ACCOUNT))
    monkeypatch.setenv("ANOMALY_M0_EXPECTED_DATABASE", "research")
    monkeypatch.setenv("ANOMALY_M0_MAX_GAP_MINUTES", "60")
    monkeypatch.setenv("ANOMALY_DATABASE_URL", "postgresql:///research")

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return (self.value,)

        def fetchall(self):
            return [(ACCOUNT, "telegram")]

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, _params=None):
            return Result("research" if "current_database" in sql else None)

    monkeypatch.setattr(m0_rollup_job.psycopg, "connect",
                        lambda *_args, **_kwargs: Connection())
    calls = []
    monkeypatch.setattr(m0_rollup_job, "run_rollup",
                        lambda **kwargs: calls.append(kwargs) or {"kind": "rollup"})
    m0_rollup_job.main()
    assert len(calls) == 1
    assert calls[0]["accounts"] == (ACCOUNT,)
    assert calls[0]["expected_database"] == "research"
    assert calls[0]["write"] is True
    assert calls[0]["max_gap_minutes"] == 60
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["status"] == "complete"
