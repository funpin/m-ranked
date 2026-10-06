"""Возврат месяцев холодного архива в базу (0063).

Для каждого поколения месяца в состоянии cold: полный файл Parquet сверяется
по SHA-256 с учётом, строки идут в базу пачками через
ingest.restore_archived_snapshots, и каждая пачка тут же сверяется:
каноническая запись восстановленной строки (ops_and_admin.publication_archive_canonical)
обязана совпасть с canonical_record архива. Отличаться может только
ingested_xid — номер транзакции записи, который ограждение разбивки
требует текущим. Расхождение останавливает возврат.

Восстановленные строки — горячие и старые: их упакует служба упаковки.

    MAINTENANCE_DATABASE_URL=... python -m operations.cold_archive.restore 2026-07 2026-08
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Iterator

from operations.storage import store

log = logging.getLogger("cold-archive-restore")

BATCH = 2000
COLD_FILES = """
SELECT generation.generation, object.name, object.sha256, generation.row_count
  FROM ops_and_admin.cold_archive_generation generation
  JOIN ops_and_admin.storage_object object ON object.id = generation.full_object_id
 WHERE generation.published_month = %s AND generation.state = 'cold'
 ORDER BY generation.generation
"""
RESTORE = "SELECT ingest.restore_archived_snapshots(%s) AS restored"
CANONICAL = """
SELECT id, canonical_record FROM ops_and_admin.publication_archive_canonical
 WHERE published_month = %s AND id = ANY(%s)
"""
# Номер транзакции записи: ограждение разбивки требует текущий.
TECHNICAL = ("ingested_xid",)


class RestoreMismatch(RuntimeError):
    pass


@dataclass(slots=True)
class MonthResult:
    month: date
    files: int = 0
    rows: int = 0
    restored: int = 0


def canonical_without_technical(text: str) -> dict[str, Any]:
    record = json.loads(text)
    for key in TECHNICAL:
        record.pop(key, None)
    return record


def batches(path: Path, size: int = BATCH) -> Iterator[list[str]]:
    import pyarrow.parquet as pq

    for batch in pq.ParquetFile(path).iter_batches(batch_size=size, columns=["canonical_record"]):
        yield batch.column(0).to_pylist()


def restore_month(connection: Any, root: Path, month: date) -> MonthResult:
    from psycopg.types.json import Jsonb

    result = MonthResult(month)
    files = connection.execute(COLD_FILES, (month,)).fetchall()
    for item in files:
        path = store.object_path(root, "archive_full", item["name"])
        # Потоком: августовский файл — 830 МБ, а памяти на сервере 4 ГБ.
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"]:
            raise RestoreMismatch(f"{path.name}: SHA-256 differs from the storage record")
        result.files += 1
        rows_in_file = 0
        for texts in batches(path):
            records = [json.loads(text) for text in texts]
            restored = connection.execute(RESTORE, (Jsonb(records),)).fetchone()["restored"]
            ids = [record["id"] for record in records]
            stored = {row["id"]: row["canonical_record"]
                      for row in connection.execute(CANONICAL, (month, ids)).fetchall()}
            for record, text in zip(records, texts):
                current = stored.get(record["id"])
                if current is None or canonical_without_technical(current) != canonical_without_technical(text):
                    raise RestoreMismatch(f"month {month}: snapshot {record['id']} differs after restore")
            rows_in_file += len(records)
            result.restored += int(restored)
        if item["row_count"] is not None and rows_in_file != item["row_count"]:
            raise RestoreMismatch(f"{path.name}: {rows_in_file} rows, generation says {item['row_count']}")
        result.rows += rows_in_file
        log.info("restored month=%s generation=%s rows=%s", month, item["generation"], rows_in_file)
    return result


def main(argv: list[str]) -> int:
    import psycopg
    from psycopg.rows import dict_row

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    months = [date.fromisoformat(f"{value}-01") for value in argv]
    if not months:
        raise SystemExit("usage: python -m operations.cold_archive.restore YYYY-MM [YYYY-MM ...]")
    root = Path(os.getenv("MRANKED_STORE_DIR", str(store.DEFAULT_ROOT)))
    with psycopg.connect(os.environ["MAINTENANCE_DATABASE_URL"], autocommit=True, row_factory=dict_row,
                         options="-c timezone=UTC -c statement_timeout=300000") as connection:
        for month in months:
            result = restore_month(connection, root, month)
            log.info("month=%s files=%s rows=%s inserted=%s", month, result.files, result.rows, result.restored)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
