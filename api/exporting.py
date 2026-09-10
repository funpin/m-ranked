"""Общий ограничитель и файловая подготовка CSV до отправки заголовков."""
from __future__ import annotations

import asyncio
import csv
import os
import tempfile
import time
import unicodedata
from collections import deque
from collections.abc import AsyncIterable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ApiProblem


class ExportLimit(ApiProblem):
    def __init__(self, detail: str) -> None:
        super().__init__(429, "Too Many Requests", detail,
                         "urn:m-ranked:problem:export-limit", headers={"Retry-After": "60"})


@dataclass
class ExportQuota:
    requests_per_minute: int
    generators: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))
    artifacts: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(4))
    recent: deque[float] = field(default_factory=deque)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def acquire(self) -> None:
        async with self.lock:
            now = time.monotonic()
            while self.recent and now-self.recent[0] > 60:
                self.recent.popleft()
            if len(self.recent) >= self.requests_per_minute:
                raise ExportLimit("Превышен минутный лимит экспорта")
            if self.generators.locked() or self.artifacts.locked():
                raise ExportLimit("Нет свободного слота подготовки экспорта")
            self.recent.append(now)
            await self.generators.acquire()
            await self.artifacts.acquire()

    def generated(self) -> None:
        self.generators.release()

    def failed(self) -> None:
        self.generators.release()
        self.artifacts.release()

    def downloaded(self) -> None:
        self.artifacts.release()


def modern_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    index = 0
    while index < len(text) and (text[index].isspace()
                                 or unicodedata.category(text[index]) == "Cc"):
        index += 1
    if index < len(text) and text[index] in "=+-@":
        return "'" + text
    return text


def write_csv(path: Path, headers: Sequence[str], rows: Iterable[Sequence[Any]], *,
              max_rows: int, max_bytes: int, max_seconds: int,
              transform: Callable[[Any], str] = modern_cell) -> tuple[int, int]:
    started = time.monotonic()
    count = 0
    with path.open("w", encoding="utf-8", newline="") as output:
        class BoundedText:
            def __init__(self) -> None:
                self.bytes = 0

            def write(self, value: str) -> int:
                self.bytes += len(value.encode("utf-8"))
                if self.bytes > max_bytes:
                    raise ExportLimit("Экспорт превышает допустимый размер")
                return output.write(value)

        bounded = BoundedText()
        writer = csv.writer(bounded, lineterminator="\r\n")
        writer.writerow([transform(value) for value in headers])
        for row in rows:
            count += 1
            if count > max_rows:
                raise ExportLimit("Экспорт превышает допустимое число строк")
            if time.monotonic()-started > max_seconds:
                raise ExportLimit("Экспорт не уложился в допустимое время")
            writer.writerow([transform(value) for value in row])
    size = path.stat().st_size
    if size > max_bytes:
        raise ExportLimit("Экспорт превышает допустимый размер")
    return count, size


def temporary_csv(prefix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=".csv")
    os.close(descriptor)
    return Path(name)


async def write_csv_async(path: Path, headers: Sequence[str], rows: AsyncIterable[Sequence[Any]], *,
                          max_rows: int, max_bytes: int, max_seconds: int,
                          transform: Callable[[Any], str] = modern_cell) -> tuple[int, int]:
    started = time.monotonic()
    count = 0
    with path.open("w", encoding="utf-8", newline="") as output:
        class BoundedText:
            def __init__(self) -> None:
                self.bytes = 0

            def write(self, value: str) -> int:
                self.bytes += len(value.encode("utf-8"))
                if self.bytes > max_bytes:
                    raise ExportLimit("Экспорт превышает допустимый размер")
                return output.write(value)

        bounded = BoundedText()
        writer = csv.writer(bounded, lineterminator="\r\n")
        writer.writerow([transform(value) for value in headers])
        async for row in rows:
            count += 1
            if count > max_rows:
                raise ExportLimit("Экспорт превышает допустимое число строк")
            if time.monotonic()-started > max_seconds:
                raise ExportLimit("Экспорт не уложился в допустимое время")
            writer.writerow([transform(value) for value in row])
    return count, path.stat().st_size
