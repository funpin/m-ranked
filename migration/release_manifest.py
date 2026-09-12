"""Exact final-schema and source provenance for rehearsals and releases."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
FINAL_SCHEMA = ROOT / "backend/src/main/resources/db/final-schema.sql"


def schema_manifest(path: Path = FINAL_SCHEMA) -> dict:
    """Return the single immutable database contract artifact."""
    if path.is_dir():
        path = path.parent / "final-schema.sql" if path.name == "migration" else path / "final-schema.sql"
    if path.is_symlink() or not path.is_file():
        raise ValueError("final schema must be a regular file")
    data = path.read_bytes()
    if not data:
        raise ValueError("final schema is empty")
    return {
        "contract": "storage-publisher-final-2026-09-08-r4",
        "script": path.name,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def flyway_manifest(directory: Path = FINAL_SCHEMA.parent) -> list[dict]:
    """Compatibility envelope for retired rehearsal report readers.

    Runtime and deploy code must use :func:`schema_manifest`. This adapter emits
    one record for old evidence JSON shapes; it does not describe migrations.
    """
    manifest = schema_manifest(directory)
    data_path = FINAL_SCHEMA if directory == FINAL_SCHEMA.parent else (
        directory.parent / "final-schema.sql" if directory.name == "migration"
        else directory / "final-schema.sql"
    )
    checksum = 0
    for line in data_path.read_text(encoding="utf-8-sig").splitlines():
        checksum = zlib.crc32(line.encode("utf-8"), checksum)
    if checksum >= 2**31:
        checksum -= 2**32
    return [{
        "version": "1",
        "script": manifest["script"],
        "checksum": checksum,
        "sha256": manifest["sha256"],
        "success": True,
    }]


def release_identity(root: Path = ROOT) -> dict:
    """Hash tracked and untracked runtime files, excluding generated evidence.

    This identifies a working-tree rehearsal without pretending it is an approved
    immutable production deployment. The file list is returned for reproduction.
    """
    packaged = root/'SHA256SUMS'
    if packaged.exists():
        if packaged.is_symlink() or not packaged.is_file():
            raise ValueError('release checksum manifest must be a regular file')
        raw = packaged.read_bytes()
        if not raw or not all(re.fullmatch(rb'[0-9a-f]{64} [ *][^\x00\r\n]+',line) for line in raw.splitlines()):
            raise ValueError('invalid packaged release checksum manifest')
        # Privileged deploy/preflight verifies the complete protected tree. The
        # bridge binds its evidence to those exact manifest bytes without needing
        # a .git directory or inventing a production approval.
        return {'kind':'packaged-release','releaseId':root.name,
                'sourceManifestSha256':hashlib.sha256(raw).hexdigest(),'productionApproved':False}
    query = subprocess.run(["git","ls-files","--cached","--others","--exclude-standard","-z"],
                           cwd=root,capture_output=True,check=True).stdout
    prefixes = ("app/","backend/","collector_target/","contracts/","frontend/","migration/bridge/",
                "migration/reverse_sync_format.py","migration/release_manifest.py","migration/integration/","operations/","infra/")
    files = []
    for name in sorted(set(query.decode().strip("\0").split("\0"))):
        path = root/name
        if not name.startswith(prefixes) or not path.is_file():
            continue
        # Extension filters silently missed executable entrypoints, .mjs/.mts,
        # properties and static assets. Bind every shipped source file, while
        # generated evidence must not change the release merely by running tests.
        if any(part in {"node_modules","target","test-results","evidence","reports",".next","__pycache__"}
               or part.endswith("-evidence") or part.startswith(".next-")
               for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise ValueError(f"runtime manifest refuses symbolic link: {name}")
        files.append({"path":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
    body = json.dumps(files,sort_keys=True,separators=(",", ":")).encode()
    head = subprocess.run(["git","rev-parse","HEAD"],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
    return {"kind":"local-working-tree","gitHead":head,"sourceManifestSha256":hashlib.sha256(body).hexdigest(),
            "productionApproved":False,"files":files}
