"""Publish aggregate progress for one exact source snapshot and import batch.

No database credentials, source paths, account IDs or error text reach the public
JSON. Run with --once, or as a service; the private control JSON is reread each
cycle. MRANKED_PROGRESS_DATABASE_URL and PGPASSFILE are private environment values.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
import time
import urllib.request

STREAMS = ('schema_migrations', 'app_state', 'institutions', 'platform_accounts',
           'channels', 'platform_posts', 'posts', 'post_messages',
           'platform_snapshots', 'reaction_snapshots')
PHASES = {'preparing', 'importing', 'catch_up', 'verifying', 'blocked', 'complete'}
class TransferEstimate:
    def __init__(self):
        self.reset()

    def reset(self):
        self.batch_id = None
        self.samples = deque()
        self.smoothed_speed = None
        self.last_estimate_at = None
        self.last_progress_at = None

    def update(self, batch_id, processed, total, now):
        if self.batch_id != batch_id or (self.samples and processed < self.samples[-1][1]):
            self.batch_id = batch_id
            self.samples.clear()
            self.smoothed_speed = None
            self.last_estimate_at = None
            self.last_progress_at = now
        if not self.samples or processed > self.samples[-1][1]:
            self.last_progress_at = now
        self.samples.append((now, processed))
        while len(self.samples) > 1 and self.samples[1][0] <= now - 600:
            self.samples.popleft()
        elapsed = now - self.samples[0][0]
        transferred = processed - self.samples[0][1]
        if now - self.last_progress_at >= 60:
            # A stopped/restarted importer has a different rate. Do not let
            # its downtime contaminate the next transfer window.
            self.reset()
            return None, None
        if elapsed < 60 or transferred <= 0 or processed >= total:
            self.smoothed_speed = None
            self.last_estimate_at = None
            return None, None
        speed = transferred / elapsed
        # Ease changes in the rate. Never clamp the ETA downward: sustained
        # slowdowns must still increase it; stalled imports lose the timer.
        if self.smoothed_speed is None:
            self.smoothed_speed = speed
        else:
            weight = -math.expm1(-max(0, now - self.last_estimate_at) / 120)
            self.smoothed_speed += weight * (speed - self.smoothed_speed)
        self.last_estimate_at = now
        return (math.ceil((total - processed) / self.smoothed_speed),
                round(self.smoothed_speed, 1))


def _database_stats(db_connection):
    rows = db_connection.execute(
        "SELECT COALESCE(SUM(n_live_tup), 0) FROM pg_stat_user_tables"
    ).fetchone()[0]
    db_size = db_connection.execute('SELECT pg_database_size(current_database())').fetchone()[0]
    return int(rows), round(db_size / (1024 ** 3), 2)


def build_status(control: dict, inventory: dict, estimate=None) -> dict:
    if control['phase'] not in PHASES:
        raise ValueError('Invalid phase')
    if inventory['quick_check'] != ['ok'] or inventory['foreign_key_violations'] != 0:
        raise ValueError('Unverified snapshot')
    totals = {name: inventory['tables'][name]['count'] for name in STREAMS}
    if any(type(value) is not int or value < 0 for value in totals.values()):
        raise ValueError('Invalid inventory')
    processed = 0
    previously_transferred = None
    delta_transferred = None
    database_rows = None
    database_size_gib = None
    eta_seconds = speed = None
    batch_id = control.get('batchId')
    if batch_id:
        import psycopg
        with psycopg.connect(os.environ['MRANKED_PROGRESS_DATABASE_URL'],
                             connect_timeout=5, options='-c statement_timeout=5000') as db:
            db.execute('SET TRANSACTION READ ONLY')
            batch = db.execute(
                'SELECT source_name,source_sha256,dry_run,status::text '
                'FROM migration.import_batch WHERE id=%s', (batch_id,)).fetchone()
            if not batch or batch[:3] != (control['sourceNamespace'], inventory['sha256'], False):
                raise ValueError('Batch does not match source')
            counts = db.execute(
                'SELECT stream_name,source_table,rows_processed FROM migration.checkpoint '
                'WHERE batch_id=%s', (batch_id,)).fetchall()
            for stream, source_table, count in counts:
                if stream not in totals or source_table != stream or not 0 <= count <= totals[stream]:
                    raise ValueError('Invalid checkpoint')
                processed += count
            if control.get('baselineBatchId'):
                baseline = db.execute(
                    'SELECT source_name,source_sha256,dry_run,status::text '
                    'FROM migration.import_batch WHERE id=%s',
                    (control['baselineBatchId'],)).fetchone()
                if (not baseline or baseline[:3] !=
                        (control['sourceNamespace'], control['baselineSha256'], False)
                        or control['baselineBatchId'] == batch_id):
                    raise ValueError('Invalid baseline binding')
                baseline_counts = db.execute(
                    'SELECT stream_name,source_table,rows_processed,completed '
                    'FROM migration.checkpoint WHERE batch_id=%s',
                    (control['baselineBatchId'],)).fetchall()
                if (len(baseline_counts) != len(STREAMS)
                        or {row[0] for row in baseline_counts} != set(STREAMS)
                        or any(table != stream or not completed or not 0 <= count <= totals[stream]
                               for stream, table, count, completed in baseline_counts)):
                    raise ValueError('Incomplete baseline transfer')
                previously_transferred = sum(row[2] for row in baseline_counts)
                if control.get('deltaCounter'):
                    delta_counts = db.execute(
                        'SELECT source_table,rows_added FROM migration.final_delta_progress_20260907 '
                        'WHERE batch_id=%s', (batch_id,)).fetchall()
                    baseline_totals = {row[0]: row[2] for row in baseline_counts}
                    if (len({row[0] for row in delta_counts}) != len(delta_counts)
                            or any(table not in totals or type(count) is not int
                                   or not 0 <= count <= totals[table] - baseline_totals[table]
                                   for table, count in delta_counts)):
                        raise ValueError('Invalid delta counts')
                    delta_transferred = sum(row[1] for row in delta_counts)
            if batch[3] in {'failed', 'cancelled'}:
                control = dict(control, phase='blocked', message='Перенос приостановлен. Проверяем данные перед продолжением.')
            if estimate is not None and previously_transferred is None and control['phase'] in {'importing', 'catch_up'} and batch[3] == 'running':
                eta_seconds, speed = estimate.update(batch_id, processed, sum(totals.values()),
                                                    time.time())
            elif estimate is not None:
                estimate.reset()
            if control['phase'] == 'complete':
                raise ValueError('Final acceptance must be published by the verified cutover workflow')
            database_rows, database_size_gib = _database_stats(db)
    elif control['phase'] not in {'preparing', 'blocked'}:
        raise ValueError('Active transfer requires exact batch binding')
    elif estimate is not None:
        estimate.reset()
    collection = control.get('collectionMessage', 'Проверяем состояние сбора новых данных.')
    try:
        with urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=3) as response:
            health = json.load(response)
        if not control.get('collectionMessage') and health.get('collector_fresh') is True:
            collection = 'Сбор данных продолжается в действующей версии сервиса.'
    except (OSError, ValueError):
        pass
    return {'phase': control['phase'], 'message': control['message'],
            'total': sum(totals.values()),
            'transferred': processed if delta_transferred is None else previously_transferred + delta_transferred,
            'passProcessed': processed, 'deltaTransferred': delta_transferred,
            'databaseRows': database_rows, 'diskUsageGiB': database_size_gib,
            'counterKind': 'delta' if delta_transferred is not None else ('final_pass' if previously_transferred is not None else 'transfer'),
            'previouslyTransferred': previously_transferred,
            'updatedAt': datetime.now(timezone.utc).isoformat(),
            'progressAvailable': True, 'collectionMessage': collection,
            'estimatedRemainingSeconds': eta_seconds, 'rowsPerSecond': speed}


def atomic_write(path: Path, payload: dict) -> None:
    handle, temporary = tempfile.mkstemp(prefix='.status-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w') as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    estimate = TransferEstimate()
    while True:
        try:
            control = json.loads(args.control.read_text())
            inventory = json.loads(Path(control['inventoryPath']).read_text())
            atomic_write(args.output, build_status(control, inventory, estimate))
        except Exception as error:
            estimate.reset()
            # Keep last confirmed counts and their original timestamp on failure.
            if args.output.exists():
                previous = json.loads(args.output.read_text())
                previous['progressAvailable'] = False
                previous['estimatedRemainingSeconds'] = None
                previous['rowsPerSecond'] = None
                previous['message'] = previous['message'].partition(' Ориентировочно осталось ')[0]
                atomic_write(args.output, previous)
            print('Progress unavailable: ' + type(error).__name__, flush=True)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            return
        time.sleep(10)


if __name__ == '__main__':
    main()
