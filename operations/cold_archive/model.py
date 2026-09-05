from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import re


UTC = timezone.utc


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


@dataclass(frozen=True, slots=True)
class MonthRange:
    """A canonical half-open UTC month used by partitions and manifests."""

    start: date

    def __post_init__(self) -> None:
        if self.start.day != 1:
            raise ValueError("archive month must be the first calendar day")

    @classmethod
    def parse(cls, raw: str) -> "MonthRange":
        if re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", raw) is None:
            raise ValueError("month must use YYYY-MM")
        try:
            parsed = datetime.strptime(raw, "%Y-%m").date()
        except ValueError as error:
            raise ValueError("month must use YYYY-MM") from error
        return cls(parsed)

    @property
    def end(self) -> date:
        return _next_month(self.start)

    @property
    def start_utc(self) -> datetime:
        return datetime.combine(self.start, datetime.min.time(), tzinfo=UTC)

    @property
    def end_utc(self) -> datetime:
        return datetime.combine(self.end, datetime.min.time(), tzinfo=UTC)

    @property
    def key(self) -> str:
        return self.start.strftime("%Y-%m")

    @property
    def partition_suffix(self) -> str:
        return self.start.strftime("%Y_%m")


@dataclass(frozen=True, slots=True)
class ArchiveVerification:
    sha256: str
    row_count: int
    min_observed_at: datetime | None
    max_observed_at: datetime | None
    sample_rows_read: int
    row_groups: int
    compression: str


@dataclass(frozen=True, slots=True)
class ArchiveResult:
    manifest_id: str
    month: MonthRange
    object_path: Path
    manifest_path: Path
    verification: ArchiveVerification
    reused: bool
    hot_partition_dropped: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "manifestId": self.manifest_id,
            "datasetType": "publication_metric_snapshot",
            "partitionStart": self.month.start_utc.isoformat(),
            "partitionEnd": self.month.end_utc.isoformat(),
            "objectPath": str(self.object_path),
            "manifestPath": str(self.manifest_path),
            "sha256": self.verification.sha256,
            "rowCount": self.verification.row_count,
            "minObservedAt": _iso(self.verification.min_observed_at),
            "maxObservedAt": _iso(self.verification.max_observed_at),
            "sampleRowsRead": self.verification.sample_rows_read,
            "rowGroups": self.verification.row_groups,
            "compression": self.verification.compression,
            "reused": self.reused,
            "hotPartitionDropped": self.hot_partition_dropped,
        }


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None
