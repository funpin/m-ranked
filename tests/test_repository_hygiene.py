"""Release tree must contain templates, never deployable credentials or dumps."""
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BLOCKED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".dump", ".sql.gz",
                    ".session", ".session.db", ".sqlite")


def _tracked() -> tuple[str, ...]:
    output = subprocess.check_output(
        ["git", "ls-files"], cwd=ROOT, text=True,
    )
    return tuple(line for line in output.splitlines() if line)


def test_templates_are_allowed_but_runtime_secrets_and_dumps_are_not_tracked() -> None:
    tracked = _tracked()
    assert any(path.endswith(".env.example") for path in tracked)
    forbidden = []
    for path in tracked:
        if not (ROOT / path).exists():
            continue
        name = Path(path).name.casefold()
        if name.endswith(".env") and not name.endswith(".env.example"):
            forbidden.append(path)
        if name.endswith(BLOCKED_SUFFIXES) or "private-key" in name:
            forbidden.append(path)
    assert forbidden == []
