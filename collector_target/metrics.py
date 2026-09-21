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
        self._phase_wait=defaultdict(float)
        self._phase_attempts=defaultdict(int)
        self._phase_results=defaultdict(int)
        self._cycle_duration=defaultdict(float)
        self._schedule_lag=defaultdict(float)
        self._overruns=defaultdict(int)
        self._coalesced=defaultdict(int)
        self._resumes=defaultdict(int)
        self._request_timeouts=defaultdict(int)
        self._shutdowns=defaultdict(int)
        self._provider_errors=defaultdict(int)
        self._schedule_modes: dict[str, str] = {}
        self._deployment_profiles: dict[str, str] = {}
        self._working_set: dict[str, float] = {}
        self._disk: dict[str, float] = {}
        self._transfer: dict[str, dict[str, float]] = {}

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

    def phase_wait(
        self, platform: Platform, *, result: str, duration: float, attempts: int,
    ) -> None:
        if not math.isfinite(duration) or duration < 0 or attempts < 0:
            raise ValueError("invalid phase metric observation")
        name = Platform(platform).value
        with self._lock:
            self._phase_wait[name] += duration
            self._phase_attempts[name] += attempts
            self._phase_results[(name, result)] += 1
            self._publish()

    def deployment_profile(self, platform: Platform, profile: str) -> None:
        normalized = str(profile).strip().lower()
        if normalized not in {"a", "b"}:
            raise ValueError('deployment profile must be a or b')
        with self._lock:
            self._deployment_profiles[Platform(platform).value] = normalized
            self._publish()

    def working_set(self, *, released_months: int, deferred_months: int,
                    oldest_retained_month=None) -> None:
        if released_months < 0 or deferred_months < 0:
            raise ValueError('invalid working set observation')
        with self._lock:
            self._working_set['released_months_total'] = (
                self._working_set.get('released_months_total', 0.0) + released_months
            )
            self._working_set['deferred_months'] = float(deferred_months)
            if oldest_retained_month is not None:
                from datetime import datetime, timezone
                moment = datetime(
                    oldest_retained_month.year, oldest_retained_month.month, 1,
                    tzinfo=timezone.utc,
                )
                self._working_set['oldest_retained_unixtime'] = moment.timestamp()
            self._publish()

    def disk(self, *, used_percent: float, free_bytes: int) -> None:
        if not 0 <= used_percent <= 100 or free_bytes < 0:
            raise ValueError('invalid disk observation')
        with self._lock:
            self._disk['used_percent'] = float(used_percent)
            self._disk['free_bytes'] = float(free_bytes)
            self._publish()

    def schedule_mode(self, platform: Platform, mode: str) -> None:
        normalized = mode.strip().lower()
        if normalized not in {"legacy", "phased", "shadow"}:
            raise ValueError("invalid collector schedule mode")
        with self._lock:
            self._schedule_modes[Platform(platform).value] = normalized
            self._publish()

    def cycle(
        self,
        platform: Platform,
        *,
        duration: float,
        schedule_lag: float,
        overrun: bool,
        coalesced_slots: int = 0,
        resumed: bool = False,
    ) -> None:
        if (
            not math.isfinite(duration) or duration < 0
            or not math.isfinite(schedule_lag) or schedule_lag < 0
            or coalesced_slots < 0
        ):
            raise ValueError("invalid cycle metric observation")
        name = Platform(platform).value
        with self._lock:
            self._cycle_duration[name] = duration
            self._schedule_lag[name] = schedule_lag
            self._overruns[name] += int(overrun)
            self._coalesced[name] += coalesced_slots
            self._resumes[name] += int(resumed)
            self._publish()

    def request_timeout(self, platform: Platform) -> None:
        with self._lock:
            self._request_timeouts[Platform(platform).value] += 1
            self._publish()

    def provider_error(self, platform: Platform, error_class: str) -> None:
        cleaned = "".join(
            character for character in error_class
            if character.isalnum() or character == "_"
        )[:64] or "unknown"
        with self._lock:
            self._provider_errors[(Platform(platform).value, cleaned)] += 1
            self._publish()

    def shutdown(self, platform: Platform, *, forced: bool) -> None:
        with self._lock:
            self._shutdowns[(Platform(platform).value, "forced" if forced else "graceful")] += 1
            self._publish()

    def transfer(self, producer_id: str, values: dict[str, float | int]) -> None:
        safe = "".join(
            character for character in producer_id
            if character.isalnum() or character in "._/-"
        )[:128]
        if safe != producer_id or not safe or any(
            not math.isfinite(float(value)) or float(value) < 0
            for value in values.values()
        ):
            raise ValueError("invalid transfer metric observation")
        with self._lock:
            self._transfer[safe] = {key: float(value) for key, value in values.items()}
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
        lines += ['# TYPE mranked_collector_phase_wait_seconds_total counter']
        for platform,value in sorted(self._phase_wait.items()):
            lines.append(f'mranked_collector_phase_wait_seconds_total{{platform="{platform}"}} {value:.9g}')
        lines += ['# TYPE mranked_collector_phase_acquisitions_total counter']
        for (platform,result),value in sorted(self._phase_results.items()):
            lines.append(f'mranked_collector_phase_acquisitions_total{{platform="{platform}",result="{result}"}} {value}')
        lines += ['# TYPE mranked_collector_phase_attempts_total counter']
        for platform,value in sorted(self._phase_attempts.items()):
            lines.append(f'mranked_collector_phase_attempts_total{{platform="{platform}"}} {value}')
        lines += ['# TYPE mranked_collector_schedule_mode_info gauge']
        for platform,mode in sorted(self._schedule_modes.items()):
            lines.append(f'mranked_collector_schedule_mode_info{{platform="{platform}",mode="{mode}"}} 1')
        working_set_types = {
            'released_months_total': 'counter', 'deferred_months': 'gauge',
            'oldest_retained_unixtime': 'gauge',
        }
        for metric, metric_type in working_set_types.items():
            if metric in self._working_set:
                lines += [f'# TYPE mranked_collector_working_set_{metric} {metric_type}',
                          f'mranked_collector_working_set_{metric} {self._working_set[metric]:.9g}']
        for metric in ('used_percent', 'free_bytes'):
            if metric in self._disk:
                lines += [f'# TYPE mranked_collector_disk_{metric} gauge',
                          f'mranked_collector_disk_{metric} {self._disk[metric]:.9g}']
        lines += ['# TYPE mranked_collector_deployment_profile_info gauge']
        for platform,profile in sorted(self._deployment_profiles.items()):
            lines.append(f'mranked_collector_deployment_profile_info{{platform="{platform}",profile="{profile}"}} 1')
        lines += ['# TYPE mranked_collector_cycle_duration_seconds gauge']
        for platform,value in sorted(self._cycle_duration.items()):
            lines.append(f'mranked_collector_cycle_duration_seconds{{platform="{platform}"}} {value:.9g}')
        lines += ['# TYPE mranked_collector_schedule_lag_seconds gauge']
        for platform,value in sorted(self._schedule_lag.items()):
            lines.append(f'mranked_collector_schedule_lag_seconds{{platform="{platform}"}} {value:.9g}')
        for metric,values in (
            ('cycle_overruns_total', self._overruns),
            ('coalesced_slots_total', self._coalesced),
            ('resumed_runs_total', self._resumes),
            ('adapter_request_timeouts_total', self._request_timeouts),
        ):
            lines.append(f'# TYPE mranked_collector_{metric} counter')
            for platform,value in sorted(values.items()):
                lines.append(f'mranked_collector_{metric}{{platform="{platform}"}} {value}')
        lines += ['# TYPE mranked_collector_shutdowns_total counter']
        for (platform,outcome),value in sorted(self._shutdowns.items()):
            lines.append(f'mranked_collector_shutdowns_total{{platform="{platform}",outcome="{outcome}"}} {value}')
        lines += ['# TYPE mranked_collector_provider_errors_total counter']
        for (platform,error_class),value in sorted(self._provider_errors.items()):
            lines.append(f'mranked_collector_provider_errors_total{{platform="{platform}",error_class="{error_class}"}} {value}')
        transfer_types = {
            "last_produced_cursor": "gauge", "last_acknowledged_cursor": "gauge",
            "last_applied_cursor": "gauge", "outbox_rows": "gauge",
            "outbox_bytes": "gauge", "backlog_rows": "gauge",
            "backlog_bytes": "gauge", "oldest_backlog_age_seconds": "gauge",
            "batch_latency_seconds": "gauge", "retries_total": "counter",
            "checksum_failures_total": "counter", "duplicates_total": "counter",
            "attempt_window_exhausted_rows": "gauge",
            "rejects_total": "counter", "quarantines_total": "counter",
            "unaccounted_records": "gauge",
        }
        for metric, metric_type in transfer_types.items():
            lines.append(f'# TYPE mranked_transfer_{metric} {metric_type}')
            for producer, values in sorted(self._transfer.items()):
                if metric in values:
                    lines.append(
                        f'mranked_transfer_{metric}{{producer="{producer}"}} {values[metric]:.9g}'
                    )
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
