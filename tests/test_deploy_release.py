"""Проверка здоровья в operations/deploy/deploy-release.sh."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "operations" / "deploy" / "deploy-release.sh"


def _wait_healthy(page: str, commit: str = "abc123", tail: int = 5_000_000) -> int:
    """wait_healthy из скрипта под его же set -Eeuo pipefail; curl и sleep — заглушки."""
    function = re.search(r"^wait_healthy\(\) \{.*?^\}", SCRIPT.read_text(encoding="utf-8"), re.S | re.M)
    assert function, "в deploy-release.sh нет wait_healthy"
    program = f"""
set -Eeuo pipefail
MRANKED_API_URL=http://api MRANKED_WEB_URL=http://web
sleep() {{ :; }}
# GNU grep -q (как на сервере) выходит на первом совпадении и закрывает канал;
# grep из macOS дочитывает ввод, и без заглушки тест там бы не краснел.
grep() {{ command head -c 64 >/dev/null; return 0; }}
seq() {{ printf '1\\n2\\n'; }}
curl() {{
  case "${{@: -1}}" in
    # Как настоящий curl: пишет и после того, как читатель ушёл.
    http://web/) printf '%s' "$PAGE"; head -c "$TAIL" /dev/zero | tr '\\0' x ;;
    *) printf '{{"status":"UP"}}' ;;
  esac
}}
{function.group(0)}
wait_healthy {commit}
"""
    return subprocess.run(["bash", "-c", program], env={"PAGE": page, "TAIL": str(tail), "PATH": "/usr/bin:/bin"},
                          capture_output=True, text=True, timeout=30).returncode


def test_large_page_with_the_release_commit_is_healthy() -> None:
    # Метка в начале большой страницы: «curl | grep -q» под pipefail падал здесь
    # с кодом 23, хотя совпадение было (01.11.2026, ~370 КБ HTML).
    assert _wait_healthy("<html data-dpl-id=abc123 dpl=abc123>") == 0


def test_page_of_another_build_is_not_healthy() -> None:
    assert _wait_healthy("<html dpl=mranked-main-7e71cff>", tail=1000) == 1
