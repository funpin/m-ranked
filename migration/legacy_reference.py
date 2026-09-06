"""Explicit external legacy release for migration oracles; never an app runtime."""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import sys
from types import ModuleType


class LegacyReferenceUnavailable(RuntimeError):
    pass


def reference_root() -> Path:
    value = os.environ.get("MRANKED_LEGACY_REFERENCE_ROOT")
    if not value:
        raise LegacyReferenceUnavailable(
            "Legacy UI was removed from alpha. Set MRANKED_LEGACY_REFERENCE_ROOT "
            "to a separate trusted legacy checkout for migration verification; "
            "see migration/legacy-reference.md."
        )
    root = Path(value).resolve()
    if root == Path(__file__).resolve().parents[1] or not (root / "app/web/app.py").is_file():
        raise LegacyReferenceUnavailable("MRANKED_LEGACY_REFERENCE_ROOT must contain a separate legacy release")
    return root


def reference_metadata() -> dict:
    root = reference_root()
    digest = hashlib.sha256()
    for path in sorted((root / "app").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {"kind": "external-legacy-reference", "appTreeSha256": digest.hexdigest()}


def create_app(*args, **kwargs):
    root = reference_root()
    # Isolate all relative imports from the current app/ collector package.
    name = "_mranked_legacy_" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [str(root / "app")]
        package.__package__ = name
        sys.modules[name] = package
    return importlib.import_module(name + ".web.app").create_app(*args, **kwargs)
