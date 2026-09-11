"""Неизменяемые исходные JSON-команды, сохранённые отдельно от БД."""
from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path


def persist_admin_envelope(original: str) -> str:
    payload = original.encode("utf-8")
    if len(payload) > 131072:
        raise ValueError("IDENTITY_RECEIPT_TOO_LARGE")
    directory = (Path(os.environ.get("MRANKED_IDENTITY_RECEIPT_DIR",
                                     "data/identity-receipts")) / "admin").absolute()
    if any(path.is_symlink() for path in (directory, *directory.parents)):
        raise ValueError("IDENTITY_RECEIPT_DIRECTORY_UNSAFE")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.stat()
    mode = stat.S_IMODE(info.st_mode)
    if not stat.S_ISDIR(info.st_mode) or mode not in (0o700, 0o2750) or info.st_uid != os.geteuid():
        raise ValueError("IDENTITY_RECEIPT_DIRECTORY_UNSAFE")
    file_mode = 0o440 if mode == 0o2750 else 0o400
    digest = hashlib.sha256(payload).hexdigest()
    descriptor, name = tempfile.mkstemp(prefix=".identity-", dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fchmod(stream.fileno(), file_mode)
            os.fsync(stream.fileno())
        destination = directory / f"{digest}.json"
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            existing = destination.read_bytes()
            existing_info = destination.stat(follow_symlinks=False)
            if (existing != payload or not stat.S_ISREG(existing_info.st_mode)
                    or stat.S_IMODE(existing_info.st_mode) != file_mode
                    or existing_info.st_uid != info.st_uid
                    or (file_mode == 0o440 and existing_info.st_gid != info.st_gid)):
                raise ValueError("IDENTITY_RECEIPT_FILE_UNSAFE")
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return digest
    finally:
        temporary.unlink(missing_ok=True)
