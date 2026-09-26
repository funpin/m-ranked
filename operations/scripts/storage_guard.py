#!/usr/bin/env python3
"""Bounded host observations and admission checks; never deletes data."""
from __future__ import annotations
import argparse
import json
from itertools import islice
import os
from pathlib import Path
import shutil
import tempfile
import time


def atomic(path: Path, data: str, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".storage-", dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def sample(path):
    usage = shutil.disk_usage(path)
    fs = os.statvfs(path)
    return dict(at=time.time(), total=usage.total, free=usage.free,
                inodes=fs.f_files, free_inodes=fs.f_favail)


def growth(samples, hours):
    last = samples[-1]
    prior = [s for s in samples if s['at'] <= last['at'] - hours * 3600]
    if not prior:
        return None
    first = prior[-1]
    return (first['free'] - last['free']) / (last['at'] - first['at'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['check', 'observe'])
    parser.add_argument('--path', default=os.environ.get('MRANKED_STORAGE_PATH', '/var/lib/m-ranked'))
    parser.add_argument('--peak-bytes', type=int, default=0)
    parser.add_argument('--reserve-bytes', type=int, default=0)
    parser.add_argument('--backup-dir', type=Path, default=Path('/var/backups/m-ranked'))
    parser.add_argument('--state', type=Path, default=Path('/var/lib/m-ranked/storage-guard/history.json'))
    parser.add_argument('--metrics', type=Path, default=Path('/var/lib/node_exporter/textfile_collector/mranked_storage.prom'))
    args = parser.parse_args()
    if min(args.peak_bytes, args.reserve_bytes) < 0:
        parser.error('negative budget')
    point = sample(args.path)
    reserve = max(args.reserve_bytes, point['total'] // 5)
    allowed = point['free'] >= reserve + args.peak_bytes and (point['inodes'] == 0 or point['free_inodes'] > point['inodes'] // 10)
    print(json.dumps(dict(**point, peak_bytes=args.peak_bytes, reserve_bytes=reserve, allowed=allowed)))
    if args.mode == 'check':
        return 0 if allowed else 75
    history = json.loads(args.state.read_text()) if args.state.exists() else []
    history = [s for s in history if point['at'] - 49 * 3600 <= s['at'] < point['at'] and s['total'] == point['total']][-599:]
    history.append(point)
    atomic(args.state, json.dumps(history))
    metrics = {f'mranked_storage_{key}':value for key,value in point.items()}
    metrics['mranked_storage_operation_peak_bytes'] = args.peak_bytes
    metrics['mranked_storage_after_peak_free_bytes'] = point['free']-args.peak_bytes
    metrics['mranked_storage_heavy_job_allowed'] = int(allowed)
    for hours in [6,24]:
        rate = growth(history, hours)
        metrics[f'mranked_storage_growth_{hours}h_available'] = int(rate is not None)
        if rate is not None:
            metrics[f'mranked_storage_growth_{hours}h_bytes_per_second'] = rate
            if rate > 0:
                metrics[f'mranked_storage_reserve_eta_{hours}h_seconds'] = max(0,point['free']-reserve-args.peak_bytes)/rate
    # stat only; never read/hash dumps in the frequent observer.
    try:
        dumps = list(islice(args.backup_dir.glob('mranked-*.dump'), 1001)) if args.backup_dir.is_dir() else []
        sizes = [p.stat() for p in dumps[:1000] if p.is_file() and not p.is_symlink()]
        metrics['mranked_storage_backup_source_up'] = 1
        metrics['mranked_storage_backup_inventory_truncated'] = int(len(dumps) > 1000)
    except OSError:
        sizes = []
        metrics['mranked_storage_backup_source_up'] = 0
    metrics['mranked_storage_backup_allocated_bytes'] = sum(st.st_blocks * 512 for st in sizes)
    metrics['mranked_storage_backup_files'] = len(sizes)
    metrics['mranked_storage_backup_last_complete_unixtime'] = max((st.st_mtime for st in sizes), default=0)
    # node-exporter reads this as a separate, unprivileged service account.
    atomic(args.metrics, ''.join(f'{key} {value}\n' for key,value in metrics.items()), 0o644)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
