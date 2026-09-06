"""Durable original identity inputs, separate from expiring provider payloads.

Only a committed revision/command digest authorizes an object. Directory listings
and unreferenced files never establish source authority.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .normalize import canonical_json


class IdentityEvidenceUnavailable(ValueError):
    pass


def configured_root() -> Path:
    return Path(os.environ.get("MRANKED_IDENTITY_RECEIPT_DIR", "data/identity-receipts")).absolute()


class IdentityEvidenceStore:
    MAX_BYTES = 131072

    def __init__(self, directory: Path):
        self.directory = directory.absolute()

    def _check_directory(self):
        if any(path.is_symlink() for path in (self.directory,*self.directory.parents)):
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_DIRECTORY_UNSAFE")
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_DIRECTORY_UNAVAILABLE")
        # Shared readers need an explicitly provisioned setgid directory.
        # Merely making an arbitrary directory/file group-readable is unsafe.
        info = self.directory.stat()
        if stat.S_IMODE(info.st_mode) not in (0o700, 0o2750):
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_DIRECTORY_UNSAFE")
        return info

    @staticmethod
    def _file_mode(directory_info):
        return 0o440 if stat.S_IMODE(directory_info.st_mode) == 0o2750 else 0o400

    def _check_file(self, info, directory_info):
        shared = self._file_mode(directory_info) == 0o440
        if (not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != self._file_mode(directory_info)
                or info.st_uid != directory_info.st_uid
                or (shared and info.st_gid != directory_info.st_gid)
                or info.st_size > self.MAX_BYTES):
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_FILE_UNSAFE")

    def put(self, value: object) -> str:
        payload = canonical_json(value).encode("utf-8")
        if len(payload) > self.MAX_BYTES:
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_TOO_LARGE")
        if any(path.is_symlink() for path in (self.directory,*self.directory.parents)):
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_DIRECTORY_UNSAFE")
        missing = []
        ancestor = self.directory
        while not ancestor.exists():
            missing.append(ancestor)
            ancestor = ancestor.parent
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for created in reversed(missing):
            for path in (created,created.parent):
                descriptor=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
                try:os.fsync(descriptor)
                finally:os.close(descriptor)
        directory_info = self._check_directory()
        if directory_info.st_uid != os.geteuid():
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_WRITER_OWNER_MISMATCH")
        digest = hashlib.sha256(payload).hexdigest()
        descriptor, name = tempfile.mkstemp(prefix=".identity-", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fchmod(stream.fileno(), self._file_mode(directory_info))
                self._check_file(os.fstat(stream.fileno()), directory_info)
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.directory / (digest + ".json"), follow_symlinks=False)
            except FileExistsError:
                self.read(digest)
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return digest

    def read(self, digest: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_DIGEST_INVALID")
        directory_info = self._check_directory()
        try:
            descriptor = os.open(self.directory / (digest + ".json"), os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                self._check_file(info, directory_info)
                payload = stream.read(self.MAX_BYTES + 1)
        except OSError as error:
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_MISSING") from error
        if len(payload) > self.MAX_BYTES or hashlib.sha256(payload).hexdigest() != digest:
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_HASH_MISMATCH")
        try:
            value = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_ENCODING_INVALID") from error
        if not isinstance(value, dict):
            raise IdentityEvidenceUnavailable("IDENTITY_RECEIPT_SCHEMA_INVALID")
        return value


def accepted_admin_input(connection, revision: int, correlation_id) -> dict | None:
    """Bind original input bytes to one committed successful command.

    The response supplies only acceptance and allocated-ID control. Never return
    its state payload: expected identity values must come from the source file.
    """
    from psycopg.rows import dict_row
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("""SELECT request_digest,created_at,actor,correlation_id,
            response->>'targetId' AS target_id,response->>'outcome' AS outcome
            FROM ops_and_admin.catalog_command_receipt WHERE correlation_id=%s
              AND response->>'datasetRevision'=%s LIMIT 2""", (correlation_id,str(revision)))
        rows=cursor.fetchall()
    if not rows:
        return None
    if len(rows)!=1 or rows[0]["outcome"]!="succeeded":
        raise IdentityEvidenceUnavailable("IDENTITY_ADMIN_ACCEPTANCE_INVALID")
    row=rows[0]
    original=IdentityEvidenceStore(configured_root()/"admin").read(row["request_digest"])
    if set(original)!={"action","target","expected","body"} or not isinstance(original["body"],dict) or not isinstance(original["action"],str):
        raise IdentityEvidenceUnavailable("IDENTITY_ADMIN_SOURCE_INVALID")
    return {"input":original,"sha256":row["request_digest"],"target_id":row["target_id"],
        "accepted_at":row["created_at"],"actor":row["actor"],"correlation_id":str(row["correlation_id"]),"revision":revision}
