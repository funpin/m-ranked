"""Недостижимость CVE soupsieve, записанная в docs/architecture/security/vex.json.

Исключение для requirements/py311/collector.lock (soupsieve 2.10 на Python 3.11.2
Сервера 1) держится на трёх условиях, которые проверяет этот файл: селекторы
сборщика — строковые константы, без псевдоклассов и не больше одного
комбинатора потомка в каждой части. Нарушение любого делает уязвимый путь
достижимым — тогда исключение нужно снимать и обновлять Python на Сервере 1.
"""
from __future__ import annotations

import ast
import datetime
import importlib.util
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGES = ("collector_runtime", "collector_target")
METHODS = {"select", "select_one"}


def _selector_calls() -> list[tuple[str, ast.Call]]:
    calls = []
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if not re.search(r"^\s*(from|import) bs4\b", source, re.M):
                continue  # select() у объектов не из Beautiful Soup
            for node in ast.walk(ast.parse(source)):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in METHODS and node.args):
                    calls.append((f"{path.relative_to(ROOT)}:{node.lineno}", node))
    return calls


def _descendant_combinators(part: str) -> int:
    part = re.sub(r"\[[^\]]*\]", "[]", part.strip())
    part = re.sub(r"\s*([>+~])\s*", r"\1", part)
    return len(part.split()) - 1


def test_collector_selectors_exist():
    assert _selector_calls(), "сборщик больше не использует select(): проверьте, нужно ли исключение в vex.json"


@pytest.mark.parametrize("where,call", _selector_calls(), ids=lambda item: item if isinstance(item, str) else "")
def test_collector_selector_is_a_safe_constant(where, call):
    selector = call.args[0]
    assert isinstance(selector, ast.Constant) and isinstance(selector.value, str), \
        f"{where}: селектор не константа — CVE-2026-126191/126193 становятся достижимы"
    assert ":" not in selector.value, f"{where}: псевдокласс в селекторе (CVE-2026-126193)"
    for part in selector.value.split(","):
        assert _descendant_combinators(part) <= 1, \
            f"{where}: больше одного комбинатора потомка в «{part.strip()}» (CVE-2026-126190)"


def _vex_module():
    spec = importlib.util.spec_from_file_location("vex_ignores", ROOT / "operations/scripts/vex_ignores.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_vex_exceptions_are_scoped_valid_and_point_here():
    vex = _vex_module()
    today = datetime.date.today()
    assert vex.ignores("requirements/py311/collector.lock", today) == [
        "CVE-2026-126190", "CVE-2026-126191", "CVE-2026-126193"]
    assert vex.ignores("requirements/collector.lock", today) == []
    for entry in json.loads(vex.VEX.read_text(encoding="utf-8"))["vulnerabilities"]:
        test = {item["name"]: item["value"] for item in entry["properties"]}["test"]
        assert (ROOT / test).is_file()


def test_expired_vex_exception_blocks(tmp_path):
    vex = _vex_module()
    document = json.loads(vex.VEX.read_text(encoding="utf-8"))
    path = tmp_path / "vex.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="истекло"):
        vex.ignores("requirements/py311/collector.lock", datetime.date(2099, 1, 1), path)
