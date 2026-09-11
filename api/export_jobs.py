"""Owner-scoped, bounded background CSV export jobs."""
from __future__ import annotations

import asyncio
import csv
import fcntl
import os
import shutil
import stat
import tempfile
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .cached import REVISION_SQL
from .errors import ApiProblem, NotFound
from .exporting import modern_cell
from .sql import exports as export_sql

MAX_ROWS = 2_000_000
MAX_BYTES = 512 * 1024 * 1024
MAX_SECONDS = 300
TTL_SECONDS = 900
PUBLIC_HEADERS = ("platform", "institution", "publication_id", "published_at", "observed_at",
                  "views", "reactions", "comments", "shares", "quality", "dataset_revision")


def _instant(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ExportJob:
    owner: str
    platform: str
    revision: int
    committed_at: datetime
    spool: Path
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    state: str = "queued"
    rows: int = 0
    bytes: int = 0
    error: str | None = None
    task: asyncio.Task[None] | None = None

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=TTL_SECONDS)

    @property
    def partial(self) -> Path:
        return self.spool / f"job-{self.id}.part"

    @property
    def complete(self) -> Path:
        return self.spool / f"job-{self.id}.csv"

    def view(self) -> dict[str, object]:
        return {"id": str(self.id), "platform": self.platform, "state": self.state,
                "datasetRevision": self.revision,
                "createdAt": self.created_at.isoformat().replace("+00:00", "Z"),
                "expiresAt": self.expires_at.isoformat().replace("+00:00", "Z"),
                "rowsWritten": self.rows, "bytesWritten": self.bytes,
                "errorCode": self.error, "maxRows": MAX_ROWS, "maxBytes": MAX_BYTES}


class ExportJobs:
    def __init__(self, database, directory: str | None = None) -> None:
        configured = directory or os.environ.get(
            "MRANKED_EXPORT_SPOOL_DIRECTORY",
            str(Path(tempfile.gettempdir()) / "mranked-async-exports"))
        path = Path(configured)
        if not path.is_absolute() or path.is_symlink():
            raise ValueError("каталог фоновых экспортов должен быть абсолютным и приватным")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
        self.spool = path.resolve(strict=True)
        if stat.S_IMODE(self.spool.stat().st_mode) != 0o700:
            raise ValueError("небезопасные права каталога фоновых экспортов")
        self.database = database
        self.jobs: dict[uuid.UUID, ExportJob] = {}
        self.rates: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()
        self.workers = asyncio.Semaphore(2)
        self.reaper: asyncio.Task[None] | None = None
        self.lock_file = None

    async def start(self) -> None:
        self.lock_file = (self.spool / ".owner.lock").open("a+b")
        try:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError("каталог фоновых экспортов уже используется") from error
        for candidate in self.spool.glob("job-*"):
            if re_job(candidate.name):
                candidate.unlink(missing_ok=True)
        self.reaper = asyncio.create_task(self._reap_loop(), name="mranked-export-reaper")

    async def close(self) -> None:
        if self.reaper:
            self.reaper.cancel()
        tasks = [job.task for job in self.jobs.values() if job.task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for job in self.jobs.values():
            job.partial.unlink(missing_ok=True)
            job.complete.unlink(missing_ok=True)
        if self.lock_file:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
            self.lock_file = None

    async def create(self, owner: str, platform: str) -> ExportJob:
        async with self.lock:
            await self._expire()
            active = [job for job in self.jobs.values()
                      if job.state in ("queued", "running", "succeeded")]
            if len(active) >= 4 or sum(job.owner == owner for job in active) >= 2:
                raise too_many("Достигнут лимит сохранённых экспортов")
            now = time.monotonic()
            recent = self.rates[owner]
            while recent and now-recent[0] > 60:
                recent.popleft()
            if len(recent) >= 5:
                raise too_many("Превышен минутный лимит фоновых экспортов")
            reserved = sum(max(0, MAX_BYTES-job.bytes) for job in active
                           if job.state in ("queued", "running"))
            if shutil.disk_usage(self.spool).free < reserved + MAX_BYTES:
                raise too_many("Недостаточно места для артефакта экспорта")
            row = await self.database.fetch_one(REVISION_SQL)
            if row is None or int(row["id"]) <= 0:
                raise too_many("Нет опубликованной ревизии набора данных")
            job = ExportJob(owner, platform, int(row["id"]), row["committed_at"], self.spool)
            self.jobs[job.id] = job
            recent.append(now)
            job.task = asyncio.create_task(self._generate(job), name=f"export-{job.id}")
            return job

    async def status(self, owner: str, job_id: uuid.UUID) -> ExportJob:
        async with self.lock:
            await self._expire()
            return self._owned(owner, job_id)

    async def cancel(self, owner: str, job_id: uuid.UUID) -> ExportJob:
        async with self.lock:
            job = self._owned(owner, job_id)
            if job.state not in ("cancelled", "expired"):
                job.state = "cancelled"
                if job.task:
                    job.task.cancel()
                job.partial.unlink(missing_ok=True)
                job.complete.unlink(missing_ok=True)
            return job

    async def download(self, owner: str, job_id: uuid.UUID) -> tuple[ExportJob, Path]:
        job = await self.status(owner, job_id)
        if job.state != "succeeded" or not job.complete.is_file():
            raise ApiProblem(409, "Conflict", "У экспорта нет готового действующего файла",
                             "urn:m-ranked:problem:export-not-ready")
        return job, job.complete

    def _owned(self, owner: str, job_id: uuid.UUID) -> ExportJob:
        job = self.jobs.get(job_id)
        if job is None or job.owner != owner:
            raise NotFound("Задание экспорта не найдено")
        return job

    async def _generate(self, job: ExportJob) -> None:
        async with self.workers:
            if job.state == "cancelled":
                return
            job.state = "running"
            started = time.monotonic()
            try:
                with job.partial.open("x", encoding="utf-8", newline="") as output:
                    os.chmod(job.partial, 0o600)

                    class Bounded:
                        def write(inner, value: str) -> int:
                            encoded = value.encode("utf-8")
                            if job.bytes + len(encoded) > MAX_BYTES:
                                raise JobFailure("MAX_BYTES")
                            written = output.write(value)
                            job.bytes += len(encoded)
                            return written

                    writer = csv.writer(Bounded(), lineterminator="\r\n")
                    writer.writerow([modern_cell(value) for value in PUBLIC_HEADERS])
                    async with self.database.read() as connection:
                        async with connection.transaction():
                            await connection.execute(
                                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                            revision = await (await connection.execute(REVISION_SQL)).fetchone()
                            if revision is None or int(revision["id"]) != job.revision:
                                raise JobFailure("REVISION_CHANGED")
                            query = export_sql.PUBLICATIONS.replace("LIMIT 100001", "LIMIT 2000001")
                            async with connection.cursor(name=f"export_{job.id.hex}") as cursor:
                                await cursor.execute(query, {"platform": job.platform,
                                                             "as_of": job.committed_at})
                                while batch := await cursor.fetchmany(500):
                                    for row in batch:
                                        if job.state == "cancelled":
                                            raise asyncio.CancelledError
                                        if job.rows >= MAX_ROWS:
                                            raise JobFailure("MAX_ROWS")
                                        if time.monotonic()-started >= MAX_SECONDS:
                                            raise JobFailure("MAX_DURATION")
                                        writer.writerow([modern_cell(value) for value in (
                                            row["platform"], row["institution"], row["publication_id"],
                                            _instant(row["published_at"]), _instant(row["observed_at"]),
                                            row["views_count"], row["reactions_count"],
                                            row["comments_count"], row["shares_count"], row["quality"],
                                            job.revision)])
                                        job.rows += 1
                os.replace(job.partial, job.complete)
                job.state = "succeeded"
            except asyncio.CancelledError:
                job.state = "cancelled" if job.state != "expired" else job.state
                job.partial.unlink(missing_ok=True)
            except JobFailure as error:
                job.state, job.error = "failed", error.code
                job.partial.unlink(missing_ok=True)
            except OSError:
                job.state, job.error = "failed", "IO_FAILURE"
                job.partial.unlink(missing_ok=True)
            except Exception:
                job.state, job.error = "failed", "SOURCE_FAILURE"
                job.partial.unlink(missing_ok=True)

    async def _expire(self) -> None:
        now = datetime.now(timezone.utc)
        for job in self.jobs.values():
            if now >= job.expires_at and job.state != "expired":
                job.state = "expired"
                if job.task:
                    job.task.cancel()
                job.partial.unlink(missing_ok=True)
                job.complete.unlink(missing_ok=True)
        stale = [key for key, job in self.jobs.items()
                 if now >= job.expires_at + timedelta(seconds=TTL_SECONDS)]
        for key in stale:
            del self.jobs[key]

    async def _reap_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(1)
                async with self.lock:
                    await self._expire()
        except asyncio.CancelledError:
            return


class JobFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def re_job(name: str) -> bool:
    import re
    return bool(re.fullmatch(r"job-[0-9a-f-]{36}\.(?:part|csv)", name))


def too_many(detail: str) -> ApiProblem:
    return ApiProblem(429, "Too Many Requests", detail,
                      "urn:m-ranked:problem:export-limit", headers={"Retry-After": "60"})
