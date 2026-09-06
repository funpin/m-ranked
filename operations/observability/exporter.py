"""Produce a private Prometheus textfile using explicit environment DSNs.

Only aggregate counters are returned. No query text, relation names, object
URIs, account identifiers, error messages or credential values are exposed.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import shutil
import tempfile
import time

import psycopg
import redis

PG_SQL = """SELECT jsonb_build_object(
 'wal_bytes_total',(SELECT wal_bytes FROM pg_stat_wal),
 'wal_archive_failures_total',(SELECT failed_count FROM pg_stat_archiver),
 'wal_last_archived_unixtime',(SELECT coalesce(extract(epoch FROM last_archived_time),0) FROM pg_stat_archiver),
 'replication_connected',(SELECT count(*) FROM pg_stat_replication),
 'replication_lag_bytes',(SELECT coalesce(max(pg_wal_lsn_diff(CASE WHEN pg_is_in_recovery() THEN pg_last_wal_receive_lsn() ELSE pg_current_wal_lsn() END,replay_lsn)),0) FROM pg_stat_replication),
 'replication_replay_lag_seconds',(SELECT coalesce(max(extract(epoch FROM replay_lag)),0) FROM pg_stat_replication),
 'lock_waits',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'),
 'database_bytes',pg_database_size(current_database()),
 'table_bytes',(SELECT coalesce(sum(pg_table_size(c.oid)),0) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('catalog','ingest','analytics','rating','ops_and_admin','migration') AND c.relkind IN ('r','m')),
 'index_bytes',(SELECT coalesce(sum(pg_indexes_size(c.oid)),0) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('catalog','ingest','analytics','rating','ops_and_admin','migration') AND c.relkind IN ('r','m')),
 'partition_bytes',(SELECT coalesce(sum(pg_total_relation_size(c.oid)),0) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='ingest' AND c.relispartition AND c.relkind='r'),
 'inserted_rows_total',(SELECT coalesce(sum(n_tup_ins),0) FROM pg_stat_user_tables WHERE schemaname IN ('catalog','ingest','analytics','rating','ops_and_admin','migration')))
"""
APP_SQL = """SELECT jsonb_build_object(
 'dataset_revision_lag',greatest(0,(SELECT coalesce(max(id),0) FROM analytics.dataset_revision)-(SELECT coalesce(min(dataset_revision_id),0) FROM analytics.projection_state)),
 'projection_not_ready',(SELECT count(*) FROM analytics.projection_state WHERE status<>'ready'),
 'archive_staging',(SELECT count(*) FROM ops_and_admin.archive_manifest WHERE status='staging'),
 'archive_verified',(SELECT count(*) FROM ops_and_admin.archive_manifest WHERE status='verified'),
 'archive_fenced',(SELECT count(*) FROM ops_and_admin.publication_partition_fence WHERE state='archiving'),
 'collection_rows_24h',(SELECT coalesce(sum(result.snapshot_count),0) FROM ingest.collection_run run JOIN ingest.collection_account_result result ON result.collection_run_id=run.id WHERE run.platform IN ('telegram','vk','max','rutube') AND run.started_at>=now()-interval '1 day'),
 'collection_last_success_unixtime',(SELECT coalesce(extract(epoch FROM max(completed_at)),0) FROM ingest.collection_run WHERE status='succeeded'))
"""
SOURCES=('postgres','application','redis','spool','disk')
NAMES={
    'postgres':('wal_bytes_total','wal_archive_failures_total','wal_last_archived_unixtime','replication_connected','replication_lag_bytes','replication_replay_lag_seconds','lock_waits','database_bytes','table_bytes','index_bytes','partition_bytes','inserted_rows_total'),
    'application':('dataset_revision_lag','projection_not_ready','archive_staging','archive_verified','archive_fenced','collection_rows_24h','collection_last_success_unixtime'),
    'redis':('used_memory_bytes','keyspace_hits_total','keyspace_misses_total','evicted_keys_total'),
    'disk':('free_bytes','total_bytes','required_5x_bytes','required_10x_bytes'),
}


def database_metrics(dsn: str, query: str) -> dict:
    with psycopg.connect(dsn,connect_timeout=3,options='-c statement_timeout=5000 -c default_transaction_read_only=on') as connection:
        return connection.execute(query).fetchone()[0]


def spool_metrics(root: Path, *, max_entries=10000) -> dict:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir(): raise ValueError('spool directory unavailable')
    size=0; count=0; oldest=time.time(); pending=[root]; visited=0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                visited+=1
                if visited>max_entries: raise ValueError('spool monitoring entry budget exceeded')
                if entry.is_symlink(): continue
                if entry.is_dir(follow_symlinks=False): pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    stat=entry.stat(follow_symlinks=False); count+=1; size+=stat.st_size; oldest=min(oldest,stat.st_mtime)
    return {'bytes':size,'files':count,'oldest_age_seconds':max(0,time.time()-oldest) if count else 0}


def sample(environment: dict[str,str]) -> tuple[str,bool]:
    metrics=[]; success=True; database_bytes=None

    def add(name: str, value, *, labels: str=''):
        numeric=float(value)
        if not math.isfinite(numeric) or numeric<0: raise ValueError('invalid numeric monitoring value')
        metrics.append((name,labels,numeric))

    for source in SOURCES:
        began=time.monotonic(); start=len(metrics)
        try:
            if source=='postgres':
                values=database_metrics(environment['OPS_MONITOR_DATABASE_URL'],PG_SQL)
                database_bytes=float(values['database_bytes'])
            elif source=='application': values=database_metrics(environment['OPS_APPLICATION_DATABASE_URL'],APP_SQL)
            elif source=='redis':
                client=redis.Redis.from_url(environment['OPS_REDIS_URL'],socket_connect_timeout=3,socket_timeout=3)
                try:
                    client.ping(); info=client.info()
                    values={'used_memory_bytes':info['used_memory'],'keyspace_hits_total':info['keyspace_hits'],
                            'keyspace_misses_total':info['keyspace_misses'],'evicted_keys_total':info['evicted_keys']}
                finally: client.close()
            elif source=='disk':
                disk=shutil.disk_usage(environment['OPS_DISK_PATH'])
                if database_bytes is None: raise ValueError('database size unavailable for capacity scenarios')
                values={'free_bytes':disk.free,'total_bytes':disk.total,'required_5x_bytes':database_bytes*5,'required_10x_bytes':database_bytes*10}
            else:
                for kind in ('wal','evidence','cold'):
                    values=spool_metrics(Path(environment['OPS_'+kind.upper()+'_SPOOL']))
                    for key,value in values.items(): add('mranked_ops_spool_'+key,value,labels='kind="'+kind+'"')
                values={}
            for key in NAMES.get(source,()): add('mranked_ops_'+key,values[key])
            add('mranked_ops_source_up',1,labels='source="'+source+'"')
        except Exception:
            # Discard partial source values. Error details can include DSNs;
            # only the bounded source enum becomes visible in monitoring.
            del metrics[start:]; success=False
            add('mranked_ops_source_up',0,labels='source="'+source+'"')
        add('mranked_ops_source_duration_seconds',time.monotonic()-began,labels='source="'+source+'"')
    add('mranked_ops_sample_unixtime',time.time())
    lines=[]; seen=set()
    for name,labels,value in metrics:
        if name not in seen:
            lines.append('# TYPE '+name+(' counter' if name.endswith('_total') else ' gauge'))
            seen.add(name)
        lines.append(name+('{'+labels+'}' if labels else '')+' '+format(value,'.12g'))
    return '\n'.join(lines)+'\n',success


def publish(path: Path, content: str):
    if not path.is_absolute() or not path.parent.is_dir() or path.is_symlink(): raise ValueError('provision an absolute regular textfile destination')
    descriptor,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as stream:
            os.fchmod(stream.fileno(),0o640); stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
    finally: Path(name).unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    content,success=sample(dict(os.environ)); publish(args.output,content)
    raise SystemExit(0 if success else 1)


if __name__=='__main__': main()
