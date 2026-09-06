"""Retrievable, content-addressed sanitized evidence with fail-closed reads.

The directory must live on durable service storage. Publishing the object before
PG commit makes a crash leave an unreferenced object, never a dangling committed
reference. Exact retry safely reuses the immutable object. Retention is enforced
at retrieval using the authoritative PG purge_after value.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import tempfile
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
                      orphan_grace: timedelta = timedelta(days=7)) -> int:
        """Bounded physical expiry; uses the collector's exact per-hash DB lock.

        Use a maintenance connection and the same durable directory. A crash
        after unlink can leave only expired metadata; new ingestion republishes
        its object while holding the same lock before committing its reference.
        """
        if max_objects < 1 or max_objects > 100_000 or orphan_grace < timedelta(days=7):
            raise ValueError("unsafe evidence purge bounds")
        now = utc(now, "now")
        self._directory()
        removed = 0
        examined = 0
        with os.scandir(self.root) as entries:
            for entry in entries:
                if examined >= max_objects:
                    break
                if not re.fullmatch(r"[0-9a-f]{64}\.json", entry.name) or not entry.is_file(follow_symlinks=False):
                    continue
                examined += 1
                digest = entry.name[:-5]
                uri = (self.root / entry.name).as_uri()
                with connection.transaction():
                    connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("raw-evidence:" + digest,))
                    result = connection.execute(
                        "SELECT max(purge_after) FROM ingest.raw_payload WHERE external_ref=%s", (uri,)
                    ).fetchone()
                    latest = next(iter(result.values())) if isinstance(result, dict) else result[0]
                    if latest is not None and latest > now:
                        continue
                    if latest is None and datetime.fromtimestamp(entry.stat(follow_symlinks=False).st_mtime, now.tzinfo) > now - orphan_grace:
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
