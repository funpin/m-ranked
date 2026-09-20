"""Prometheus textfile metrics for the ingest listener.

Labels carry only bounded reason codes. A producer id comes from a verified
certificate, so it is safe as a label; anything derived from request content is
not and never becomes one.
"""
from __future__ import annotations

from collections import defaultdict
import os
from pathlib import Path
import re
import tempfile
from threading import Lock
import time


SAFE_LABEL = re.compile(r"^[A-Za-z0-9_./-]{1,128}$")


class IngestMetrics:
    def __init__(self, output: Path | None = None) -> None:
        self.output = output
        self._lock = Lock()
        self._accepted: dict[str, int] = defaultdict(int)
        self._duplicates: dict[str, int] = defaultdict(int)
        self._rejects: dict[tuple[str, str], int] = defaultdict(int)
        self._last_accepted: dict[str, float] = {}
        self._apply_seconds: dict[str, float] = {}

    @staticmethod
    def _safe(value: str) -> str:
        cleaned = str(value).strip()
        return cleaned if SAFE_LABEL.match(cleaned) else "unknown"

    def accepted(self, producer: str, *, duration: float, duplicate: bool) -> None:
        if duration < 0:
            raise ValueError("duration must not be negative")
        key = self._safe(producer)
        with self._lock:
            if duplicate:
                self._duplicates[key] += 1
            else:
                self._accepted[key] += 1
            self._last_accepted[key] = time.time()
            self._apply_seconds[key] = duration
            self._publish()

    def rejected(self, producer: str, reason: str) -> None:
        with self._lock:
            self._rejects[(self._safe(producer), self._safe(reason))] += 1
            self._publish()

    def render(self) -> str:
        with self._lock:
            return self._render()

    def _render(self) -> str:
        lines = ["# TYPE mranked_transfer_ingest_accepted_total counter"]
        for producer, value in sorted(self._accepted.items()):
            lines.append(
                f'mranked_transfer_ingest_accepted_total{{producer="{producer}"}} {value}'
            )
        lines.append("# TYPE mranked_transfer_ingest_duplicates_total counter")
        for producer, value in sorted(self._duplicates.items()):
            lines.append(
                f'mranked_transfer_ingest_duplicates_total{{producer="{producer}"}} {value}'
            )
        lines.append("# TYPE mranked_transfer_ingest_rejects_total counter")
        for (producer, reason), value in sorted(self._rejects.items()):
            lines.append(
                f'mranked_transfer_ingest_rejects_total'
                f'{{producer="{producer}",reason="{reason}"}} {value}'
            )
        lines.append("# TYPE mranked_transfer_ingest_apply_seconds gauge")
        for producer, value in sorted(self._apply_seconds.items()):
            lines.append(
                f'mranked_transfer_ingest_apply_seconds{{producer="{producer}"}} {value:.9g}'
            )
        lines.append("# TYPE mranked_transfer_ingest_last_accepted_unixtime gauge")
        for producer, value in sorted(self._last_accepted.items()):
            lines.append(
                f'mranked_transfer_ingest_last_accepted_unixtime'
                f'{{producer="{producer}"}} {value:.6f}'
            )
        return "\n".join(lines) + "\n"

    def _publish(self) -> None:
        if self.output is None:
            return
        if (
            not self.output.is_absolute()
            or self.output.is_symlink()
            or not self.output.parent.is_dir()
        ):
            raise ValueError("metrics file must have a provisioned absolute parent")
        descriptor, name = tempfile.mkstemp(
            prefix="." + self.output.name, dir=self.output.parent,
        )
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(self._render())
                stream.flush()
                os.fchmod(stream.fileno(), 0o640)
                os.fsync(stream.fileno())
            os.replace(name, self.output)
        finally:
            Path(name).unlink(missing_ok=True)
