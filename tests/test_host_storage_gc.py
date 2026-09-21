import importlib.util
import os
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "operations" / "scripts" / "gc_host_storage.py"
SPEC = importlib.util.spec_from_file_location("gc_host_storage", SCRIPT)
assert SPEC and SPEC.loader
gc_host_storage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gc_host_storage)


def configure(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    releases = tmp_path / "releases"
    releases.mkdir()
    current = releases / "current-release"
    current.mkdir()
    (tmp_path / "current").symlink_to(current)
    proc = tmp_path / "proc"
    proc.mkdir()
    monkeypatch.setenv("MRANKED_RELEASE_ROOT", str(releases))
    monkeypatch.setenv("MRANKED_CURRENT_LINK", str(tmp_path / "current"))
    monkeypatch.setenv("MRANKED_PROC_ROOT", str(proc))
    monkeypatch.setenv("MRANKED_RELEASE_KEEP_ROLLBACKS", "1")
    monkeypatch.setenv("MRANKED_RELEASE_MIN_AGE_HOURS", "1")
    monkeypatch.setenv("MRANKED_DOCKER_PRUNE_ENABLED", "0")
    return releases, proc


def age(path: Path, hours: int) -> None:
    timestamp = gc_host_storage.time.time() - hours * 3_600
    os.utime(path, (timestamp, timestamp))


def test_collect_keeps_current_and_one_rollback(monkeypatch, tmp_path, capsys):
    releases, _ = configure(monkeypatch, tmp_path)
    rollback = releases / "rollback-release"
    old = releases / "old-release"
    rollback.mkdir()
    old.mkdir()
    age(releases / "current-release", 2)
    age(rollback, 3)
    age(old, 4)

    assert gc_host_storage.collect(apply=True) == 1

    assert (releases / "current-release").is_dir()
    assert rollback.is_dir()
    assert not old.exists()
    assert "removed release=old-release" in capsys.readouterr().out


def test_collect_protects_release_used_by_process(monkeypatch, tmp_path, capsys):
    releases, proc = configure(monkeypatch, tmp_path)
    rollback = releases / "rollback-release"
    active_old = releases / "active-old"
    rollback.mkdir()
    active_old.mkdir()
    age(releases / "current-release", 2)
    age(rollback, 3)
    age(active_old, 4)
    process = proc / "123"
    process.mkdir()
    (process / "cwd").symlink_to(active_old)

    assert gc_host_storage.collect(apply=True) == 0

    assert active_old.is_dir()
    assert "keep release=active-old reason=in-use" in capsys.readouterr().out
