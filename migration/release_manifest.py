"""Exact schema and source provenance for local rehearsals and packaged releases."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import zlib

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "backend/src/main/resources/db/migration"


def flyway_manifest(directory: Path = MIGRATIONS) -> list[dict]:
    result = []
    paths = sorted(directory.glob("V*__*.sql"), key=lambda p: int(p.name.split("__")[0][1:]))
    for expected, path in enumerate(paths, 1):
        match = re.fullmatch(r"V([1-9][0-9]*)__.+\.sql", path.name)
        if not match or int(match[1]) != expected or path.is_symlink():
            raise ValueError("schema manifest must contain sequential regular V1..Vn files")
        data = path.read_bytes()
        # Flyway's CRC32 excludes line terminators and an optional UTF-8 BOM.
        checksum = 0
        for line in data.decode("utf-8-sig").splitlines():
            checksum = zlib.crc32(line.encode("utf-8"), checksum)
        if checksum >= 2**31:
            checksum -= 2**32
        result.append({"version":str(expected),"script":path.name,"checksum":checksum,
                       "sha256":hashlib.sha256(data).hexdigest(),"success":True})
    if not result:
        raise ValueError("empty schema manifest")
    return result


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
