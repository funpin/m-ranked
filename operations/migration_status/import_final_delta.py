"""Load only the explicitly requested final SQLite tail; never scan old rows.

The user waived historical revalidation. Original checkpoints are not rewritten.
Each new-row batch is checked against canonical metrics and checkpointed in its
own transaction. Existing native collectors may continue writing independently.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
from uuid import UUID

from psycopg.errors import DeadlockDetected

from migration.bridge.model import row_hash, stable_uuid
from migration.bridge.source import LegacySource
from migration.bridge.service import BridgeService
from migration.bridge.target import PostgresTarget
from migration.bridge.export_lexemes import preserve_export_lexemes

BATCH = UUID('1fbb7597-18c3-595c-b6b6-582fee82a158')
BASELINE = UUID('e832c733-8416-5f15-8649-b11405e49528')
NAMESPACE = 'm-ranked-production'
NAMESPACE_ID = UUID('b6770d25-ad0e-5319-b41d-cf0e1315635d')
SOURCE_SHA = 'b670a51a72194641fad06912ea07baf8c7937571801c5be8f0cb2f0332de2b79'
SOURCE = Path('/source/final.sqlite')
EXPECTED = {'platform_snapshots': 193156, 'reaction_snapshots': 53403}


class DeltaWriter:
    def __init__(self, target, source_time):
        self.target = target
        self.options = SimpleNamespace(source_namespace=NAMESPACE)
        self.source_namespace_uuid = NAMESPACE_ID
        self.batch_id = BATCH
        self.source_snapshot_at = source_time

    def publication_uuid(self, table, key):
        return BridgeService._publication_uuid(self, table, key)

    def persist(self, table, row, publication, published_at, run):
        return BridgeService._import_snapshot(self, table, row, publication, published_at, run)


def verify_new_rows(target, table, rows, publications):
    actual = target.fetchall('''SELECT m.source_pk,m.source_row_hash,
        s.publication_id,s.observed_at,s.age_seconds,s.sampling_bucket,
        s.views_count,s.reactions_count,s.comments_count,s.shares_count,
        s.interval_uncertain,s.synthetic,
        COALESCE((SELECT jsonb_object_agg(r.reaction_key,r.reaction_count)
            FROM ingest.reaction_breakdown r WHERE r.snapshot_published_month=s.published_month
                AND r.snapshot_id=s.id),'{}'::jsonb)
        FROM migration.legacy_identity_map m
        JOIN ingest.publication_metric_snapshot s ON s.id=m.target_bigint
            AND s.published_month=(m.natural_key->>'published_month')::date
        WHERE m.source_namespace=%s AND m.source_table=%s AND m.source_pk=ANY(%s)
            AND m.target_type='publication_metric_snapshot' AND m.last_seen_batch_id=%s''',
        (NAMESPACE_ID, table, [str(r['id']) for r in rows], BATCH))
    by_key = {a[0]: a for a in actual}
    if len(actual) != len(rows) or len(by_key) != len(rows):
        raise RuntimeError('Delta canonical coverage mismatch')
    for row, publication in zip(rows, publications, strict=True):
        instant = datetime.fromisoformat(str(row['measured_at']).replace('Z', '+00:00'))
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        telegram = table == 'reaction_snapshots'
        raw = json.loads(row.get('raw_json') or '{}') if not telegram else {}
        reactions = json.loads(row.get('reactions_json') or '{}') if telegram else ((raw.get('reaction_breakdown', {}) or {}) if isinstance(raw, dict) else {})
        expected = (str(row['id']), row_hash({k:v for k,v in row.items() if not k.startswith('__')}),
                    publication, instant, row['age_seconds'], row['measurement_bucket'],
                    row.get('views_count'), row.get('total_reactions' if telegram else 'reactions_count'),
                    row.get('comments_count'), None if telegram else row.get('shares_count'),
                    bool(row.get('interval_uncertain')) if telegram else False,
                    bool(row.get('synthetic')) if telegram else False, reactions)
        if tuple(by_key[str(row['id'])]) != expected:
            raise RuntimeError('Delta canonical metric mismatch: '+table+'/'+str(row['id']))


def main():
    source = LegacySource(SOURCE)
    if SOURCE.is_symlink() or SOURCE.stat().st_size != 1934426112:
        raise RuntimeError('Unexpected final source file')
    with PostgresTarget(os.environ['BRIDGE_DATABASE_URL']) as target:
        batch = target.fetchone('''SELECT source_name,source_sha256,source_snapshot_at
            FROM migration.import_batch WHERE id=%s AND NOT dry_run''', (BATCH,))
        if not batch or batch[:2] != (NAMESPACE, SOURCE_SHA):
            raise RuntimeError('Final batch binding mismatch')
        bounds = {}
        import sqlite3
        with sqlite3.connect(SOURCE.as_uri()+'?mode=ro', uri=True) as db:
            for table, expected in EXPECTED.items():
                old = target.fetchone('''SELECT last_sequence,completed FROM migration.checkpoint
                    WHERE batch_id=%s AND stream_name=%s''', (BASELINE,table))
                if not old or not old[1]:
                    raise RuntimeError('Original stream was not completely loaded')
                count, high = db.execute('SELECT count(*),max(rowid) FROM '+table+' WHERE rowid>?', (old[0],)).fetchone()
                if count != expected:
                    raise RuntimeError('Final tail count mismatch for '+table)
                bounds[table] = (old[0], high)
        writer = DeltaWriter(target, batch[2])
        with target.transaction():
            target.execute('''UPDATE migration.import_batch SET status='running',error_summary=NULL,
                metadata=metadata || %s::jsonb WHERE id=%s''',
                (json.dumps({'executionMode':'delta_only','validationScope':'new_rows_only',
                             'historicalRevalidation':'explicitly_waived_by_user','deltaExpected':EXPECTED}),BATCH))
        for table, expected in EXPECTED.items():
            checkpoint = target.fetchone('''SELECT last_rowid,rows_processed,completed
                FROM migration.final_delta_checkpoint_20260907 WHERE batch_id=%s AND source_table=%s''', (BATCH,table))
            after, processed, completed = checkpoint or (bounds[table][0],0,False)
            if completed:
                if processed != expected: raise RuntimeError('Invalid completed delta checkpoint')
                continue
            publication_table = 'platform_posts' if table == 'platform_snapshots' else 'posts'
            publication_key = 'platform_post_id' if table == 'platform_snapshots' else 'post_id'
            for rows in source.iter_rows(table,after_rowid=after,batch_size=1000):
                if shutil.disk_usage('/work').free < 3*1024**3:
                    raise RuntimeError('Delta paused at disk reserve')
                aliases={key:writer.publication_uuid(publication_table,key)
                         for key in {int(row[publication_key]) for row in rows}}
                publications=[aliases[int(row[publication_key])] for row in rows]
                contexts=target.publication_contexts(publications)
                with target.transaction():
                    for month in {contexts[p][0].replace(day=1,hour=0,minute=0,second=0,microsecond=0) for p in publications}:
                        target.ensure_partition(month)
                    for row,publication in zip(rows,publications,strict=True):
                        published_at,platform=contexts[publication]
                        run=stable_uuid(NAMESPACE,'migration_collection_run',{'batch_id':str(BATCH),'platform':platform})
                        writer.persist(table,row,publication,published_at,run)
                        preserve_export_lexemes(target,NAMESPACE_ID,table,row)
                    verify_new_rows(target,table,rows,publications)
                    processed += len(rows)
                    after = int(rows[-1]['__source_rowid'])
                    if processed > expected or after > bounds[table][1]:
                        raise RuntimeError('Delta exceeded fixed source boundary')
                    target.record_revision(BATCH,None,'delta:'+table,['publications','analytics','overview','comparison'])
                    target.execute('''INSERT INTO migration.final_delta_checkpoint_20260907
                        (batch_id,source_table,last_rowid,rows_processed,completed)
                        VALUES(%s,%s,%s,%s,%s) ON CONFLICT(batch_id,source_table)
                        DO UPDATE SET last_rowid=excluded.last_rowid,rows_processed=excluded.rows_processed,
                            completed=excluded.completed,updated_at=transaction_timestamp()''',
                        (BATCH,table,after,processed,processed==expected))
                print(f'{table}: {processed}/{expected} new rows committed and verified',flush=True)
            if processed != expected:
                raise RuntimeError('Delta source ended before expected count')
        with target.transaction():
            target.finish_batch(BATCH,status='succeeded',rows_read=sum(EXPECTED.values()),
                                rows_written=sum(EXPECTED.values()),error_summary=None)
        report={'status':'delta_loaded_and_verified','newRows':sum(EXPECTED.values()),
                'tables':EXPECTED,'historicalRevalidation':'waived_by_user',
                'fullHistoricalGatePassed':False,'projectionRebuild':'pending',
                'completedAt':datetime.now(timezone.utc).isoformat()}
        Path('/work/delta-only-result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)


if __name__ == '__main__':
    while True:
        try:
            main()
            break
        except DeadlockDetected:
            # The failed transaction rolled back both rows and its checkpoint.
            # Reopen the connection and resume only the uncommitted tail.
            print('Concurrent writer deadlock; resuming from committed delta checkpoint in 5 seconds', flush=True)
            time.sleep(5)
