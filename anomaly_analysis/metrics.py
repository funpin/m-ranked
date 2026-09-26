"""Метрики анализа в textfile node_exporter: атомарная запись, метки только из кода."""
from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile
from typing import Iterable, Mapping

PREFIX = "mranked_anomaly_"
_NAME = re.compile(r"[a-z_][a-z0-9_]*")


def write_textfile(path: Path | None, samples: Iterable[tuple[str, str, Mapping[str, str], float]]) -> None:
    """Записать образцы (имя без префикса, тип, метки, значение) одним заменяемым файлом."""
    if path is None:
        return
    lines: list[str] = []
    typed: set[str] = set()
    for name, kind, labels, value in samples:
        if not _NAME.fullmatch(name) or any(not _NAME.fullmatch(key) for key in labels):
            raise ValueError(f"invalid metric name {name!r}")
        full = PREFIX + name
        if full not in typed:
            lines.append(f"# TYPE {full} {kind}")
            typed.add(full)
        rendered = ",".join(f'{key}="{labels[key]}"' for key in sorted(labels))
        lines.append(f"{full}{{{rendered}}} {value:.12g}" if rendered else f"{full} {value:.12g}")
    if not path.is_absolute() or not path.parent.is_dir() or path.is_symlink():
        raise ValueError("metrics path must be a provisioned absolute regular destination")
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), 0o640)
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
