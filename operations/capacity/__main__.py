from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import shutil

import psycopg
from psycopg.rows import dict_row


INDEX_SQL = """
SELECT i.oid AS index_oid,n.nspname AS schema, i.relname AS name, t.relname AS table_name,
       pg_relation_size(i.oid) AS bytes, s.idx_scan,
       x.indisunique, x.indisprimary, x.indisvalid,
       EXISTS(SELECT 1 FROM pg_inherits p WHERE p.inhrelid=i.oid) AS attached,
       x.indkey::smallint[] AS columns,
       coalesce((SELECT jsonb_agg(c.conkey) FROM pg_constraint c
                 WHERE c.conrelid=t.oid AND c.contype='f'),'[]'::jsonb) AS foreign_keys
FROM pg_stat_user_indexes s JOIN pg_index x ON x.indexrelid=s.indexrelid
JOIN pg_class i ON i.oid=x.indexrelid JOIN pg_class t ON t.oid=x.indrelid
JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_am am ON am.oid=i.relam
WHERE n.nspname IN ('ingest','analytics') AND am.amname='btree' AND i.relkind='i'
ORDER BY pg_relation_size(i.oid) DESC
"""


def index_candidates(before: dict, after: dict) -> list[dict]:
    # Statistics from a restored copy, or across a restart/reset, are not proof
    # about production reads. Per-index resets between captures cannot be
    # detected here: the result still requires workload and reset-log review.
    for field in ('database', 'server', 'started_at', 'stats_reset'):
        if before[field] != after[field]:
            raise ValueError(f'incomparable statistics: {field} changed')
    elapsed = datetime.fromisoformat(after['captured_at']) - datetime.fromisoformat(before['captured_at'])
    if elapsed.total_seconds() < 5 * 86400:
        raise ValueError('at least five days of comparable statistics are required')
    previous = {(row['schema'], row['name']): row for row in before['indexes']}
    candidates = []
    protected = {'publication_latest_institution_platform_idx', 'publication_latest_account_idx'}
    for row in after['indexes']:
        old = previous.get((row['schema'], row['name']))
        if old is None or row['name'] in protected or row['index_oid'] != old['index_oid']:
            continue
        if any(row[key] or old[key] for key in ('attached', 'indisunique', 'indisprimary')):
            continue
        if not row['indisvalid'] or not old['indisvalid'] or row['idx_scan'] != 0 or old['idx_scan'] != 0:
            continue
        if row['columns'] != old['columns'] or row['table_name'] != old['table_name']:
            continue
        if any(row['columns'][:len(fk)] == fk for fk in row['foreign_keys']):
            continue
        # This is a review list, deliberately never executed as DROP commands.
        candidates.append(row)
    return candidates


def audit(connection) -> dict:
    metadata = connection.execute("""SELECT current_database() AS database,
        inet_server_addr()::text||':'||inet_server_port() AS server,
        pg_postmaster_start_time() AS started_at,stats_reset,
        current_timestamp AS captured_at,pg_database_size(current_database()) AS database_bytes
        FROM pg_stat_database WHERE datname=current_database()""").fetchone()
    metadata['settings'] = connection.execute("""SELECT name,setting,unit,source FROM pg_settings
        WHERE name IN ('shared_buffers','effective_cache_size','work_mem','max_wal_size',
        'min_wal_size','archive_mode','wal_keep_size','max_slot_wal_keep_size') ORDER BY name""").fetchall()
    metadata['relations'] = connection.execute("""SELECT n.nspname AS schema,c.relname AS name,
        pg_table_size(c.oid) AS heap_bytes,pg_indexes_size(c.oid) AS index_bytes
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('ingest','analytics') AND c.relkind='r'
        ORDER BY pg_total_relation_size(c.oid) DESC""").fetchall()
    metadata['indexes'] = connection.execute(INDEX_SQL).fetchall()
    metadata['column_widths'] = connection.execute("""SELECT tablename,attname,avg_width,null_frac,
        avg_width*(1-null_frac) AS estimated_bytes_per_row FROM pg_stats
        WHERE schemaname='ingest' AND tablename LIKE 'publication_metric_snapshot%'
          AND attname IN ('metric_evidence','metric_evidence_id','source_fingerprint',
                         'semantic_fingerprint','correction_reason') ORDER BY tablename,attname""").fetchall()
    return metadata


def compact(connection, args) -> None:
    if args.month.day != 1 or args.after < 0 or not 1 <= args.batch_size <= 10000 or args.batches < 1:
        raise ValueError('use a month boundary, nonnegative cursor and positive bounded batch size/count')
    # Serializes only competing maintenance runners; collectors continue normally.
    lock = 'capacity-evidence:' + args.month.isoformat()
    if not connection.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked', (lock,)).fetchone()['locked']:
        raise RuntimeError('another evidence compaction runner owns this month')
    cursor = args.after
    try:
        for _ in range(args.batches):
            free = shutil.disk_usage(args.capacity_path).free
            if free < args.min_free_bytes:
                raise RuntimeError('capacity reserve reached; resume from the last printed committed cursor')
            with connection.transaction():
                connection.execute("SET LOCAL statement_timeout='30s'")
                connection.execute("SET LOCAL lock_timeout='1s'")
                # REPEATABLE READ makes the comparison one snapshot. A later
                # commit below the cursor is handled by the final verification pass.
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                upper = connection.execute('''SELECT max(id) AS id FROM (
                    SELECT id FROM ingest.publication_metric_snapshot WHERE published_month=%s AND id>%s
                    ORDER BY id LIMIT %s) page''', (args.month, cursor, args.batch_size)).fetchone()['id']
                if upper is None:
                    break
                checksum_sql = '''SELECT count(*) AS count,
                    md5(string_agg(ops_and_admin.publication_archive_record(published_month,id),'|' ORDER BY id)) AS checksum
                    FROM ingest.publication_metric_snapshot WHERE published_month=%s AND id>%s AND id<=%s'''
                params = (args.month, cursor, upper)
                before = connection.execute(checksum_sql, params).fetchone()
                result = connection.execute('SELECT * FROM ops_and_admin.compact_metric_evidence_batch(%s,%s,%s)',
                                            (args.month, cursor, args.batch_size)).fetchone()
                after = connection.execute(checksum_sql, params).fetchone()
                if before != after or result['last_id'] != upper:
                    raise RuntimeError('logical archive checksum changed; this batch has been rolled back')
            cursor = result['last_id']
            print(json.dumps({'month': str(args.month), **result, 'free_bytes': free, 'committed': True}), flush=True)
        remaining = connection.execute('''SELECT count(*) AS count FROM ingest.publication_metric_snapshot
            WHERE published_month=%s AND metric_evidence IS NOT NULL AND pg_column_size(metric_evidence)>=256''',
                                       (args.month,)).fetchone()['count']
        print(json.dumps({'month': str(args.month), 'after': cursor, 'remaining': remaining,
                          'complete': remaining == 0, 'restart_from_zero_for_late_commits': remaining > 0}), flush=True)
    finally:
        connection.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (lock,))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('audit')
    compare = commands.add_parser('index-candidates')
    compare.add_argument('before', type=Path)
    compare.add_argument('after', type=Path)
    backfill = commands.add_parser('compact-evidence')
    backfill.add_argument('--month', required=True, type=date.fromisoformat)
    backfill.add_argument('--after', type=int, default=0)
    backfill.add_argument('--batch-size', type=int, default=1000)
    backfill.add_argument('--batches', type=int, default=1)
    backfill.add_argument('--capacity-path', required=True, type=Path,
                          help='directory on the actual PostgreSQL data/WAL filesystem on this host')
    backfill.add_argument('--min-free-bytes', type=int, default=5 * 1024**3)
    args = parser.parse_args()
    if args.command == 'index-candidates':
        print(json.dumps(index_candidates(json.loads(args.before.read_text()), json.loads(args.after.read_text())), indent=2))
        return
    if args.command == 'compact-evidence' and args.min_free_bytes <= 0:
        parser.error('--min-free-bytes must be positive')
    # Keep credentials out of argv and reports; libpq's PGPASSFILE is supported.
    with psycopg.connect(os.environ['CAPACITY_DATABASE_URL'], autocommit=True, row_factory=dict_row) as connection:
        if args.command == 'audit':
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                connection.execute("SET LOCAL statement_timeout='2min'")
                print(json.dumps(audit(connection), default=str, indent=2))
        else:
            if connection.execute('SELECT contract_id FROM ops_and_admin.schema_contract').fetchone()['contract_id'] != 'storage-publisher-final-2026-09-08-r4':
                raise RuntimeError('install the r4 capacity delta before backfilling')
            compact(connection, args)


if __name__ == '__main__':
    main()
