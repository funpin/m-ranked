#!/usr/bin/env python3
"""Аргументы pip-audit --ignore-vuln для одного lock-файла из security/vex.json.

Исключение действует только для того lock-файла, который указан в его
affects, и только до даты expires. Просроченное или неполное исключение —
ошибка: выпуск снова блокируется (docs/architecture/security/dependency-policy.md).

    pip-audit -r requirements/py311/collector.lock \\
        $(python3 operations/scripts/vex_ignores.py requirements/py311/collector.lock)
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys

VEX = pathlib.Path(__file__).resolve().parents[2] / "docs" / "architecture" / "security" / "vex.json"
REQUIRED = ("owner", "expires", "test")


def ignores(lock: str, today: datetime.date, vex: pathlib.Path = VEX) -> list[str]:
    document = json.loads(vex.read_text(encoding="utf-8"))
    found: list[str] = []
    for entry in document.get("vulnerabilities", []):
        properties = {item["name"]: item["value"] for item in entry.get("properties", [])}
        missing = [name for name in REQUIRED if not properties.get(name)]
        if missing or not entry.get("analysis", {}).get("detail"):
            raise ValueError(f"{entry.get('id')}: в исключении нет {missing or ['analysis.detail']}")
        if datetime.date.fromisoformat(properties["expires"]) < today:
            raise ValueError(f"{entry['id']}: исключение истекло {properties['expires']}")
        if lock in {item["ref"] for item in entry.get("affects", [])}:
            found.append(entry["id"])
    return found


def main() -> int:
    try:
        found = ignores(sys.argv[1], datetime.date.today())
    except (IndexError, ValueError, KeyError) as error:
        print(f"vex.json: {error}", file=sys.stderr)
        return 1
    print(" ".join(f"--ignore-vuln {item}" for item in found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
