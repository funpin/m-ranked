"""Граница модуля анализа: он не знает об API, сборщиках и переносе, они — о нём.

API читает таблицы анализа через SQL, а не через импорт пакета: иначе падение
или тяжёлая зависимость анализа (numpy, scipy) утянули бы за собой API.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = "anomaly_analysis"
NEIGHBOURS = ("api", "collector_target", "collector_runtime", "transfer_ingest")


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _sources(package: str) -> list[Path]:
    files = sorted((ROOT / package).rglob("*.py"))
    assert files, package
    return files


def test_analysis_does_not_import_its_neighbours() -> None:
    violations = [
        f"{path.relative_to(ROOT)} → {root}"
        for path in _sources(ANALYSIS)
        for root in sorted(_imported_roots(path) & set(NEIGHBOURS))
    ]
    assert not violations, violations


@pytest.mark.parametrize("package", NEIGHBOURS)
def test_neighbours_do_not_import_analysis(package: str) -> None:
    violations = [str(path.relative_to(ROOT)) for path in _sources(package)
                  if ANALYSIS in _imported_roots(path)]
    assert not violations, violations
