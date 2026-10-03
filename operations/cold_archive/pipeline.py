"""Перевод месяца замеров в холодный архив поколениями (ADR-016).

Месяц партиции — месяц публикации поста. Он готов к архиву, когда со дня его
конца прошло coldAfterDays (политика хранения, не меньше 30), а анализ всех его
постов окончен. Один запуск переводит один месяц:

1. preparing (месяц открыт): черновик файла просмотра — готовая выдача
   истории каждого поста. Где выдача из analytics.publication_history_page
   полна и свежа, она берётся как есть; остальное считается тем же запросом
   и DTO, что у API. Самый долгий шаг идёт без блокировок.
2. exporting (месяц закрыт для записи): полный файл Parquet v3 с
   проверенным манифестом (service.py), затем в черновике пересчитываются
   только посты, чей отпечаток изменился, и пишется окончательный файл
   просмотра.
3. replicating: файлы регистрируются в хранилище; агенты копируют полный файл
   на другой сервер. Его подтверждённая копия становится независимой
   аттестацией — без неё партицию удалить нельзя.
4. dropping → cold: удаление партиции (drop_v22). Месяц снова открыт, поздние
   замеры пойдут в новую партицию и уйдут следующим поколением.

Закрытый месяц задерживает перенос его поздних замеров с Сервера 1: батчи
повторяются с паузой и не теряются. Поэтому закрытие ограничено сроком
(по умолчанию два часа): не дождавшись копии, конвейер открывает месяц,
выводит файлы поколения из оборота и пробует на следующий день.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import logging
import lzma
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from typing import Any, Callable
import zlib

import psycopg
from psycopg.rows import dict_row

from api import dto
from api.sql import details
from operations.storage import store

from . import browse
from .model import MonthRange
from .parquet import verify_archive
from .service import ColdArchiveService

logger = logging.getLogger("cold-archive")
FULL_HISTORY_LIMIT = 1_000_000
# Готовая выдача обрезана на 2000 элементов с признаком продолжения.
STORED_PAGE_LIMIT = 2000
COLLECTOR_INTERVAL_SECONDS = {"telegram": 300, "vk": 300, "max": 300, "rutube": 3600}

CANDIDATE_MONTHS = """
SELECT to_date(substring(child.relname from '(\\d{4}_\\d{2})$'), 'YYYY_MM') AS month,
       pg_total_relation_size(child.oid) AS hot_bytes
  FROM pg_inherits link
  JOIN pg_class parent ON parent.oid = link.inhparent
  JOIN pg_class child ON child.oid = link.inhrelid
 WHERE parent.relname = 'publication_metric_snapshot'
   AND child.relname ~ '_\\d{4}_\\d{2}$'
 ORDER BY 1
"""
MONTH_ROWS = "SELECT EXISTS (SELECT 1 FROM ingest.publication_metric_snapshot WHERE published_month = %(month)s) AS any"
UNFINISHED_ANALYSIS = """
SELECT count(*) AS open
  FROM analytics.post_anomaly_state state
  JOIN ingest.publication publication ON publication.id = state.publication_id
 WHERE NOT state.frozen
   AND publication.published_at >= %(start)s AND publication.published_at < %(end)s
"""
POSTS = """
SELECT snapshot.publication_id::text AS publication_id, publication.primary_account_id::text AS account_id,
       publication.published_at, account.platform::text AS platform,
       count(*)::integer AS snapshot_count, max(snapshot.id)::bigint AS max_snapshot_id
  FROM ingest.publication_metric_snapshot snapshot
  JOIN ingest.publication publication ON publication.id = snapshot.publication_id
  JOIN catalog.platform_account account ON account.id = publication.primary_account_id
 WHERE snapshot.published_month = %(month)s
 GROUP BY 1, 2, 3, 4
"""
STORED_PAGE = """
SELECT payload, items_count, snapshot_count, max_snapshot_id
  FROM analytics.publication_history_page WHERE publication_id = %(publication_id)s::uuid
"""


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path
    cold_after_days: int
    fence_deadline: timedelta
    pace: float


def _policy(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    row = connection.execute("SELECT value FROM ops_and_admin.runtime_policy WHERE name = 'storage'").fetchone()
    return row["value"] if row else {}


def due_months(connection: psycopg.Connection[Any], cold_after_days: int, today: date) -> list[dict[str, Any]]:
    result = []
    busy = {row["published_month"] for row in connection.execute(
        "SELECT published_month FROM ops_and_admin.cold_archive_generation "
        "WHERE state IN ('preparing', 'exporting', 'replicating', 'dropping')").fetchall()}
    for row in connection.execute(CANDIDATE_MONTHS).fetchall():
        month = MonthRange(row["month"])
        if month.end + timedelta(days=cold_after_days) > today or month.start in busy:
            continue
        if not connection.execute(MONTH_ROWS, {"month": month.start}).fetchone()["any"]:
            continue
        open_posts = connection.execute(UNFINISHED_ANALYSIS, {"start": month.start_utc, "end": month.end_utc}).fetchone()
        result.append({"month": month, "hot_bytes": row["hot_bytes"], "analysis_open": open_posts["open"]})
    return result


def _history_items(connection: psycopg.Connection[Any], post: dict[str, Any], month: date) -> list[dict[str, Any]]:
    stored = connection.execute(STORED_PAGE, {"publication_id": post["publication_id"]}).fetchone()
    if (stored is not None and stored["items_count"] <= STORED_PAGE_LIMIT
            and (stored["snapshot_count"], stored["max_snapshot_id"]) == (post["snapshot_count"], post["max_snapshot_id"])):
        return json.loads(zlib.decompress(stored["payload"]))
    rows = connection.execute(details.HISTORY, {
        "publication_id": post["publication_id"], "published_month": month,
        "as_of": datetime.now(timezone.utc), "after_snapshot_id": None, "fetch_limit": FULL_HISTORY_LIMIT,
    }).fetchall()
    # Тот же JSON, что отдаёт API: значения, которые json не знает, — строкой.
    return json.loads(json.dumps([dto.history_snapshot(row) for row in rows], default=str))


def _coverage(connection: psycopg.Connection[Any], post: dict[str, Any]) -> dict[str, Any] | None:
    row = connection.execute(details.COLLECTOR_COVERAGE, {
        "publication_id": post["publication_id"], "from_at": post["published_at"],
        "as_of": datetime.now(timezone.utc),
        "expected_interval_seconds": COLLECTOR_INTERVAL_SECONDS.get(post["platform"], 300),
    }).fetchone()
    return json.loads(json.dumps(dto.collector_coverage(row), default=str)) if row else None


class Draft:
    """Черновик файла просмотра: изменяемый SQLite в incoming."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS post (
            publication_id TEXT PRIMARY KEY, account_id TEXT, published_at TEXT, snapshot_count INTEGER,
            max_snapshot_id INTEGER, items BLOB, coverage BLOB) WITHOUT ROWID""")

    def fingerprint(self, publication_id: str) -> tuple[int, int] | None:
        row = self.connection.execute("SELECT snapshot_count, max_snapshot_id FROM post WHERE publication_id = ?",
                                      (publication_id,)).fetchone()
        return (row[0], row[1]) if row else None

    def put(self, post: dict[str, Any], items: list[dict[str, Any]], coverage: dict[str, Any] | None) -> None:
        self.connection.execute("INSERT OR REPLACE INTO post VALUES (?,?,?,?,?,?,?)", (
            post["publication_id"], post["account_id"], post["published_at"].isoformat(), post["snapshot_count"],
            post["max_snapshot_id"], lzma.compress(json.dumps(items).encode(), preset=1),
            lzma.compress(json.dumps(coverage).encode(), preset=1)))
        self.connection.commit()

    def keep_only(self, ids: set[str]) -> None:
        stale = [row[0] for row in self.connection.execute("SELECT publication_id FROM post") if row[0] not in ids]
        self.connection.executemany("DELETE FROM post WHERE publication_id = ?", [(item,) for item in stale])
        self.connection.commit()

    def records(self) -> Iterator[browse.BrowseRecord]:
        for row in self.connection.execute("SELECT * FROM post ORDER BY publication_id"):
            yield browse.BrowseRecord(row[0], row[1], datetime.fromisoformat(row[2]),
                                      json.loads(lzma.decompress(row[5])), json.loads(lzma.decompress(row[6])),
                                      row[3], row[4])

    def close(self) -> None:
        self.connection.close()


def fill_draft(connection: psycopg.Connection[Any], draft: Draft, month: date, pace: float,
               sleep: Callable[[float], None] = time.sleep) -> tuple[int, int]:
    """Довести черновик до текущего состояния партиции; вернуть (пересчитано, всего)."""
    posts = connection.execute(POSTS, {"month": month}).fetchall()
    computed = 0
    for post in posts:
        if draft.fingerprint(post["publication_id"]) == (post["snapshot_count"], post["max_snapshot_id"]):
            continue
        began = time.monotonic()
        draft.put(post, _history_items(connection, post, month), _coverage(connection, post))
        computed += 1
        # Вполсилы, как задание готовых страниц: база остаётся посетителям.
        if pace:
            sleep((time.monotonic() - began) * pace)
    draft.keep_only({post["publication_id"] for post in posts})
    return computed, len(posts)


class Pipeline:
    def __init__(self, dsn: str, settings: Settings, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.dsn, self.settings, self.clock, self.sleep = dsn, settings, clock, sleep

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row)

    def _state(self, connection: Any, month: date, generation: int, state: str, **values: Any) -> None:
        assignments = ", ".join(f"{key} = %({key})s" for key in values)
        connection.execute(
            f"UPDATE ops_and_admin.cold_archive_generation SET state = %(state)s, updated_at = transaction_timestamp()"
            f"{', ' + assignments if assignments else ''}"
            f"{', finished_at = transaction_timestamp()' if state in ('cold', 'failed') else ''}"
            " WHERE published_month = %(month)s AND generation = %(generation)s",
            {"state": state, "month": month, "generation": generation, **values})

    def run(self, only: date | None = None) -> dict[str, Any]:
        with self._connect() as connection:
            lock = connection.execute("SELECT pg_try_advisory_lock(hashtext('cold-archive-pipeline')) AS ok").fetchone()
            if not lock["ok"]:
                return {"status": "busy"}
            try:
                policy = _policy(connection)
                cold_after = max(30, int(policy.get("coldAfterDays") or self.settings.cold_after_days))
                today = self.clock().date()
                months = [item for item in due_months(connection, cold_after, today)
                          if only is None or item["month"].start == only]
                ready = [item for item in months if item["analysis_open"] == 0]
                if not ready:
                    return {"status": "idle", "waiting": [
                        {"month": item["month"].key, "analysisOpen": item["analysis_open"]} for item in months]}
                return self.archive_month(connection, ready[0]["month"], ready[0]["hot_bytes"])
            finally:
                connection.execute("SELECT pg_advisory_unlock(hashtext('cold-archive-pipeline'))")

    def archive_month(self, connection: Any, month: MonthRange, hot_bytes: int) -> dict[str, Any]:
        generation = connection.execute(
            "SELECT coalesce(max(generation), 0) + 1 AS next FROM ops_and_admin.cold_archive_generation "
            "WHERE published_month = %(month)s", {"month": month.start}).fetchone()["next"]
        connection.execute("INSERT INTO ops_and_admin.cold_archive_generation (published_month, generation, state, hot_bytes)"
                           " VALUES (%(month)s, %(generation)s, 'preparing', %(hot)s)",
                           {"month": month.start, "generation": generation, "hot": hot_bytes})
        root = self.settings.root
        store.ensure_layout(root)
        stem = f"{month.key}-g{generation}"
        draft_path = root / "incoming" / f"browse-{stem}.draft.sqlite"
        spool = root / "incoming" / "spool"
        fenced = dropped = False
        objects: list[str] = []
        try:
            draft = Draft(draft_path)
            computed, total = fill_draft(connection, draft, month.start, self.settings.pace, self.sleep)
            logger.info("cold archive draft month=%s generation=%s posts=%s computed=%s",
                        month.key, generation, total, computed)
            service = ColdArchiveService(self.dsn, spool)
            spool.mkdir(parents=True, exist_ok=True)
            self._state(connection, month.start, generation, "exporting")
            connection.execute("SELECT ops_and_admin.begin_publication_archive(%s)", (month.start,))
            fenced = True
            fence_until = self.clock() + self.settings.fence_deadline
            self._assert_capacity(connection, month, spool)
            temporary, expected = service._export(connection, month)
            try:
                verification = verify_archive(temporary, expected_row_count=expected)
                exported = service._publish_object(temporary, month, verification)
            finally:
                temporary.unlink(missing_ok=True)
            sidecar = service._publish_sidecar(month, exported, verification)
            manifest_id = str(service._record_verified_manifest(connection, month, exported, sidecar, verification))
            full_name = f"snapshots-{stem}.parquet"
            full_path = store.object_path(root, "archive_full", full_name)
            os.replace(exported, full_path)
            os.chmod(full_path, 0o644)
            # Месяц закрыт: досчитываются только посты, изменившиеся с черновика.
            recomputed, total = fill_draft(connection, draft, month.start, 0.0, self.sleep)
            browse_name = f"browse-{stem}.sqlite"
            browse_path = store.object_path(root, "archive_browse", browse_name)
            summary = browse.write(browse_path, month.key, draft.records())
            draft.close()
            draft_path.unlink(missing_ok=True)
            os.chmod(browse_path, 0o644)
            full_id = self._register(connection, "archive_full", full_name, full_path.stat().st_size,
                                     verification.sha256, month.start, generation, manifest_id)
            objects.append(full_id)
            browse_id = self._register(connection, "archive_browse", browse_name, summary.size_bytes,
                                       summary.sha256, month.start, generation, None)
            objects.append(browse_id)
            self._state(connection, month.start, generation, "replicating", manifest_id=manifest_id,
                        full_object_id=full_id, browse_object_id=browse_id, row_count=verification.row_count,
                        publications=summary.publications)
            logger.info("cold archive exported month=%s rows=%s posts=%s recomputed=%s full=%s browse=%s",
                        month.key, verification.row_count, summary.publications, recomputed,
                        full_path.stat().st_size, summary.size_bytes)
            holder = self._wait_for_copy(connection, full_id, fence_until)
            connection.execute("SELECT ops_and_admin.attest_node_replica(%s::uuid, %s::uuid, %s)",
                               (manifest_id, full_id, holder))
            self._state(connection, month.start, generation, "dropping")
            with connection.transaction():
                connection.execute("SELECT ops_and_admin.drop_publication_metric_partition_v22(%s, %s::uuid)",
                                   (month.start, manifest_id))
            dropped = True
            fenced = False
            # Готовые страницы этого месяца больше не сверить с партицией.
            connection.execute("DELETE FROM analytics.publication_history_page WHERE published_month = %(month)s",
                               {"month": month.start})
            self._state(connection, month.start, generation, "cold")
            return {"status": "cold", "month": month.key, "generation": generation, "rows": verification.row_count,
                    "publications": summary.publications, "hotBytes": hot_bytes,
                    "archiveBytes": full_path.stat().st_size + summary.size_bytes, "copy": holder}
        except Exception as error:
            logger.error("cold archive failed month=%s generation=%s class=%s", month.key, generation,
                         type(error).__name__)
            if fenced and not dropped:
                connection.execute("SELECT ops_and_admin.abort_publication_archive(%s)", (month.start,))
            if not dropped and objects:
                # Без удаления партиции поколение недействительно: его файлы
                # выводятся из оборота, следующий запуск выгрузит месяц заново.
                connection.execute("UPDATE ops_and_admin.storage_object SET retired_at = transaction_timestamp() "
                                   "WHERE id = ANY(%(ids)s::uuid[])", {"ids": objects})
            self._state(connection, month.start, generation, "failed", error=f"{type(error).__name__}: {error}"[:500])
            raise

    def _assert_capacity(self, connection: Any, month: MonthRange, spool: Path) -> None:
        """Parquet+Zstd меньше партиции в разы (замер 08.2026: ~1/5), а файл
        просмотра — ещё в несколько раз; запас — половина партиции и гигабайт.
        Проверка сервиса (двойной размер) не дала бы архивировать крупный месяц
        как раз тогда, когда место нужнее всего."""
        name = f"ingest.publication_metric_snapshot_{month.partition_suffix}"
        row = connection.execute("SELECT to_regclass(%s) AS relation, "
                                 "coalesce(pg_total_relation_size(to_regclass(%s)), 0) AS bytes", (name, name)).fetchone()
        if row["relation"] is None:
            raise ValueError(f"snapshot partition {name} does not exist")
        required = int(row["bytes"]) // 2 + 1024 ** 3
        free = shutil.disk_usage(spool).free
        if free < required:
            raise RuntimeError(f"archive staging capacity gate failed: require {required} bytes, have {free}")

    def _register(self, connection: Any, kind: str, name: str, size: int, sha256: str, month: date,
                  generation: int, manifest_id: str | None) -> str:
        main = connection.execute("SELECT id FROM ops_and_admin.server_node WHERE role = 'main'").fetchone()["id"]
        row = connection.execute("""
            INSERT INTO ops_and_admin.storage_object (kind, name, size_bytes, sha256, published_month, generation,
                   manifest_id, origin_node)
            VALUES (%(kind)s, %(name)s, %(size)s, %(sha)s, %(month)s, %(generation)s, %(manifest)s::uuid, %(main)s)
            RETURNING id::text""", {"kind": kind, "name": name, "size": size, "sha": sha256, "month": month,
                                     "generation": generation, "manifest": manifest_id, "main": main}).fetchone()
        connection.execute("""INSERT INTO ops_and_admin.storage_replica (object_id, node_id, state, bytes_done, verified_at)
                              VALUES (%(object)s::uuid, %(main)s, 'verified', %(size)s, transaction_timestamp())""",
                           {"object": row["id"], "main": main, "size": size})
        return row["id"]

    def _wait_for_copy(self, connection: Any, object_id: str, until: datetime) -> str:
        while True:
            row = connection.execute("""
                SELECT replica.node_id FROM ops_and_admin.storage_replica replica
                  JOIN ops_and_admin.server_node node ON node.id = replica.node_id
                 WHERE replica.object_id = %(object)s::uuid AND replica.state = 'verified' AND node.role <> 'main'
                 ORDER BY replica.verified_at LIMIT 1""", {"object": object_id}).fetchone()
            if row is not None:
                return row["node_id"]
            if self.clock() >= until:
                raise TimeoutError("no verified off-main copy before the fence deadline")
            self.sleep(15)


def run_jobs(dsn: str, pipeline: Pipeline) -> int:
    """Задания «архивировать сейчас» из панели и плановый запуск."""
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        job = connection.execute("""
            UPDATE ops_and_admin.admin_job SET state = 'running', started_at = transaction_timestamp()
             WHERE id = (SELECT id FROM ops_and_admin.admin_job WHERE kind = 'archive_now' AND state = 'queued'
                          ORDER BY requested_at LIMIT 1 FOR UPDATE SKIP LOCKED)
            RETURNING id::text, params""").fetchone()
    only = None
    if job and job["params"].get("month"):
        only = MonthRange.parse(job["params"]["month"]).start
    try:
        result = pipeline.run(only)
        state, error = "done", None
    except Exception as failure:  # noqa: BLE001 — итог пишется в задание
        result, state, error = None, "failed", f"{type(failure).__name__}: {failure}"[:500]
    if job:
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute("UPDATE ops_and_admin.admin_job SET state = %s, finished_at = transaction_timestamp(),"
                               " result = %s::jsonb, error = %s WHERE id = %s::uuid",
                               (state, json.dumps(result, default=str), error, job["id"]))
    logger.info("cold archive run state=%s result=%s", state, json.dumps(result, default=str))
    return 0 if state == "done" else 1


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    dsn = os.environ["MAINTENANCE_DATABASE_URL"]
    settings = Settings(
        root=Path(os.getenv("MRANKED_STORE_DIR", str(store.DEFAULT_ROOT))),
        cold_after_days=int(os.getenv("COLD_ARCHIVE_AFTER_DAYS", "30")),
        fence_deadline=timedelta(minutes=int(os.getenv("COLD_ARCHIVE_FENCE_MINUTES", "120"))),
        pace=float(os.getenv("COLD_ARCHIVE_PACE", "1.0")),
    )
    return run_jobs(dsn, Pipeline(dsn, settings))


if __name__ == "__main__":
    sys.exit(main())
