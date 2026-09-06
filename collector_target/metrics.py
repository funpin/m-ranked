"""Bounded Prometheus textfile metrics; labels never contain accounts or errors."""
from __future__ import annotations
from collections import defaultdict
import math
import os
from pathlib import Path
import tempfile
from threading import Lock
import time

from .model import Platform, RunStatus

BUCKETS = (.1,.5,1,2,5,10,30,60,120,300)


class CollectorMetrics:
    def __init__(self, output: Path | None = None):
        self.output=output
        self._lock=Lock()
        self._accounts=defaultdict(lambda:[0,0.,[0]*len(BUCKETS)])
        self._runs=defaultdict(int)
        self._snapshots=defaultdict(int)
        self._last_success=defaultdict(float)

    def account(self, platform: Platform, *, succeeded: bool, duration: float, snapshots: int = 0):
        if not math.isfinite(duration) or duration<0 or snapshots<0: raise ValueError('invalid metric observation')
        key=(Platform(platform).value,'succeeded' if succeeded else 'failed')
        with self._lock:
            counters=self._accounts[key]
            self._last_success.setdefault(key[0],0.)
            counters[0]+=1; counters[1]+=duration
            for i,bound in enumerate(BUCKETS): counters[2][i]+=int(duration<=bound)
            self._snapshots[key[0]]+=snapshots
            if succeeded: self._last_success[key[0]]=time.time()
            self._publish()

    def run(self, platform: Platform, status: RunStatus):
        with self._lock:
            self._runs[(Platform(platform).value,RunStatus(status).value)]+=1
            self._last_success.setdefault(Platform(platform).value,0.)
            self._publish()

    def render(self) -> str:
        with self._lock: return self._render()

    def _render(self) -> str:
        lines=['# HELP mranked_collector_account_duration_seconds Account collection latency.',
               '# TYPE mranked_collector_account_duration_seconds histogram']
        for (platform,outcome),(count,total,buckets) in sorted(self._accounts.items()):
            labels=f'platform="{platform}",outcome="{outcome}"'
            for bound,value in zip(BUCKETS,buckets):
                lines.append(f'mranked_collector_account_duration_seconds_bucket{{{labels},le="{bound:g}"}} {value}')
            lines += [f'mranked_collector_account_duration_seconds_bucket{{{labels},le="+Inf"}} {count}',
                      f'mranked_collector_account_duration_seconds_count{{{labels}}} {count}',
                      f'mranked_collector_account_duration_seconds_sum{{{labels}}} {total:.9g}']
        lines += ['# TYPE mranked_collector_runs_total counter']
        for (platform,status),count in sorted(self._runs.items()):
            lines.append(f'mranked_collector_runs_total{{platform="{platform}",status="{status}"}} {count}')
        lines += ['# TYPE mranked_collector_snapshots_total counter']
        for platform,count in sorted(self._snapshots.items()):
            lines.append(f'mranked_collector_snapshots_total{{platform="{platform}"}} {count}')
        lines += ['# TYPE mranked_collector_last_success_unixtime gauge']
        for platform,value in sorted(self._last_success.items()):
            lines.append(f'mranked_collector_last_success_unixtime{{platform="{platform}"}} {value:.6f}')
        return '\n'.join(lines)+'\n'

    def _publish(self):
        if self.output is None: return
        if not self.output.is_absolute() or self.output.is_symlink() or not self.output.parent.is_dir():
            raise ValueError('metrics file must have a provisioned absolute parent')
        descriptor,name=tempfile.mkstemp(prefix='.'+self.output.name,dir=self.output.parent)
        try:
            with os.fdopen(descriptor,'w') as stream:
                stream.write(self._render()); stream.flush(); os.fchmod(stream.fileno(),0o640); os.fsync(stream.fileno())
            os.replace(name,self.output)
        finally:
            Path(name).unlink(missing_ok=True)
