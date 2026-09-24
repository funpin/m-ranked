#!/usr/bin/env python3
"""Rotate only after a real restore receipt; retain last verified + newest."""
import hashlib
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
keep = int(sys.argv[2])
if not 1 <= keep <= 90:
    raise SystemExit("BACKUP_KEEP must be between 1 and 90")
files = sorted((p for p in root.iterdir() if re.fullmatch(r'mranked-[0-9]{8}T[0-9]{6}Z\.dump',p.name)
                and p.is_file() and not p.is_symlink()), reverse=True)
verified = []
for dump in files:
    receipt = dump.with_suffix('.restore-verified.json')
    if receipt.is_file() and not receipt.is_symlink():
        info = json.loads(receipt.read_text())
        if info.get('dump') != dump.name or info.get('restore_exit_code') != 0:
            raise SystemExit('invalid restore receipt')
        with dump.open('rb') as stream:
            sha = hashlib.sha256()
            while block := stream.read(1024 * 1024):
                sha.update(block)
            digest = sha.hexdigest()
        if info.get('sha256') != digest:
            raise SystemExit('restore receipt checksum mismatch')
        verified.append(dump)
        break
if not verified:
    print('rotation refused: no restore-verified copy; operator action required')
    raise SystemExit(75)
protected = set(files[:keep] + verified)
for dump in files:
    if dump not in protected:
        dump.unlink()
        dump.with_suffix('.restore-verified.json').unlink(missing_ok=True)
