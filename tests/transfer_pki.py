"""Disposable test PKI.

Certificates are generated with the ``openssl`` CLI into a temporary directory
so the repository never carries a key and the collector image never grows a
``cryptography`` dependency for a test-only need.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

import pytest


def require_openssl() -> str:
    path = shutil.which("openssl")
    if not path:
        pytest.skip("openssl CLI is required to build the disposable test PKI")
    return path


def _run(*args: str) -> None:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"openssl failed: {' '.join(args[:3])} -> {result.returncode}"
        )


@dataclass(frozen=True, slots=True)
class Identity:
    certificate: Path
    private_key: Path


@dataclass(frozen=True, slots=True)
class TestPki:
    root: Path
    ca_bundle: Path
    server: Identity

    def issue(self, name: str, common_name: str, *, san: str | None = None) -> Identity:
        return issue(self.root, name, common_name, ca=self.ca_bundle, san=san)


def _ca(root: Path, name: str) -> tuple[Path, Path]:
    key, cert = root / f"{name}.key", root / f"{name}.pem"
    _run(
        require_openssl(), "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(cert), "-days", "1",
        "-subj", f"/CN={name}",
        # OpenSSL 3 отказывается доверять CA без этих расширений.
        "-addext", "basicConstraints=critical,CA:TRUE",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
    )
    return key, cert


def issue(
    root: Path,
    name: str,
    common_name: str,
    *,
    ca: Path,
    san: str | None = None,
) -> Identity:
    key, csr, cert = root / f"{name}.key", root / f"{name}.csr", root / f"{name}.pem"
    ca_key = ca.with_suffix(".key")
    _run(
        require_openssl(), "req", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={common_name}",
    )
    args = [
        require_openssl(), "x509", "-req", "-in", str(csr), "-CA", str(ca),
        "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(cert), "-days", "1",
    ]
    if san:
        extension = root / f"{name}.ext"
        extension.write_text(f"subjectAltName={san}\n", encoding="utf-8")
        args += ["-extfile", str(extension)]
    _run(*args)
    return Identity(cert, key)


def build_pki(root: Path) -> TestPki:
    require_openssl()
    root.mkdir(parents=True, exist_ok=True)
    _ca(root, "ca")
    server = issue(
        root, "server", "localhost",
        ca=root / "ca.pem", san="DNS:localhost,IP:127.0.0.1",
    )
    return TestPki(root, root / "ca.pem", server)


def rogue_ca(root: Path) -> Path:
    _ca(root, "rogue")
    return root / "rogue.pem"
