#!/usr/bin/env python3
"""Собрать воспроизводимый lock с хешами для среды выполнения.

Замыкание решается под целевую платформу CI и продакшена — linux x86_64,
CPython 3.13, — а не под машину разработчика: иначе в lock попали бы колёса
другой архитектуры и установка в образе не сошлась бы.

Проход первый решает состав зависимостей, проход второй скачивает каждый пакет
уже под целевую платформу. Пакет без колеса (такой, как pyaes у Telethon)
берётся исходным архивом; тогда в lock обязаны попасть setuptools и wheel, а
установка идёт с --no-build-isolation, чтобы ничего не докачивалось мимо
проверки хешей.

    python3 operations/scripts/generate_python_lock.py requirements/api.txt \\
        requirements/api.lock
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys
import tempfile

PLATFORMS = ("manylinux2014_x86_64", "manylinux_2_17_x86_64", "any")


def _download(destination: pathlib.Path, *arguments: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "download", "--quiet", "--no-cache-dir",
                    "--dest", str(destination), *arguments],
                   check=True, capture_output=True, text=True)


def _artifacts(directory: pathlib.Path) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for artifact in sorted(directory.iterdir()):
        if artifact.suffix == ".whl":
            name, version = artifact.name.split("-")[:2]
        elif artifact.name.endswith((".tar.gz", ".zip")):
            stem = artifact.name.removesuffix(".tar.gz").removesuffix(".zip")
            name, _, version = stem.rpartition("-")
        else:
            continue
        found[name.replace("_", "-").lower()] = (
            version, hashlib.sha256(artifact.read_bytes()).hexdigest())
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("target", type=pathlib.Path)
    parser.add_argument("--python-version", default="3.13")
    parser.add_argument("--extra", nargs="*", default=[],
                        help="дополнительные закреплённые пакеты, например setuptools==80.9.0")
    arguments = parser.parse_args()
    abi = "cp"+arguments.python_version.replace(".", "")
    platform_arguments = [item for platform in PLATFORMS for item in ("--platform", platform)]
    platform_arguments += ["--python-version", arguments.python_version,
                           "--implementation", "cp", "--abi", abi]

    with tempfile.TemporaryDirectory() as resolved_root, tempfile.TemporaryDirectory() as root:
        resolved, work = pathlib.Path(resolved_root), pathlib.Path(root)
        _download(resolved, "--requirement", str(arguments.source))
        pinned = [f"{name}=={version}" for name, (version, _) in _artifacts(resolved).items()]
        sources: list[str] = []
        for requirement in pinned+list(arguments.extra):
            try:
                _download(work, "--no-deps", "--only-binary=:all:",
                          *platform_arguments, requirement)
            except subprocess.CalledProcessError:
                _download(work, "--no-deps", "--no-binary=:all:", requirement)
                sources.append(requirement)
        if sources and not any(item.startswith("setuptools") for item in arguments.extra):
            print(f"исходные архивы {sources} требуют --extra setuptools==... wheel==...",
                  file=sys.stderr)
            return 1
        lines = [f"# Создано operations/scripts/generate_python_lock.py из {arguments.source}.",
                 f"# Платформа: linux x86_64, CPython {arguments.python_version}."
                 " Правится только пересозданием.",
                 "# Установка: pip install --require-hashes --no-deps --no-build-isolation"
                 " -r <этот файл>"]
        for name, (version, digest) in _artifacts(work).items():
            lines.append(f"{name}=={version} \\\n    --hash=sha256:{digest}")
        arguments.target.write_text("\n".join(lines)+"\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
