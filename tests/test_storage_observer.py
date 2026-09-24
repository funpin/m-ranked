import json
from pathlib import Path
import stat
import subprocess
import sys


def test_observer_metrics_readable_by_exporter_and_history_private(tmp_path):
    script = Path(__file__).parents[1] / 'operations/scripts/storage_guard.py'
    state = tmp_path / 'state.json'
    metrics = tmp_path / 'storage.prom'
    backups = tmp_path / 'backups'
    backups.mkdir()
    args = [sys.executable, str(script), 'observe', '--path', str(tmp_path),
            '--state', str(state), '--metrics', str(metrics), '--backup-dir', str(backups)]
    for _ in range(2):
        subprocess.run(args, check=True, capture_output=True)
        assert stat.S_IMODE(metrics.stat().st_mode) == 0o644
        assert stat.S_IMODE(state.stat().st_mode) == 0o600
    assert len(json.loads(state.read_text())) == 2
    assert 'mranked_storage_backup_source_up 1' in metrics.read_text()
    assert not list(tmp_path.glob('.storage-*'))
