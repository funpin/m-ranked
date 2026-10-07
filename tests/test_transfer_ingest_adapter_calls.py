"""Приёмник вызывает у адаптера только существующие методы.

Уборка в главном цикле ловит любое исключение, чтобы не ронять приём, — и
06.10 вызов метода, по ошибке положенного в класс отправителя, полгода
тихо писал бы «prune failed class=AttributeError», не удаляя квитанций.
"""
from __future__ import annotations

import ast
from pathlib import Path

from collector_target.transfer import PostgresDataAdapter

MAIN = Path(__file__).resolve().parents[1] / "transfer_ingest" / "__main__.py"


def test_every_adapter_method_the_ingest_loop_calls_exists():
    called = {node.attr for node in ast.walk(ast.parse(MAIN.read_text()))
              if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "adapter"}
    assert {"release_applied_payloads", "prune_receipts"} <= called
    adapter = PostgresDataAdapter(object())
    assert not {name for name in called if not hasattr(adapter, name)}
