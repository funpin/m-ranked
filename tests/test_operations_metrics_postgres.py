"""Real role/Redis smoke; the mandatory integration runner supplies fixture DSNs."""
import os
from pathlib import Path

import pytest

from operations.observability.exporter import sample


@pytest.mark.skipif(not os.getenv('MRANKED_TEST_METRICS_MONITOR_DSN'),reason='requires disposable monitoring/application/Redis fixture endpoints')
def test_real_operational_sources_are_healthy_bounded_and_secret_free(tmp_path: Path):
    environment={
        'OPS_MONITOR_DATABASE_URL':os.environ['MRANKED_TEST_METRICS_MONITOR_DSN'],
        'OPS_APPLICATION_DATABASE_URL':os.environ['MRANKED_TEST_METRICS_APPLICATION_DSN'],
        'OPS_REDIS_URL':os.environ['MRANKED_TEST_METRICS_REDIS_URL'],
        'OPS_DISK_PATH':str(tmp_path),
    }
    for kind in ('WAL','EVIDENCE','COLD'):
        root=tmp_path/kind; root.mkdir(); (root/'fixture').write_bytes(b'counter-only')
        environment['OPS_'+kind+'_SPOOL']=str(root)
    content,success=sample(environment)
    assert success, [line for line in content.splitlines() if line.startswith('mranked_ops_source_up')]
    assert all('source="'+source+'"} 1' in content for source in ('postgres','application','redis','spool','disk'))
    assert len([line for line in content.splitlines() if not line.startswith('#')])<=50
    assert all(value not in content for value in environment.values())
