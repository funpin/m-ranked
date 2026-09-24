#!/usr/bin/env python3
"""Write a dump with an enforced size cap and live free-space reserve."""
import os
from pathlib import Path
import shutil
import sys

path = Path(sys.argv[1])
maximum, reserve = map(int, sys.argv[2:4])
if maximum <= 0 or reserve <= 0:
    raise SystemExit('positive stream budgets required')
written = 0
# Exclusive create, never follow/overwrite an existing partial or symlink.
with path.open('xb') as output:
    while block := sys.stdin.buffer.read(1024 * 1024):
        usage = shutil.disk_usage(path.parent)
        if written + len(block) > maximum or usage.free < max(reserve, usage.total // 5) + len(block):
            raise SystemExit('dump stopped before consuming reserved disk space')
        output.write(block)
        written += len(block)
    output.flush()
    os.fsync(output.fileno())
