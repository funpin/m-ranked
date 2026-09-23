#!/usr/bin/env python3
"""Fail when deploy examples, units and runtime environment readers drift."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_DIR = ROOT / "operations" / "env"
SYSTEMD_DIR = ROOT / "operations" / "systemd"

RUNTIME_DIRS = (
    ROOT / "api",
    ROOT / "collector_runtime",
    ROOT / "collector_target",
    ROOT / "transfer_ingest",
    ROOT / "anomaly_analysis",
)
HELPERS = {"_int", "_float", "_bool", "_bounded", "_environment_or_file", "_flag"}
DYNAMIC = {
    *(f"{prefix}_DB_{suffix}" for prefix in ("API_READ", "API_WRITE_ADMIN", "OUTBOX_WORKER")
      for suffix in ("HOST", "PORT", "NAME", "USER", "PASSWORD", "PASSWORD_FILE")),
    *(f"INTEGRATION_{platform}" for platform in ("TELEGRAM", "VK", "MAX", "RUTUBE")),
    *(f"COLLECTOR_{platform}_POLL_INTERVAL_SECONDS"
      for platform in ("TELEGRAM", "VK", "MAX", "RUTUBE")),
    "ADMIN_AUTH_USERS", "ADMIN_AUTH_USERS_FILE",
    "ADMIN_CSRF_SECRET", "ADMIN_CSRF_SECRET_FILE",
}
# Supported compatibility inputs must remain absent from deployment examples.
DEPRECATED = {"DATABASE_URL", "COLLECTOR_POLL_INTERVAL_SECONDS"}
EXTERNAL_READERS = {"NEXT_TELEMETRY_DISABLED"}
# Secret values use credentials, while these direct alternatives remain code-level
# compatibility inputs and intentionally have no public value example.
CREDENTIAL_ONLY = {
    "API_READ_DB_PASSWORD", "API_WRITE_ADMIN_DB_PASSWORD",
    "OUTBOX_WORKER_DB_PASSWORD", "ADMIN_AUTH_USERS", "ADMIN_CSRF_SECRET",
    "TELEGRAM_API_ID", "TELEGRAM_API_HASH", "CHANNELS", "VK_ACCESS_TOKEN",
    "MAX_USER_PHONE", "TRANSFER_INGEST_CERTIFICATE",
    "TRANSFER_INGEST_PRIVATE_KEY", "TRANSFER_INGEST_CA_BUNDLE",
}
# One-off operator tools read these from the operator's shell: no unit injects
# them and a DSN carries a password, so no example exists either.
OPERATOR_TOOL_ONLY = {"ANOMALY_REFERENCE_DATABASE_URL"}


def example_values() -> dict[str, tuple[str, Path]]:
    result: dict[str, tuple[str, Path]] = {}
    for path in sorted(ENV_DIR.glob("*.env.example")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                raise ValueError(f"{path.relative_to(ROOT)}: invalid variable {name!r}")
            result[name] = (value, path)
    return result


def environment_readers() -> set[str]:
    names: set[str] = set(DYNAMIC)
    for directory in RUNTIME_DIRS:
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
                    if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                        names.add(node.slice.value)
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                function = ast.unparse(node.func)
                candidates = node.args[:1]
                if function.split(".")[-1] in HELPERS:
                    candidates = node.args
                if function in {"os.getenv", "os.environ.get"} or function.split(".")[-1] in HELPERS:
                    for candidate in candidates:
                        if (
                            isinstance(candidate, ast.Constant)
                            and isinstance(candidate.value, str)
                            and re.fullmatch(r"[A-Z][A-Z0-9_]*", candidate.value)
                        ):
                            names.add(candidate.value)
    return names


def unit_environment() -> set[str]:
    names: set[str] = set()
    for path in SYSTEMD_DIR.rglob("*"):
        if not path.is_file():
            continue
        for match in re.finditer(r"(?m)^Environment=(?:\"?)([A-Z][A-Z0-9_]*)=", path.read_text(encoding="utf-8")):
            names.add(match.group(1))
    return names


def check_environment_files(errors: list[str]) -> None:
    special = {
        "collector-%i.env": [f"collector-{p}.env.example" for p in ("telegram", "vk", "max", "rutube")],
        "api-profile.env": ["api-profile-b.env.example"],
        "collector-profile.env": ["collector-profile-b.env.example"],
    }
    for path in SYSTEMD_DIR.glob("*.service"):
        text = path.read_text(encoding="utf-8")
        for raw in re.findall(r"(?m)^EnvironmentFile=-?([^\s]+)", text):
            basename = Path(raw).name
            expected = special.get(basename, [f"{basename}.example"])
            for name in expected:
                if not (ENV_DIR / name).is_file():
                    errors.append(f"{path.name}: missing operations/env/{name}")


def check_credentials(errors: list[str]) -> None:
    inventory = (ENV_DIR / "CREDENTIALS.md").read_text(encoding="utf-8")
    for path in SYSTEMD_DIR.rglob("*"):
        if not path.is_file():
            continue
        for source in re.findall(r"(?m)^LoadCredential=[^:]+:([^\s]+)", path.read_text(encoding="utf-8")):
            basename = Path(source).name.replace("%i", "<platform>")
            if basename not in inventory:
                errors.append(f"{path.relative_to(ROOT)}: undocumented credential {basename}")


def main() -> int:
    errors: list[str] = []
    examples = example_values()
    code = environment_readers()
    injected = unit_environment()
    covered = set(examples) | injected | CREDENTIAL_ONLY | DEPRECATED | OPERATOR_TOOL_ONLY

    for name in sorted(code - covered):
        errors.append(f"runtime variable has no example/unit/credential: {name}")

    searchable_suffixes = {".py", ".sh", ".mjs", ".js", ".ts", ".tsx", ".service", ".target"}
    searchable = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for directory in (*RUNTIME_DIRS, ROOT / "operations" / "scripts", SYSTEMD_DIR, ROOT / "frontend")
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in searchable_suffixes and "node_modules" not in path.parts
    )
    for name, (value, path) in sorted(examples.items()):
        if name not in searchable and name not in code and name not in injected and name not in EXTERNAL_READERS:
            errors.append(f"{path.relative_to(ROOT)}: example variable is not read: {name}")
        if re.search(r"(?:PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_HASH)$", name):
            if value and value.lower() not in {"true", "false"} and not value.startswith("REPLACE_"):
                errors.append(f"{path.relative_to(ROOT)}: secret-like {name} must be blank or placeholder")

    check_environment_files(errors)
    check_credentials(errors)

    for path in (ENV_DIR / "redis.acl.example", ENV_DIR / "redis-url.credential.example"):
        text = path.read_text(encoding="utf-8")
        if "REPLACE_WITH_RANDOM_PASSWORD" not in text:
            errors.append(f"{path.relative_to(ROOT)}: credential example must use placeholder")
    if any(ENV_DIR.rglob("*.key")) or any(ENV_DIR.rglob("*.pem")):
        errors.append("operations/env must not contain generated keys or PEM files")

    if errors:
        print("runtime configuration check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"runtime configuration check passed: {len(code)} readers, {len(examples)} example variables")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
