from pathlib import Path

import pytest

from operations.observability import exporter


def test_unavailable_dependencies_emit_only_bounded_health_without_secrets(monkeypatch):
    def fail(*args,**kwargs): raise RuntimeError('password=secret-token https://private/path')
    monkeypatch.setattr(exporter,'database_metrics',fail)
    text,success=exporter.sample({'OPS_MONITOR_DATABASE_URL':'secret-token'})
    assert not success
    assert 'secret-token' not in text and 'private' not in text and 'RuntimeError' not in text
    assert text.count('mranked_ops_source_up{')==5
    assert len(text.splitlines())<=14
    assert 'source="postgres"} 0' in text


def test_spool_scan_is_bounded_ignores_symlinks_and_publishes_atomically(tmp_path: Path):
    (tmp_path/'one').write_bytes(b'123')
    (tmp_path/'link').symlink_to(tmp_path/'one')
    stats=exporter.spool_metrics(tmp_path)
    assert stats['bytes']==3 and stats['files']==1
    with pytest.raises(ValueError,match='budget'): exporter.spool_metrics(tmp_path,max_entries=1)
    output=tmp_path/'ops.prom'
    exporter.publish(output,'# TYPE example gauge\nexample 1\n')
    assert output.read_text().endswith('example 1\n')
    assert output.stat().st_mode & 0o777==0o640
    assert not list(tmp_path.glob('.ops.prom*'))


def test_database_metric_names_and_sql_do_not_expose_private_content():
    sql=exporter.PG_SQL+exporter.APP_SQL
    assert 'query' not in sql and 'external_ref' not in sql and 'raw_payload' not in sql
    assert 'ingest.publication_metric_snapshot' not in sql
    assert 'relation_name' not in sql
    assert len(exporter.NAMES['postgres'])==12
