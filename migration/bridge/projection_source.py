"""Private source-only overlay for owner-verified disappeared legacy rows."""
from __future__ import annotations

from contextlib import closing,contextmanager
from pathlib import Path
import sqlite3
import tempfile

from .model import row_hash, stable_uuid
from .source import LegacySource, sha256_file


class ProjectionSourceError(ValueError):
    pass


def _identifier(value):
    return '"' + value.replace('"','""') + '"'


@contextmanager
def projection_source(source:Path, connection, *, source_name:str, current_batch_id,
        preserved_source_paths=()):
    namespace=stable_uuid('m-ranked-bridge','source_namespace',{'name':source_name})
    preservation_count=connection.execute('SELECT count(*) FROM migration.source_preservation WHERE source_namespace=%s',
        (namespace,)).fetchone()[0]
    if not preservation_count:
        if preserved_source_paths:
            raise ProjectionSourceError('PRESERVED_SOURCE_NOT_CLASSIFIED')
        yield source,{'mode':'original','restoredRows':0,'priorSourceSha256':[]}
        return
    if not preserved_source_paths:
        raise ProjectionSourceError('PRESERVED_HISTORY_ORACLE_RECONSTRUCTION_REQUIRED')
    if len(preserved_source_paths)>64:
        raise ProjectionSourceError('PRESERVED_SOURCE_ARTIFACT_BOUND_EXCEEDED')
    priors={}
    for path in preserved_source_paths:
        path=Path(path).resolve(strict=True);digest=sha256_file(path)
        known=connection.execute('''SELECT count(*) FROM migration.source_preservation p
            JOIN migration.import_batch b ON b.source_name=%s AND b.source_sha256=p.prior_source_sha256 AND NOT b.dry_run
            WHERE p.source_namespace=%s AND p.prior_source_sha256=%s''',(source_name,namespace,digest)).fetchone()[0]
        if not known:
            raise ProjectionSourceError('PRESERVED_SOURCE_ARTIFACT_NOT_VERIFIED')
        priors[digest]=LegacySource(path)
    from .service import BridgeService,_source_pk,_without_internal
    with tempfile.TemporaryDirectory(prefix='mranked-source-overlay-') as directory:
        overlay=Path(directory)/'overlay.sqlite'
        with LegacySource(source).connect() as original:
            with closing(sqlite3.connect(overlay)) as copied:
                original.backup(copied)
        overlay.chmod(0o600)
        # One bounded disk index holds approval keys, never target metric values.
        index=sqlite3.connect(Path(directory)/'approval.sqlite')
        index.execute('PRAGMA cache_size=-2048')
        index.execute('CREATE TABLE approved(table_name TEXT,pk TEXT,row_hash TEXT,prior_hash TEXT,used INTEGER DEFAULT 0,PRIMARY KEY(table_name,pk,row_hash,prior_hash))')
        restored=0
        try:
            with connection.cursor(name='projection_source_approvals') as cursor:
                cursor.itersize=500
                cursor.execute('''SELECT DISTINCT d.source_table,d.source_pk,d.source_row_hash,p.prior_source_sha256
                    FROM migration.source_disappearance_decision d
                    JOIN migration.preserved_source_decision verified ON verified.decision_id=d.id
                    JOIN migration.source_preservation p ON p.id=verified.preservation_id
                    JOIN migration.legacy_identity_map m ON m.source_namespace=d.source_namespace
                      AND m.source_table=d.source_table AND m.source_pk=d.source_pk AND m.target_type=d.target_type
                      AND m.source_row_hash=d.source_row_hash
                    WHERE d.source_namespace=%s AND p.source_namespace=%s AND d.decision='preserved_history'
                      AND m.last_seen_batch_id<>%s''',(namespace,namespace,current_batch_id))
                index.executemany('INSERT OR IGNORE INTO approved(table_name,pk,row_hash,prior_hash) VALUES(?,?,?,?)',cursor)
            if index.execute('SELECT count(*) FROM approved').fetchone()[0]>250_000:
                raise ProjectionSourceError('PRESERVED_SOURCE_ROW_BOUND_EXCEEDED')
            tables={row[0] for row in index.execute('SELECT DISTINCT table_name FROM approved')}
            if not tables.issubset(BridgeService.STREAMS):
                raise ProjectionSourceError('PRESERVED_SOURCE_TABLE_UNSUPPORTED')
            with closing(sqlite3.connect(overlay)) as output, output:
                output.row_factory=sqlite3.Row
                output.execute('PRAGMA journal_mode=DELETE')
                output.execute('PRAGMA foreign_keys=OFF')
                for table in BridgeService.STREAMS:
                    if table not in tables:continue
                    columns=tuple(row[1] for row in output.execute('PRAGMA table_info('+_identifier(table)+')'))
                    if not columns:raise ProjectionSourceError('PRESERVED_SOURCE_SCHEMA_MISMATCH')
                    for digest,prior in priors.items():
                        if prior.columns(table)!=columns:
                            raise ProjectionSourceError('PRESERVED_SOURCE_SCHEMA_MISMATCH')
                        for batch in prior.iter_rows(table,batch_size=500):
                            for row in batch:
                                pk=_source_pk(table,row);clean=_without_internal(row);value_hash=row_hash(clean)
                                approval=index.execute('SELECT 1 FROM approved WHERE table_name=? AND pk=? AND row_hash=? AND prior_hash=?',
                                    (table,pk,value_hash,digest)).fetchone()
                                if not approval:continue
                                if table=='post_messages':
                                    condition='post_id=? AND telegram_message_id=?';keys=(row['post_id'],row['telegram_message_id'])
                                else:
                                    key='key' if table=='app_state' else 'version' if table=='schema_migrations' else 'id'
                                    condition=_identifier(key)+'=?';keys=(row[key],)
                                existing=output.execute('SELECT * FROM '+_identifier(table)+' WHERE '+condition,keys).fetchone()
                                if existing is not None:
                                    if row_hash(dict(existing))!=value_hash:
                                        raise ProjectionSourceError('PRESERVED_SOURCE_CURRENT_ROW_CONFLICT')
                                else:
                                    output.execute('INSERT INTO '+_identifier(table)+' ('+','.join(map(_identifier,columns))+') VALUES ('+','.join('?' for _ in columns)+')',
                                        tuple(clean[column] for column in columns))
                                    restored+=1
                                index.execute('UPDATE approved SET used=1 WHERE table_name=? AND pk=? AND row_hash=?',(table,pk,value_hash))
                if index.execute('SELECT count(*) FROM approved WHERE used=0').fetchone()[0]:
                    raise ProjectionSourceError('PRESERVED_SOURCE_ROW_EVIDENCE_MISSING')
                if output.execute('PRAGMA quick_check').fetchone()[0]!='ok' or output.execute('PRAGMA foreign_key_check').fetchone():
                    raise ProjectionSourceError('PRESERVED_SOURCE_OVERLAY_INTEGRITY_FAILED')
            for digest,prior in priors.items():
                if sha256_file(prior.path)!=digest:
                    raise ProjectionSourceError('PRESERVED_SOURCE_ARTIFACT_CHANGED')
            metadata={'mode':'verified-preserved-source-overlay','restoredRows':restored,
                'overlaySha256':sha256_file(overlay),'priorSourceSha256':sorted(priors)}
            yield overlay,metadata
            if sha256_file(overlay)!=metadata['overlaySha256']:
                raise ProjectionSourceError('PRESERVED_SOURCE_OVERLAY_CHANGED')
            for digest,prior in priors.items():
                if sha256_file(prior.path)!=digest:
                    raise ProjectionSourceError('PRESERVED_SOURCE_ARTIFACT_CHANGED')
        finally:index.close()
