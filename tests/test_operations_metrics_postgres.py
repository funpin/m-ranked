"""Real role smoke; configured DSNs point to a disposable fixture."""
import os
from pathlib import Path

import pytest

from operations.observability.exporter import sample


@pytest.mark.skipif(not os.getenv('MRANKED_TEST_METRICS_MONITOR_DSN'),reason='requires disposable monitoring/application fixture endpoints')
def test_real_operational_sources_are_healthy_bounded_and_secret_free(tmp_path: Path):
    environment={
        'OPS_MONITOR_DATABASE_URL':os.environ['MRANKED_TEST_METRICS_MONITOR_DSN'],
        'OPS_APPLICATION_DATABASE_URL':os.environ['MRANKED_TEST_METRICS_APPLICATION_DSN'],
        'OPS_DISK_PATH':str(tmp_path),
    }
    for kind in ('WAL','EVIDENCE','COLD'):
        root=tmp_path/kind; root.mkdir(); (root/'fixture').write_bytes(b'counter-only')
        environment['OPS_'+kind+'_SPOOL']=str(root)
    content,success=sample(environment)
    assert success, [line for line in content.splitlines() if line.startswith('mranked_ops_source_up')]
    assert all('source="'+source+'"} 1' in content for source in ('postgres','application','spool','disk'))
    samples=[line for line in content.splitlines() if not line.startswith('#')]
    assert len(samples)<=64
    # Очередь анализа v2 публикует сам работник; экспортёр её не дублирует.
    assert not any(line.startswith('mranked_ops_anomaly_') for line in samples)
    assert all(value not in content for value in environment.values())
