#!/usr/bin/env python3
"""Check repository-relative Markdown links used by architecture and runbooks."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
SCOPES = (ROOT / "docs" / "architecture", ROOT / "operations" / "runbooks", ROOT / "operations" / "env")
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    broken: list[str] = []
    checked = 0
    for scope in SCOPES:
        for document in scope.rglob("*.md"):
            for raw in LINK.findall(document.read_text(encoding="utf-8")):
                target = raw.split(maxsplit=1)[0].strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "file:")):
                    continue
                path_text = unquote(target.split("#", 1)[0])
                path_text = re.sub(r":\d+$", "", path_text)
                if not path_text:
                    continue
                checked += 1
                resolved = (ROOT / path_text.lstrip("/")) if path_text.startswith("/") else (document.parent / path_text)
                if not resolved.resolve().exists():
                    broken.append(f"{document.relative_to(ROOT)} -> {target}")
    if broken:
        print("documentation link check failed:", file=sys.stderr)
        for item in broken:
            print(f"- {item}", file=sys.stderr)
        return 1
    print(f"documentation link check passed: {checked} local links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
