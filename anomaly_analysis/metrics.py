from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import tempfile
import time


class TextfileMetrics:
    """Bounded Prometheus textfile metrics; labels come only from packaged enums."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.processed_counts: Counter[str] = Counter()
        self.detector_counts: Counter[tuple[str, str]] = Counter()
        self.finding_counts: Counter[tuple[str, str, str]] = Counter()
        self.last_duration = 0.0
        self.last_batch_size = 0
        self.analysis_revision = 0
        self.source_revision = 0
        self.operational_values: dict[str, float] = {}

    def processed(self, outcome: str, duration_seconds: float) -> None:
        self.processed_counts[outcome] += 1
        self.last_duration = duration_seconds
        self._publish()

    def detector(self, detector_id: str, outcome: str) -> None:
        self.detector_counts[(detector_id, outcome)] += 1

    def revision(self, analysis_revision: int, source_revision: int) -> None:
        self.analysis_revision = max(self.analysis_revision, analysis_revision)
        self.source_revision = max(self.source_revision, source_revision)

    def batch(self, size: int) -> None:
        self.last_batch_size = size

    def finding(self, detector_id: str, metric: str, severity: str) -> None:
        self.finding_counts[(detector_id, metric, severity)] += 1

    def operational(self, values: dict[str, float]) -> None:
        self.operational_values = dict(values)
        self._publish()

    def _publish(self) -> None:
        if self.path is None:
            return
        lines = ["# TYPE mranked_anomaly_publications_processed_total counter"]
        for outcome, value in sorted(self.processed_counts.items()):
            lines.append(f'mranked_anomaly_publications_processed_total{{outcome="{outcome}"}} {value}')
        lines.append("# TYPE mranked_anomaly_detector_evaluations_total counter")
        for (detector, outcome), value in sorted(self.detector_counts.items()):
            lines.append(f'mranked_anomaly_detector_evaluations_total{{detector="{detector}",outcome="{outcome}"}} {value}')
        lines.append("# TYPE mranked_anomaly_findings_total counter")
        for (detector, metric, severity), value in sorted(self.finding_counts.items()):
            lines.append(f'mranked_anomaly_findings_total{{detector="{detector}",metric="{metric}",severity="{severity}"}} {value}')
        lines.extend((
            "# TYPE mranked_anomaly_last_batch_size gauge",
            f"mranked_anomaly_last_batch_size {self.last_batch_size}",
            "# TYPE mranked_anomaly_last_duration_seconds gauge",
            f"mranked_anomaly_last_duration_seconds {self.last_duration:.9g}",
            "# TYPE mranked_anomaly_latest_analysis_revision gauge",
            f"mranked_anomaly_latest_analysis_revision {self.analysis_revision}",
            "# TYPE mranked_anomaly_latest_source_dataset_revision gauge",
            f"mranked_anomaly_latest_source_dataset_revision {self.source_revision}",
            "# TYPE mranked_anomaly_last_completion_unixtime gauge",
            f"mranked_anomaly_last_completion_unixtime {time.time():.9g}",
        ))
        for key, value in sorted(self.operational_values.items()):
            if key.replace("_", "").isalnum():
                lines.extend((f"# TYPE mranked_anomaly_{key} gauge", f"mranked_anomaly_{key} {value:.12g}"))
        if not self.path.is_absolute() or not self.path.parent.is_dir() or self.path.is_symlink():
            raise ValueError("metrics path must be a provisioned absolute regular destination")
        descriptor, temporary = tempfile.mkstemp(prefix="." + self.path.name, dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w") as stream:
                os.fchmod(stream.fileno(), 0o640)
                stream.write("\n".join(lines) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
