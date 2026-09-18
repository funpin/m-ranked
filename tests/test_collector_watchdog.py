from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "operations/scripts/collector-watchdog.sh"


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def test_watchdog_uses_platform_thresholds_and_accounts_for_missing_history(
    tmp_path: Path,
) -> None:
    log = tmp_path / "systemctl.log"
    _executable(tmp_path / "systemctl", """#!/usr/bin/env bash
set -eu
case "$1" in
  is-active) exit 0 ;;
  show) echo 1 ;;
  restart) echo "$2" >> "$WATCHDOG_TEST_LOG" ;;
  *) exit 2 ;;
esac
""")
    _executable(tmp_path / "docker", """#!/usr/bin/env bash
set -eu
case "$*" in
  *platform=telegram*) echo 5 ;;
  *platform=vk*) echo never ;;
  *platform=max*) echo 46 ;;
  *platform=rutube*) echo 60 ;;
  *) exit 2 ;;
esac
""")
    environment = os.environ.copy()
    environment.update({
        "PATH": f"{tmp_path}:{environment['PATH']}",
        "WATCHDOG_TEST_LOG": str(log),
        "WATCHDOG_TEST_MONOTONIC_SECONDS": "3600",
    })

    result = subprocess.run(
        [str(SCRIPT)], env=environment, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr

    assert log.read_text(encoding="utf-8").splitlines() == [
        "m-ranked-target-collector@vk.service",
        "m-ranked-target-collector@max.service",
    ]
    assert "collector rutube progress age 60m is below 90m" in result.stdout


def test_watchdog_does_not_use_snapshot_freshness_as_liveness() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "collection_account_result" in text
    assert "publication_metric_snapshot" not in text
    assert "PLATFORMS=(telegram vk max rutube)" in text
    assert "--file=-" in text
    assert "--command" not in text
