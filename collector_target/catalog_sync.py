"""Справочник Сервера 2 для сборщиков Сервера 1 (профиль B).

Команды каталога пишут только базу Сервера 2, а сборщики читают
``catalog.platform_account`` из своей. Отправитель переноса и так держит
mTLS-соединение с приёмником Сервера 2, поэтому справочник едет по нему же,
в обратную сторону: раз в несколько минут отправитель спрашивает снимок и
применяет его в своей базе одной транзакцией.

Снимок собирает и применяет SQL (миграция 0082): одно согласованное чтение на
Сервере 2, одна транзакция на Сервере 1, правила «чья версия новее» — там же.
Здесь только доставка. Сервер 2 отвечает отпечатком снимка, и пока справочник
не менялся, тело не передаётся и база Сервера 1 не трогается.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit


logger = logging.getLogger("catalog_sync")

CATALOG_PATH = "/catalog/v1/snapshot"
# Снимок сейчас около 400 КБ; предел с большим запасом и всё равно далеко
# от памяти отправителя (MemoryMax 256M).
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
DEFAULT_INTERVAL_SECONDS = 300
_DIGEST = re.compile(r"[0-9a-f]{64}")

SNAPSHOT_SQL = "SELECT catalog.catalog_sync_snapshot()::text AS snapshot"
APPLY_SQL = "SELECT catalog.apply_catalog_sync(%s::jsonb)::text AS result"


def catalog_endpoint(transfer_endpoint: str) -> str:
    """Адрес снимка у того же приёмника, что принимает пачки."""
    parsed = urlsplit(transfer_endpoint)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("catalog endpoint must be an HTTPS URL without credentials")
    return urlunsplit((parsed.scheme, parsed.netloc, CATALOG_PATH, "", ""))


def valid_digest(value: str | None) -> str | None:
    cleaned = (value or "").strip().lower()
    return cleaned if _DIGEST.fullmatch(cleaned) else None


def _value(row: Any, key: str) -> Any:
    return row[key] if isinstance(row, Mapping) else row[0]


class CatalogSnapshotSource:
    """Сервер 2: снимок справочника с отпечатком."""

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def respond(self, known: str | None) -> bytes:
        with self._connect() as connection:
            row = connection.execute(SNAPSHOT_SQL).fetchone()
        text = str(_value(row, "snapshot"))
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if valid_digest(known) == digest:
            return json.dumps({"digest": digest, "unchanged": True}).encode()
        # Снимок уже JSON: вкладывается как есть, без разбора и повторной
        # сериализации.
        return b'{"digest":"' + digest.encode() + b'","snapshot":' + text.encode("utf-8") + b"}"


@dataclass(slots=True)
class CatalogSyncStats:
    applied_total: int = 0
    failures_total: int = 0
    last_success_unix: float = 0.0
    account_conflicts: int = 0


class CatalogSync:
    """Сервер 1: спросить снимок и применить его, если он новый."""

    def __init__(
        self,
        connect: Callable[[], Any],
        fetch: Callable[[str | None], bytes],
        *,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._connect = connect
        self._fetch = fetch
        self.interval_seconds = interval_seconds
        self._clock = clock
        self._wall_clock = wall_clock
        self._next_at = float("-inf")
        self.digest: str | None = None
        self.stats = CatalogSyncStats()

    def run_if_due(self) -> Mapping[str, Any] | None:
        now = self._clock()
        if now < self._next_at:
            return None
        self._next_at = now + self.interval_seconds
        try:
            return self.run_once()
        except Exception as error:  # noqa: BLE001 — справочник не роняет доставку
            self.stats.failures_total += 1
            logger.warning("catalog sync failed class=%s", type(error).__name__)
            return None

    def run_once(self) -> Mapping[str, Any]:
        document = json.loads(self._fetch(self.digest))
        if not isinstance(document, dict):
            raise ValueError("catalog response is not an object")
        digest = valid_digest(document.get("digest"))
        if digest is None:
            raise ValueError("catalog response lacks a digest")
        if document.get("unchanged") is True and digest == self.digest:
            self.stats.last_success_unix = self._wall_clock()
            return {}
        snapshot = document.get("snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("catalog response lacks a snapshot")
        with self._connect() as connection:
            with connection.transaction():
                row = connection.execute(
                    APPLY_SQL, (json.dumps(snapshot, ensure_ascii=False),),
                ).fetchone()
        result = json.loads(_value(row, "result"))
        # Отпечаток запоминается только после фиксации: оборванное применение
        # повторится со следующего прохода.
        self.digest = digest
        self.stats.applied_total += 1
        self.stats.last_success_unix = self._wall_clock()
        self.stats.account_conflicts = int(result.get("accountConflicts") or 0)
        changes = {key: value for key, value in result.items() if value}
        if changes:
            logger.info("catalog sync applied %s", json.dumps(changes, sort_keys=True))
        if self.stats.account_conflicts:
            logger.warning(
                "catalog sync skipped accounts conflicting on platform/external key count=%s",
                self.stats.account_conflicts,
            )
        return result


def metrics_lines(stats: CatalogSyncStats) -> str:
    return (
        "# HELP mranked_catalog_sync_applied_total Применённые снимки справочника\n"
        "# TYPE mranked_catalog_sync_applied_total counter\n"
        f"mranked_catalog_sync_applied_total {stats.applied_total}\n"
        "# HELP mranked_catalog_sync_failures_total Неудачные запросы или применения снимка\n"
        "# TYPE mranked_catalog_sync_failures_total counter\n"
        f"mranked_catalog_sync_failures_total {stats.failures_total}\n"
        "# HELP mranked_catalog_sync_last_success_timestamp_seconds Последняя сверка со справочником Сервера 2\n"
        "# TYPE mranked_catalog_sync_last_success_timestamp_seconds gauge\n"
        f"mranked_catalog_sync_last_success_timestamp_seconds {stats.last_success_unix:.0f}\n"
        "# HELP mranked_catalog_sync_account_conflicts Аккаунты Сервера 2, не легшие из-за чужого id\n"
        "# TYPE mranked_catalog_sync_account_conflicts gauge\n"
        f"mranked_catalog_sync_account_conflicts {stats.account_conflicts}\n"
    )
