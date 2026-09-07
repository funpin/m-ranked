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
original_enter = PostgresTarget.__enter__


def configured_enter(self):
    timeout = int(os.environ.get('MRANKED_MIGRATION_STATEMENT_TIMEOUT_SECONDS', '300'))
    if not 300 <= timeout <= 1800:
        raise ValueError('Migration statement timeout must be between 300 and 1800 seconds')
    result = original_enter(self)
    try:
        self.connection.execute("SELECT set_config('statement_timeout', %s, false)", (f'{timeout}s',))
    except Exception:
        self.connection.close()
        self.connection = None
        raise
    return result


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
    PostgresTarget.__enter__ = configured_enter
    raise SystemExit(main())
