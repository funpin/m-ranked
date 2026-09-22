"""Release tree must contain templates, never deployable credentials or dumps."""
from pathlib import Path
import re
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


def test_every_workflow_action_is_pinned_to_a_commit() -> None:
    """Подвижный тег действия отдаёт выполнение в CI чужому репозиторию."""
    unpinned = []
    for workflow in (ROOT / ".github/workflows").glob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().removeprefix("- ")
            if stripped.startswith("uses:"):
                reference = stripped.split("uses:", 1)[1].split("#", 1)[0].strip()
                _, _, version = reference.partition("@")
                if not re.fullmatch(r"[0-9a-f]{40}", version):
                    unpinned.append(f"{workflow.name}: {reference}")
    assert unpinned == []


def test_security_gates_stay_in_the_pipeline() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for tool in ("pip-audit", "pnpm audit", "semgrep", "gitleaks", "trivy config",
                 "trivy image", "cyclonedx-py", "cdxgen", "attest-build-provenance",
                 "--require-hashes"):
        assert tool in workflow, tool
    # Скачанные бинарники проверяются по контрольной сумме, а не «как есть».
    assert workflow.count("sha256sum --check --strict") == 3
    # Сканер секретов сначала обязан найти заведомый ключ.
    assert "канарейку" in workflow
    # Ни один шаг не оставляет в рабочем дереве токен GitHub.
    assert workflow.count("persist-credentials: false") == workflow.count("uses: actions/checkout@")
    assert "npx --yes" not in workflow


def test_production_dependencies_are_hash_locked() -> None:
    for name in ("api.lock", "collector.lock", "anomaly.lock", "tooling.lock"):
        lock = (ROOT / "requirements" / name).read_text(encoding="utf-8")
        pins = [line for line in lock.splitlines() if line and not line.startswith("#")]
        assert pins, name
        assert all("--hash=sha256:" in line or "==" in line for line in pins), name
        assert len([line for line in pins if "--hash=sha256:" in line]) == len(pins)//2
    for name in ("api", "collector", "anomaly"):
        body = (ROOT / f"infra/local/{name}.Dockerfile").read_text(encoding="utf-8")
        assert "--require-hashes" in body, name
        assert f"requirements/{name}.lock" in body, name
    # Зависимость из git собирается отдельно и не отключает проверку хешей.
    pymax = (ROOT / "requirements/pymax.txt").read_text(encoding="utf-8")
    assert "53103f0c8df32f36110cbe0bcbfc3ad82173808a" in pymax
    assert "git+" not in (ROOT / "requirements/collector.txt").read_text(encoding="utf-8")


def test_response_headers_carry_a_content_security_policy() -> None:
    headers = (ROOT / "operations/nginx/security-headers.conf").read_text(encoding="utf-8")
    assert "includeSubDomains" in headers
    # Политику для разметки выдаёт Next: у неё одноразовый nonce.
    proxy = (ROOT / "frontend/proxy.ts").read_text(encoding="utf-8")
    for directive in ("default-src 'self'", "object-src 'none'", "base-uri 'none'",
                      "frame-ancestors 'self'", "form-action 'self'", "'strict-dynamic'"):
        assert directive in proxy, directive
    assert "script-src ${script}" in proxy
    assert "'unsafe-eval'" in proxy and 'NODE_ENV === "development"' in proxy


def test_production_images_are_pinned_unprivileged_and_free_of_test_tooling() -> None:
    runtime = "".join((ROOT / name).read_text(encoding="utf-8")
                      for name in ("requirements/api.txt", "requirements/collector.txt"))
    for tool in ("pytest", "playwright", "jsonschema", "pyyaml"):
        assert tool not in runtime.casefold(), tool
    for dockerfile in (ROOT / "infra/local").glob("*.Dockerfile"):
        body = dockerfile.read_text(encoding="utf-8")
        assert re.search(r"^FROM \S+@sha256:[0-9a-f]{64}", body, re.MULTILINE), dockerfile.name
        assert re.search(r"^USER \S+", body, re.MULTILINE), dockerfile.name


def test_the_repository_root_stays_readable() -> None:
    """Корень — оглавление проекта, а не свалка.

    Набор файлов зависимостей рос по одному на среду выполнения; в корне им
    места нет, там остаётся одна привычная точка входа.
    """
    allowed = {
        ".dockerignore", ".editorconfig", ".env.example", ".gitignore",
        ".gitleaksignore", "AGENTS.md", "CONTRIBUTING.md", "Makefile", "README.md",
        "pyproject.toml", "requirements.txt",
    }
    present = {path for path in _tracked() if "/" not in path}
    assert present <= allowed, f"лишнее в корне: {sorted(present - allowed)}"
    assert (ROOT / "requirements.txt").read_text(encoding="utf-8").strip().endswith(
        "-r requirements/dev.txt")


def test_anomaly_metrics_migration_cannot_restore_the_removed_revision_barrier() -> None:
    migration = (ROOT / "db/migrations/0027_anomaly_metrics_live_revision.sql").read_text(
        encoding="utf-8",
    )
    body = migration.split("CREATE OR REPLACE FUNCTION", 1)[1]
    assert "analytics.latest_dataset_revision()" in body
    assert "latest_fully_published_dataset_revision()" not in body
