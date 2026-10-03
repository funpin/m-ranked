"""Verified Parquet cold-archive support.

Имена пакета подгружаются лениво: API и работник анализа читают только файлы
просмотра (browse.py, стандартная библиотека), а в их окружении нет pyarrow,
который нужен выгрузке Parquet (service.py, parquet.py).
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ArchiveResult",
    "ArchiveVerification",
    "ColdArchiveService",
    "MonthRange",
]
_HOMES = {"ArchiveResult": ".model", "ArchiveVerification": ".model", "MonthRange": ".model",
          "ColdArchiveService": ".service"}


def __getattr__(name: str) -> Any:
    if name not in _HOMES:
        raise AttributeError(name)
    return getattr(import_module(_HOMES[name], __name__), name)
