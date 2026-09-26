"""Retrievable, content-addressed sanitized evidence with fail-closed reads.

The directory must live on durable service storage. Publishing the object before
PG commit makes a crash leave an unreferenced object, never a dangling committed
reference. Exact retry safely reuses the immutable object. Retention is enforced
at retrieval using the authoritative PG purge_after value.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import tempfile
import time
from urllib.parse import unquote, urlsplit

from .normalize import canonical_json, sanitize_evidence
from .model import utc


class EvidenceUnavailable(RuntimeError):
    """Missing, expired, corrupt, or unsafe evidence; never echo payload data."""


class ImmutableEvidenceStore:
    def __init__(self, root: Path):
        self.root = root.absolute()

    def _directory(self) -> None:
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise EvidenceUnavailable("evidence root must be a real directory")
        info = self.root.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise EvidenceUnavailable("evidence directory permissions are unsafe")

    def put(self, value: object) -> tuple[str, str]:
        self._directory()
        payload = canonical_json(value).encode('utf-8')
        digest = hashlib.sha256(payload).hexdigest()
        destination = self.root / f'{digest}.json'
        descriptor, name = tempfile.mkstemp(prefix='.evidence-', dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fchmod(stream.fileno(), 0o400)
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                self._read_bytes(destination, digest)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return destination.as_uri(), digest

    def _read_bytes(self, path: Path, digest: str) -> bytes:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o400:
                    raise EvidenceUnavailable('evidence object permissions are unsafe')
                payload = stream.read()
        except OSError as error:
            raise EvidenceUnavailable('evidence object unavailable') from error
        if hashlib.sha256(payload).hexdigest() != digest:
            raise EvidenceUnavailable('evidence hash mismatch')
        return payload

    def read(self, uri: str, digest: str, *, purge_after: datetime, now: datetime) -> object:
        if utc(now, 'now') >= utc(purge_after, 'purge_after'):
            raise EvidenceUnavailable('evidence retention expired')
        parsed = urlsplit(uri)
        path = Path(unquote(parsed.path))
        if parsed.scheme != 'file' or parsed.netloc or path.parent != self.root or path.name != f'{digest}.json':
            raise EvidenceUnavailable('evidence reference is outside configured storage')
        payload = self._read_bytes(path, digest)
        try:
            value = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise EvidenceUnavailable('invalid evidence encoding') from error
        if canonical_json(value).encode('utf-8') != payload or sanitize_evidence(value) != value:
            raise EvidenceUnavailable('evidence redaction verification failed')
        return value


    def purge_expired(self, connection, *, now: datetime, max_objects: int = 1000,
                      orphan_grace: timedelta = timedelta(days=7),
                      max_seconds: float = 10) -> int:
        """Bounded physical expiry; uses the collector's exact per-hash DB lock.

        Use a maintenance connection and the same durable directory. A crash
        after unlink can leave only expired metadata; new ingestion republishes
        its object while holding the same lock before committing its reference.
        """
        if max_objects < 1 or max_objects > 100_000 or orphan_grace < timedelta(days=7):
            raise ValueError("unsafe evidence purge bounds")
        if not 0 < max_seconds <= 60:
            raise ValueError("unsafe evidence time budget")
        deadline = time.monotonic() + max_seconds
        now = utc(now, "now")
        self._directory()
        removed = 0
        examined = 0
        # A durable worklist scans the directory once per sweep, not on every
        # batch. 70 bytes/object (~21 MiB at 312k files), constant process RAM.
        # Progress also advances over retained objects. Replaying after a crash
        # is safe because metadata and the per-hash lock are checked again.
        with self._gc_entries(max_objects, deadline) as entries:
            for entry in entries:
                if examined >= max_objects:
                    break
                if not re.fullmatch(r"[0-9a-f]{64}\.json", entry.name) or entry.is_symlink() or not entry.is_file():
                    continue
                examined += 1
                digest = entry.name[:-5]
                uri = (self.root / entry.name).as_uri()
                with connection.transaction():
                    connection.execute("SET LOCAL lock_timeout='1s'")
                    connection.execute("SET LOCAL statement_timeout='5s'")
                    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("raw-evidence:" + digest,))
                    result = connection.execute(
                        "SELECT max(purge_after) FROM ingest.raw_payload WHERE external_ref=%s", (uri,)
                    ).fetchone()
                    if not entry.exists():
                        continue
                    latest = next(iter(result.values())) if isinstance(result, dict) else result[0]
                    if latest is not None and latest > now:
                        continue
                    if latest is None and datetime.fromtimestamp(entry.lstat().st_mtime, now.tzinfo) > now - orphan_grace:
                        continue
                    self._read_bytes(self.root / entry.name, digest)
                    (self.root / entry.name).unlink()
                    directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                    connection.execute("SELECT ops_and_admin.purge_raw_evidence_reference(%s,%s)", (uri,now))
                    removed += 1
        return removed

    @contextmanager
    def _gc_entries(self, limit: int, deadline: float):
        """Single sweeper; atomically published manifest + durable byte cursor.

        The directory is service-owned and private. Opening control files with
        O_NOFOLLOW prevents an unexpected symlink from redirecting GC writes.
        New objects enter the next sweep; orphan grace still applies.
        """
        lock_fd = os.open(self.root / '.gc-lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock_fd, 'r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            manifest = self.root / '.gc-worklist'
            cursor = self.root / '.gc-cursor'
            offset = 0
            if cursor.exists():
                fd = os.open(cursor, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd) as stream:
                    offset = int(stream.read(32))
                if offset < 0 or offset % 70:
                    raise EvidenceUnavailable('invalid GC cursor')
            if not manifest.exists():
                offset = 0
                fd, name = tempfile.mkstemp(prefix='.gc-build-', dir=self.root)
                try:
                    with os.fdopen(fd, 'w') as stream, os.scandir(self.root) as entries:
                        for entry in entries:
                            # Remove only this sweeper's stale crash temporaries,
                            # never JSON evidence by filename/mtime alone.
                            if entry.name.startswith(('.gc-build-', '.gc-state-')) and entry.name != Path(name).name and entry.is_file(follow_symlinks=False):
                                info = entry.stat(follow_symlinks=False)
                                if info.st_uid == os.geteuid() and info.st_mtime < time.time() - 86400:
                                    (self.root / entry.name).unlink(missing_ok=True)
                            if re.fullmatch(r'[0-9a-f]{64}\.json', entry.name) and entry.is_file(follow_symlinks=False):
                                stream.write(entry.name + '\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                    # Reset cursor before publishing: crash may safely replay.
                    self._gc_checkpoint(cursor, 0)
                    os.replace(name, manifest)
                finally:
                    Path(name).unlink(missing_ok=True)
            fd = os.open(manifest, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                stream.seek(offset)
                def entries():
                    for _ in range(limit):
                        if time.monotonic() >= deadline:
                            break
                        line = stream.readline(71)
                        if not line:
                            break
                        if len(line) != 70 or not re.fullmatch(rb'[0-9a-f]{64}\.json\n', line):
                            raise EvidenceUnavailable('invalid GC worklist')
                        yield self.root / line.decode('ascii').strip()
                yield entries()
                # Only commit progress on success; exceptions retry this batch.
                self._gc_checkpoint(cursor, stream.tell())
                if not stream.read(1):
                    manifest.unlink()
                    self._gc_checkpoint(cursor, 0)

    def _gc_checkpoint(self, cursor: Path, offset: int) -> None:
        fd, name = tempfile.mkstemp(prefix='.gc-state-', dir=self.root)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write(str(offset))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, cursor)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(name).unlink(missing_ok=True)
