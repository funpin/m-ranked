"""Synthetic local rehearsal authentication; no production credentials are read."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess


def bcrypt_hash(password: str, *, java: str, repository: Path) -> str:
    jars = sorted(repository.glob("org/springframework/security/spring-security-crypto/*/spring-security-crypto-*.jar"))
    if not jars:
        raise RuntimeError("Build the backend first to resolve its pinned security dependency")
    result = subprocess.run([java, "--class-path", str(jars[-1]), str(Path(__file__).with_name("AdminFixturePassword.java"))],
                            env=os.environ | {"MRANKED_FIXTURE_PASSWORD": password}, capture_output=True, text=True, check=True)
    value = result.stdout.strip()
    if not value.startswith("{bcrypt}$2"):
        raise RuntimeError("Invalid fixture password encoding")
    return value
