from pathlib import Path
import pytest
from collector_target.metrics import CollectorMetrics
from collector_target.model import Platform,RunStatus


def test_prometheus_metrics_are_bounded_and_atomically_published(tmp_path: Path):
    target=tmp_path/'collector.prom'
    metrics=CollectorMetrics(target)
    for platform in Platform:
        metrics.account(platform,succeeded=True,duration=.25,snapshots=3)
        metrics.account(platform,succeeded=False,duration=2)
        metrics.run(platform,RunStatus.PARTIAL)
    text=target.read_text()
    assert text==metrics.render()
    assert 'mranked_collector_snapshots_total{platform="vk"} 3' in text
    assert 'mranked_collector_runs_total{platform="max",status="partial"} 1' in text
    assert 'le="0.5"} 1' in text
    assert len([line for line in text.splitlines() if not line.startswith('#')])<=140
    assert target.stat().st_mode & 0o777==0o640
    assert not list(tmp_path.glob('.collector.prom*'))
    with pytest.raises(ValueError): metrics.account('account-secret',succeeded=False,duration=1)
    with pytest.raises(ValueError): metrics.account(Platform.VK,succeeded=False,duration=float('nan'))
