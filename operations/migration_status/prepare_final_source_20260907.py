"""Build a verified final source from stopped SQLite plus disappeared S0 rows.

Existing final values win. Missing historical records come exclusively from
the byte-verified original S0, never from PostgreSQL or invented values.
"""
from pathlib import Path
import hashlib
import json
import os
import pwd
import shutil
import sqlite3
import subprocess

live = Path('/opt/telegram-reaction-monitor/data/reactions.db')
prior = Path('/opt/telegram-reaction-monitor/data/backups/cutover-20260906/reactions-20260906T172657Z.db')
destination = Path('/var/lib/m-ranked/catchup-20260907/final.sqlite')
receipt = Path('/var/lib/m-ranked-migration-status/final-live-sqlite-20260907.json')
expected = json.loads(receipt.read_text())
def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

if not Path('/var/lib/m-ranked').exists():
    print('Skipping legacy service checks: /var/lib/m-ranked not yet available', flush=True)
assert not destination.exists(), 'Refusing to overwrite an existing final source'
assert shutil.disk_usage(live).free - live.stat().st_size > 3 * 1024**3
assert digest(live) == expected['sha256']
assert digest(prior) == '4061e900f6f2700498795e39d8fa70a076a9f191e3c30b143cb455371c26f80e'
destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
temporary = destination.with_suffix('.building')
assert not temporary.exists()
restored = {}
with sqlite3.connect(live.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(temporary) as dst:
    src.backup(dst, pages=4096)
    dst.execute('PRAGMA journal_mode=DELETE')
    dst.execute('PRAGMA foreign_keys=ON')
    dst.execute('ATTACH DATABASE ? AS original', (prior.as_uri() + '?mode=ro&immutable=1',))
    tables = ('schema_migrations', 'app_state', 'institutions', 'platform_accounts',
              'channels', 'platform_posts', 'posts', 'post_messages',
              'platform_snapshots', 'reaction_snapshots')
    for table in tables:
        columns = dst.execute(f'PRAGMA main.table_info("{table}")').fetchall()
        assert columns == dst.execute(f'PRAGMA original.table_info("{table}")').fetchall()
        pk = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        assert pk, table
        where = ' AND '.join(f'current."{key}"=old."{key}"' for key in pk)
        names = ','.join(f'"{row[1]}"' for row in columns)
        old_names = ','.join(f'old."{row[1]}"' for row in columns)
        before = dst.total_changes
        dst.execute(f'INSERT INTO main."{table}" ({names}) SELECT {old_names} '
                    f'FROM original."{table}" old WHERE NOT EXISTS '
                    f'(SELECT 1 FROM main."{table}" current WHERE {where})')
        restored[table] = dst.total_changes - before
        print(table, 'restored', restored[table], flush=True)
    dst.commit()
    assert dst.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    assert not dst.execute('PRAGMA foreign_key_check').fetchmany(1)
assert digest(live) == expected['sha256'], 'Stopped source changed while preparing final input'
temporary.replace(destination)
owner = pwd.getpwnam('m-ranked-migration')
os.chown(destination.parent, owner.pw_uid, owner.pw_gid)
os.chown(destination, owner.pw_uid, owner.pw_gid)
destination.chmod(0o400)
result = {'source': str(destination), 'sha256': digest(destination),
          'bytes': destination.stat().st_size, 'liveSourceSha256': expected['sha256'],
          'priorSourceSha256': digest(prior), 'restoredMissingRows': restored}
Path('/var/lib/m-ranked-migration-status/final-source-20260907.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result), flush=True)
