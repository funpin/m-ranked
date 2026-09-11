"""Run the existing resumable bridge with a host-disk reserve before each commit batch."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import signal

from migration.bridge.cli import main
from migration.bridge.target import PostgresTarget


def stop(signum, frame):
    raise RuntimeError('Migration stopped by operator; committed checkpoints retained')


original_transaction = PostgresTarget.transaction


@contextmanager
def guarded_transaction(self):
    reserve = int(os.environ.get('MRANKED_MIGRATION_RESERVE_BYTES', str(3 * 1024**3)))
    source = Path(os.environ['MRANKED_MIGRATION_DISK_PATH'])
    if shutil.disk_usage(source).free < reserve:
        raise RuntimeError('Migration paused at disk reserve; committed checkpoints retained')
    with original_transaction(self):
        yield


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    PostgresTarget.transaction = guarded_transaction
    raise SystemExit(main())
