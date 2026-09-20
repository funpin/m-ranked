"""Ingest settings; secrets stay in files referenced by path, never inline."""
from __future__ import annotations

from dataclasses import dataclass
import os


def _int(name: str, default: int) -> int:
    value = int(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True, slots=True)
class IngestSettings:
    host: str
    port: int
    certificate: str
    private_key: str
    ca_bundle: str
    database_url: str
    path: str = "/transfer/v1/batches"
    allowed_producers: tuple[str, ...] = ()

    @classmethod
    def load(cls) -> "IngestSettings":
        missing = [
            name for name in (
                "TRANSFER_INGEST_CERTIFICATE",
                "TRANSFER_INGEST_PRIVATE_KEY",
                "TRANSFER_INGEST_CA_BUNDLE",
            ) if not os.getenv(name, "").strip()
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} must be configured")
        dsn = (
            os.getenv("TRANSFER_INGEST_DATABASE_URL", "").strip()
            or os.getenv("COLLECTOR_DATABASE_URL", "").strip()
        )
        if not dsn:
            raise ValueError("TRANSFER_INGEST_DATABASE_URL must be configured")
        producers = tuple(
            item.strip()
            for item in os.getenv("TRANSFER_INGEST_ALLOWED_PRODUCERS", "").split(",")
            if item.strip()
        )
        return cls(
            host=os.getenv("TRANSFER_INGEST_HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=_int("TRANSFER_INGEST_PORT", 8443),
            certificate=os.environ["TRANSFER_INGEST_CERTIFICATE"].strip(),
            private_key=os.environ["TRANSFER_INGEST_PRIVATE_KEY"].strip(),
            ca_bundle=os.environ["TRANSFER_INGEST_CA_BUNDLE"].strip(),
            database_url=dsn,
            path=os.getenv("TRANSFER_INGEST_PATH", "/transfer/v1/batches").strip(),
            allowed_producers=producers,
        )
