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
    monkeypatch.setenv("MRANKED_APPROVED_RELEASE_REMOVALS", "old-release")
    monkeypatch.setattr(gc_host_storage, "docker_mount_releases", lambda root: set())
    monkeypatch.setattr(gc_host_storage, "systemd_releases", lambda root: set())
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


def test_stopped_service_release_and_forensic_are_preserved(monkeypatch, tmp_path):
    releases, _ = configure(monkeypatch, tmp_path)
    for name in ['rollback', 'future-unit', 'forensic']:
        (releases/name).mkdir()
        age(releases/name, 4)
    monkeypatch.setattr(gc_host_storage, 'systemd_releases', lambda root: {root/'future-unit'})
    monkeypatch.setenv('MRANKED_PROTECTED_RELEASES', 'forensic')
    monkeypatch.setenv('MRANKED_APPROVED_RELEASE_REMOVALS', 'future-unit,forensic')
    gc_host_storage.collect(apply=True)
    assert (releases/'future-unit').is_dir()
    assert (releases/'forensic').is_dir()


def test_docker_gc_never_prunes(monkeypatch):
    monkeypatch.setattr(gc_host_storage.subprocess, 'run', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not execute prune')))
    gc_host_storage.run_docker_gc(1, True)


def test_gc_refuses_when_process_references_cannot_be_read(monkeypatch,tmp_path):
    import pytest
    releases,proc=configure(monkeypatch,tmp_path)
    (proc/'123').mkdir()
    original=Path.resolve
    def resolve(path,*args,**kwargs):
        if path == proc/'123'/'cwd':
            raise PermissionError('restricted proc')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'resolve',resolve)
    with pytest.raises(RuntimeError,match='GC refused'):
        gc_host_storage.collect(apply=True)


def test_systemd_template_and_dropin_keep_next_start_releases(monkeypatch, tmp_path):
    from types import SimpleNamespace
    root = tmp_path / 'releases'
    monkeypatch.setattr(gc_host_storage.shutil, 'which', lambda name: '/bin/systemctl')
    def run(args, **kwargs):
        if args[1] == 'list-unit-files':
            return SimpleNamespace(stdout='m-ranked-collector@.service disabled\nm-ranked-api.service enabled\n')
        assert args[1] == 'cat'  # show refuses collector@.service on production systemd
        return SimpleNamespace(stdout=(
            f'# template\nWorkingDirectory={root}/collector-rollback\n'
            f'# drop-in\nExecStart={root}/api-rollback/.venv/bin/python -m api\n'
        ))
    monkeypatch.setattr(gc_host_storage.subprocess, 'run', run)
    assert gc_host_storage.systemd_releases(root) == {root/'collector-rollback', root/'api-rollback'}
