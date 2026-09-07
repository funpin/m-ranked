"""One-time production collector staging; run using the installed legacy Python.

Does not start writers or remove legacy state. Credentials stay on the host.
"""
from pathlib import Path
import grp
import os
import pwd
import shutil
import sqlite3
import subprocess
from dotenv import dotenv_values

SOURCE = Path('/srv/m-ranked-artifacts/alpha-v30-bridge-20260907-r5')
RELEASE = Path('/opt/m-ranked/releases/collectors-v30-20260907')
LEGACY = Path('/opt/telegram-reaction-monitor')
STATE = Path('/var/lib/m-ranked')
PLATFORMS = ('telegram', 'vk', 'max', 'rutube')

def run(*args):
    subprocess.run(args, check=True)

def directory(path, mode=0o755, uid=0, gid=0):
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    path.chmod(mode)

def write(path, value, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, 'w') as stream:
        stream.write(value)
    path.chmod(mode)

for group in ('m-ranked-collector', 'm-ranked-identity-readers'):
    try:
        grp.getgrnam(group)
    except KeyError:
        run('groupadd', '--system', group)
for name in ('m-ranked-build', *(f'm-ranked-collector-{p}' for p in PLATFORMS)):
    try:
        pwd.getpwnam(name)
    except KeyError:
        run('useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', name)
directory(RELEASE)
for name in ('app', 'collector_target', 'migration', 'operations'):
    if not (RELEASE / name).exists():
        shutil.copytree(SOURCE / name, RELEASE / name)
if not (RELEASE / '.venv').exists():
    shutil.copytree(LEGACY / '.venv', RELEASE / '.venv', symlinks=True)
    run('chown', '-R', 'm-ranked-build:m-ranked-build', str(RELEASE / '.venv'))

directory(STATE, 0o711)
directory(STATE / 'collectors', 0o755)
directory(STATE / 'identity-receipts')
directory(STATE / 'identity-receipts/collector')
reader_gid = grp.getgrnam('m-ranked-identity-readers').gr_gid
env = dotenv_values(LEGACY / '.env')
# Retain polling policy, but never copy admin/database credentials to collectors.
allowed = {
    'DATA_SOURCE', 'COMPLETE_HISTORY_MAX_FIRST_AGE_MINUTES', 'DISCOVERY_LIMIT',
    'DISCOVERY_OVERLAP', 'POLL_INTERVAL_MINUTES', 'TRACK_POST_FOR_HOURS',
    'RECENT_POST_HOURS', 'MEDIUM_POST_HOURS', 'MEDIUM_POLL_INTERVAL_MINUTES',
    'OLD_POLL_INTERVAL_MINUTES', 'SUBSCRIBER_REFRESH_HOURS', 'VK_API_VERSION',
    'SECOND_DAY_POLL_INTERVAL_MINUTES', 'THIRD_DAY_POLL_INTERVAL_MINUTES',
    'DAYS_4_TO_6_POLL_INTERVAL_MINUTES', 'DAYS_7_TO_13_POLL_INTERVAL_MINUTES',
    'DAY_14_PLUS_POLL_INTERVAL_MINUTES',
    'RUTUBE_FIRST_THREE_DAYS_POLL_INTERVAL_MINUTES',
    'RUTUBE_DAYS_4_TO_6_POLL_INTERVAL_MINUTES',
    'RUTUBE_DAYS_7_TO_13_POLL_INTERVAL_MINUTES',
    'RUTUBE_DAY_14_PLUS_POLL_INTERVAL_MINUTES',
}
common = {k: v for k, v in env.items() if k in allowed and v is not None}
common.setdefault('DAYS_7_TO_13_POLL_INTERVAL_MINUTES', '60')
common.setdefault('DAY_14_PLUS_POLL_INTERVAL_MINUTES', '60')
common.setdefault('RUTUBE_FIRST_THREE_DAYS_POLL_INTERVAL_MINUTES', '60')
common.setdefault('RUTUBE_DAYS_4_TO_6_POLL_INTERVAL_MINUTES', '180')
common.setdefault('RUTUBE_DAYS_7_TO_13_POLL_INTERVAL_MINUTES', '360')
common.setdefault('RUTUBE_DAY_14_PLUS_POLL_INTERVAL_MINUTES', '720')
common.update(COLLECTOR_DATABASE_URL='postgresql://collector_ingest@127.0.0.1:5432/mranked',
              COLLECTOR_VERSION='target-v30-20260907',
              MRANKED_IDENTITY_RECEIPT_DIR=str(STATE / 'identity-receipts'),
              TELEGRAM_WEB_CONCURRENCY='1', RUTUBE_REQUEST_CONCURRENCY='2',
              COLLECTOR_PERSIST_RAW_EVIDENCE='false',
              COLLECTOR_PERSIST_LEGACY_CSV='false')
assert all('\n' not in v and '"' not in v for v in common.values())
write(Path('/etc/m-ranked/collector-common.env'), ''.join(f'{k}="{v}"\n' for k, v in common.items()))

for platform in PLATFORMS:
    user = pwd.getpwnam(f'm-ranked-collector-{platform}')
    state = STATE / 'collectors' / platform
    directory(state, 0o700, user.pw_uid, user.pw_gid)
    directory(state / 'raw-evidence', 0o700, user.pw_uid, user.pw_gid)
    directory(STATE / 'identity-receipts/collector' / platform, 0o2750, user.pw_uid, reader_gid)
    keys = {'telegram': ('TELEGRAM_API_ID', 'TELEGRAM_API_HASH') if env.get('DATA_SOURCE') == 'mtproto' else (),
            'vk': ('VK_ACCESS_TOKEN',), 'max': ('MAX_USER_PHONE',), 'rutube': ()}[platform]
    auth = {k: env[k] for k in keys}
    assert all(v and '\n' not in v for v in auth.values())
    write(Path(f'/etc/m-ranked/credentials/collector-{platform}-auth.env'), ''.join(f'{k}={v}\n' for k, v in auth.items()))
    write(Path(f'/etc/m-ranked/collector-{platform}.env'),
          f'COLLECTOR_RAW_EVIDENCE_DIR={state}/raw-evidence\nCOLLECTOR_METRICS_FILE={state}/metrics.prom\n')
    if platform == 'max':
        destination = state / 'max.session.db'
        if not destination.exists():
            original = Path(env['MAX_SESSION_PATH'])
            with sqlite3.connect(original.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(destination) as dst:
                src.backup(dst)
                assert dst.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            os.chown(destination, user.pw_uid, user.pw_gid)
            destination.chmod(0o600)
    if platform == 'telegram':
        destination = state / 'telegram-web-profile'
        if env.get('DATA_SOURCE') == 'telegram_web' and not destination.exists():
            shutil.copytree(Path(env['TELEGRAM_WEB_PROFILE_PATH']), destination,
                            ignore=shutil.ignore_patterns('Singleton*', 'LOCK', 'lockfile', 'DevToolsActivePort'))
            directory(destination, 0o700, user.pw_uid, user.pw_gid)
            run('chown', '-R', f'{user.pw_name}:{user.pw_name}', str(destination))
        if env.get('DATA_SOURCE') == 'mtproto':
            raise RuntimeError('MTProto requires explicit session preparation')

# Browser executables are a target runtime dependency and get an independent path.
browser = Path('/opt/m-ranked/browser-runtime')
if not browser.exists():
    shutil.copytree(Path(env['PLAYWRIGHT_BROWSERS_PATH']), browser, symlinks=True)
    run('chown', '-R', 'root:root', str(browser))
with Path('/etc/m-ranked/collector-telegram.env').open('a') as stream:
    stream.write(f'PLAYWRIGHT_BROWSERS_PATH={browser}\n')
print('Collector source, isolated states and credential files staged; no writers started.')
