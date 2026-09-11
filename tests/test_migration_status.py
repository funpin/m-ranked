"""Regressions for the progress publisher installed during production import."""
from contextlib import nullcontext
from copy import deepcopy
import io
import json
from types import SimpleNamespace

import pytest

from operations.migration_status import publish


@pytest.fixture
def progress(monkeypatch):
    control = {
        "phase": "importing", "message": "Перенос данных",
        "batchId": "private-batch", "sourceNamespace": "private-source",
        "inventoryPath": "/private/source/inventory.json",
    }
    inventory = {
        "quick_check": ["ok"], "foreign_key_violations": 0, "sha256": "a" * 64,
        "tables": {name: {"count": 100} for name in publish.STREAMS},
    }
    state = SimpleNamespace(
        batch=(control["sourceNamespace"], inventory["sha256"], False, "running"),
        checkpoints=[("posts", "posts", 100), ("reaction_snapshots", "reaction_snapshots", 25)],
        queries=[],
    )

    def execute(sql, params=()):
        state.queries.append((sql, params))
        return SimpleNamespace(fetchone=lambda: state.batch, fetchall=lambda: state.checkpoints)

    import psycopg
    monkeypatch.setenv("MRANKED_PROGRESS_DATABASE_URL", "postgresql://private-credential")
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: nullcontext(SimpleNamespace(execute=execute)))
    monkeypatch.setattr(publish.urllib.request, "urlopen", lambda *args, **kwargs: io.StringIO('{"collector_fresh":true}'))
    return control, inventory, state


def test_progress_counts_only_committed_checkpoints_and_keeps_private_binding_out_of_json(progress):
    control, inventory, state = progress
    status = publish.build_status(control, inventory)
    assert (status["total"], status["transferred"]) == (1000, 125)
    assert status["progressAvailable"] is True
    assert "Сбор данных продолжается" in status["collectionMessage"]
    assert state.queries[0] == ("SET TRANSACTION READ ONLY", ())
    assert all(params == (control["batchId"],) for _, params in state.queries[1:])
    assert "private" not in json.dumps(status)


@pytest.mark.parametrize("batch", [None, ("other", "a" * 64, False, "running"),
                                  ("private-source", "b" * 64, False, "running"),
                                  ("private-source", "a" * 64, True, "running")])
def test_progress_rejects_a_different_snapshot_namespace_or_dry_run(progress, batch):
    control, inventory, state = progress
    state.batch = batch
    with pytest.raises(ValueError, match="Batch does not match source"):
        publish.build_status(control, inventory)


@pytest.mark.parametrize("checkpoint", [("unknown", "unknown", 1), ("posts", "channels", 1),
                                       ("posts", "posts", -1), ("posts", "posts", 101)])
def test_progress_rejects_unbound_or_impossible_checkpoint_counts(progress, checkpoint):
    control, inventory, state = progress
    state.checkpoints = [checkpoint]
    with pytest.raises(ValueError, match="Invalid checkpoint"):
        publish.build_status(control, inventory)


@pytest.mark.parametrize("phase", ["failed", "cancelled"])
def test_failed_import_keeps_confirmed_counts_and_clears_eta(progress, phase):
    control, inventory, state = progress
    state.batch = (*state.batch[:3], phase)
    estimate = publish.TransferEstimate()
    estimate.update("private-batch", 0, 1000, 0)
    estimate.update("private-batch", 100, 1000, 60)
    status = publish.build_status(control, inventory, estimate)
    assert status["phase"] == "blocked" and status["transferred"] == 125
    assert status["estimatedRemainingSeconds"] is None
    assert estimate.batch_id is None
    assert control["phase"] == "importing"


def test_progress_cannot_declare_cutover_complete_from_import_counters(progress):
    control, inventory, state = progress
    state.batch = (*state.batch[:3], "completed")
    with pytest.raises(ValueError, match="Final acceptance"):
        publish.build_status(dict(control, phase="complete"), inventory)


def test_unverified_inventory_and_active_transfer_without_binding_are_rejected(progress):
    control, inventory, _ = progress
    damaged = deepcopy(inventory)
    damaged["foreign_key_violations"] = 1
    with pytest.raises(ValueError, match="Unverified snapshot"):
        publish.build_status(control, damaged)
    with pytest.raises(ValueError, match="exact batch binding"):
        publish.build_status(dict(control, batchId=None), inventory)


def test_eta_excludes_restart_pause_and_waits_for_a_fresh_minute():
    estimate = publish.TransferEstimate()
    assert estimate.update("batch", 0, 100_000, 0) == (None, None)
    assert estimate.update("batch", 6000, 100_000, 60) == (940, 100.0)
    assert estimate.update("batch", 6000, 100_000, 120) == (None, None)
    assert estimate.update("batch", 6000, 100_000, 600) == (None, None)
    assert estimate.update("batch", 9000, 100_000, 630) == (None, None)
    assert estimate.update("batch", 12000, 100_000, 660) == (880, 100.0)


def test_eta_resets_on_batch_change_counter_rollback_and_completion():
    estimate = publish.TransferEstimate()
    estimate.update("first", 0, 100_000, 0)
    estimate.update("first", 6000, 100_000, 60)
    assert estimate.update("second", 20_000, 100_000, 70) == (None, None)
    assert estimate.update("second", 100, 100_000, 80) == (None, None)
    assert estimate.update("second", 100_000, 100_000, 140) == (None, None)


def test_eta_increases_when_sustained_transfer_slows_down():
    estimate = publish.TransferEstimate()
    estimate.update("batch", 0, 1_000_000, 0)
    previous, _ = estimate.update("batch", 60_000, 1_000_000, 60)
    for now in range(70, 661, 10):
        eta, speed = estimate.update("batch", 60_000 + (now - 60) * 100, 1_000_000, now)
    assert eta > previous
    assert 100 <= speed < 300


def test_status_file_is_replaced_atomically_without_temporary_files(tmp_path):
    path = tmp_path / "migration-status.json"
    publish.atomic_write(path, {"transferred": 10})
    publish.atomic_write(path, {"transferred": 20, "message": "Перенос"})
    assert json.loads(path.read_text()) == {"transferred": 20, "message": "Перенос"}
    assert list(tmp_path.iterdir()) == [path]
    assert path.stat().st_mode & 0o777 == 0o644


def test_publisher_failure_retains_last_confirmed_counts_and_timestamp(tmp_path, monkeypatch, capsys):
    control, output = tmp_path / "control.json", tmp_path / "status.json"
    control.write_text("{}")  # Missing inventory path simulates unavailable private control.
    previous = {"total": 1000, "transferred": 125, "updatedAt": "2026-09-06T12:00:00Z",
                "phase": "importing", "message": "Перенос", "progressAvailable": True,
                "estimatedRemainingSeconds": 10, "rowsPerSecond": 87.5}
    publish.atomic_write(output, previous)
    monkeypatch.setattr(publish.argparse.ArgumentParser, "parse_args", lambda self: SimpleNamespace(
        control=control, output=output, once=True))
    with pytest.raises(SystemExit) as exit:
        publish.main()
    assert exit.value.code == 1
    assert json.loads(output.read_text()) == dict(previous, progressAvailable=False,
                                                 estimatedRemainingSeconds=None, rowsPerSecond=None)
    assert capsys.readouterr().out == "Progress unavailable: KeyError\n"
