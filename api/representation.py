"""Версия представления: отпечаток контракта и идентичности сборки.

Кэш и валидаторы ETag ключуются не только номером ревизии данных, но и версией
представления. Правка кода меняет тело ответа при той же ревизии в базе,
поэтому в отпечаток входит и идентичность сборки.
"""
from __future__ import annotations

import functools
import hashlib
import os
import pathlib

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "contracts/openapi/m-ranked-v1.yaml"
BUILD_INFO = pathlib.Path(__file__).resolve().parent / "build_info.txt"


def _build_identity() -> bytes:
    explicit = os.environ.get("APP_BUILD_ID")
    if explicit:
        return explicit.encode("utf-8")
    if BUILD_INFO.exists():
        return BUILD_INFO.read_bytes()
    # Окружение разработчика: сборки нет, идентичность берём от контракта.
    return b"development"


@functools.cache
def representation_version() -> str:
    if not CONTRACT.exists():
        raise RuntimeError(f"контракт публичного API отсутствует: {CONTRACT}")
    digest = hashlib.sha256()
    digest.update(CONTRACT.read_bytes())
    digest.update(b"\x00")
    digest.update(_build_identity())
    return digest.hexdigest()
