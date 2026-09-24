#!/usr/bin/env python3
"""Write a dump with an enforced size cap, live free-space reserve and rate cap.

The optional fourth argument caps the average throughput in bytes per second.
Reading slower makes pg_dump block on its pipe and the server-side COPY wait
with it, which is what keeps a nightly dump from starving ingestion.
"""
import os
from pathlib import Path
import shutil
import sys
import time

path = Path(sys.argv[1])
maximum, reserve = map(int, sys.argv[2:4])
rate = int(sys.argv[4]) if len(sys.argv) > 4 else 0
if maximum <= 0 or reserve <= 0 or rate < 0:
    raise SystemExit('positive stream budgets required')
written = 0
started = time.monotonic()
# Exclusive create, never follow/overwrite an existing partial or symlink.
with path.open('xb') as output:
    while block := sys.stdin.buffer.read(1024 * 1024):
        usage = shutil.disk_usage(path.parent)
        if written + len(block) > maximum or usage.free < max(reserve, usage.total // 5) + len(block):
            raise SystemExit('dump stopped before consuming reserved disk space')
        output.write(block)
        written += len(block)
        if rate:
            ahead = written / rate - (time.monotonic() - started)
            if ahead > 0:
                time.sleep(ahead)
    output.flush()
    os.fsync(output.fileno())
