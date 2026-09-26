#!/usr/bin/env python3
"""Safely bound immutable releases and unused Docker artifacts."""

from __future__ import annotations

import argparse
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import time


def positive(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    if not raw.isdecimal() or int(raw) < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(raw)


def release_for(path: Path, root: Path) -> Path | None:
    try:
        relative = path.resolve(strict=False).relative_to(root)
    except ValueError:
        return None
    return root / relative.parts[0] if relative.parts else None


def process_releases(root: Path, proc_root: Path) -> set[Path]:
    active: set[Path] = set()
    for process in proc_root.glob("[0-9]*"):
        for name in ("cwd", "exe"):
            try:
                target = release_for((process / name).resolve(strict=True), root)
            except PermissionError as error:
                raise RuntimeError("cannot inspect process release references; GC refused") from error
            except OSError:
                continue
            if target is not None and target.is_dir():
                active.add(target)
    return active


def docker_mount_releases(root: Path) -> set[Path]:
    identifiers = subprocess.run(
        ["docker", "ps", "-aq"], check=True, text=True, capture_output=True
    ).stdout.split()
    if not identifiers:
        return set()
    containers = json.loads(subprocess.run(
        ["docker", "inspect", *identifiers], check=True, text=True, capture_output=True
    ).stdout)
    active: set[Path] = set()
    for container in containers:
        for mount in container.get("Mounts", []):
            source = mount.get("Source")
            if not source:
                continue
            release = release_for(Path(source), root)
            if release is not None and release.is_dir():
                active.add(release)
    return active


_UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12,
          "KIB": 2**10, "MIB": 2**20, "GIB": 2**30, "TIB": 2**40}


def _bytes(text: str) -> int:
    match = re.match(r"\s*([0-9.]+)\s*([A-Za-z]+)", text or "")
    if not match:
        return 0
    return int(float(match.group(1)) * _UNITS.get(match.group(2).upper(), 1))


def docker_reclaimable_bytes() -> int | None:
    """Сколько Docker мог бы освободить. Только счёт: на хосте чужие проекты,
    и что из их образов нужно для отката, знает только их владелец."""
    if not shutil.which("docker"):
        return None
    result = subprocess.run(["docker", "system", "df", "--format", "{{json .}}"],
                            check=False, capture_output=True, text=True, timeout=120)
    if result.returncode:
        return None
    total = 0
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        total += _bytes(str(item.get("Reclaimable", "")))
    return total


def write_metrics(path: str, values: dict[str, float]) -> None:
    if not path:
        return
    target = Path(path)
    temporary = target.with_name(f".{target.name}.{os.getpid()}")
    temporary.write_text("".join(f"{key} {value}\n" for key, value in values.items()))
    temporary.chmod(0o644)
    os.replace(temporary, target)


def run_docker_gc(age_hours: int, apply: bool) -> None:
    # Docker cannot tell whether a stopped service's next ExecStart or an
    # operator's rollback needs an image. Age/unused status is not authorization.
    print("docker-gc disabled: review exact image/container IDs; no blanket prune")


def systemd_releases(root: Path) -> set[Path]:
    if not shutil.which("systemctl"):
        return set()
    units = subprocess.run(
        ["systemctl", "list-unit-files", "--no-legend", "--no-pager", "m-ranked*"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    names = [line.split()[0] for line in units if line.strip()]
    if not names:
        return set()
    # show rejects uninstantiated templates (e.g. collector@.service). Read
    # their fragments/drop-ins too: a stopped template can pin the next release.
    output = subprocess.run(
        ["systemctl", "cat", *names],
        check=True, capture_output=True, text=True,
    ).stdout
    return {root / name for name in re.findall(re.escape(str(root)) + r"/([^/\s;{}]+)", output)}


def collect(apply: bool) -> int:
    configured_root = Path(os.environ.get("MRANKED_RELEASE_ROOT", "/opt/m-ranked/releases"))
    if configured_root.is_symlink():
        raise RuntimeError("release root/current layout is unsafe")
    root = configured_root.resolve(strict=True)
    current = Path(os.environ.get("MRANKED_CURRENT_LINK", "/opt/m-ranked/current")).resolve(strict=True)
    proc_root = Path(os.environ.get("MRANKED_PROC_ROOT", "/proc"))
    keep_rollbacks = positive("MRANKED_RELEASE_KEEP_ROLLBACKS", 1)
    min_age_hours = positive("MRANKED_RELEASE_MIN_AGE_HOURS", 24)
    docker_age_hours = positive("MRANKED_DOCKER_PRUNE_AGE_HOURS", 168)
    docker_enabled = os.environ.get("MRANKED_DOCKER_PRUNE_ENABLED", "0")
    # Автоудаление: кандидат — всё, что не защищено ниже и старше порога.
    # Без него удаляются только имена из списка одобренных.
    auto_remove = os.environ.get("MRANKED_RELEASE_AUTO_REMOVE", "0")
    if auto_remove not in {"0", "1"}:
        raise ValueError("MRANKED_RELEASE_AUTO_REMOVE must be 0 or 1")
    if docker_enabled not in {"0", "1"}:
        raise ValueError("MRANKED_DOCKER_PRUNE_ENABLED must be 0 or 1")
    if not root.is_dir() or current.parent != root:
        raise RuntimeError("release root/current layout is unsafe")

    releases = sorted(
        (item for item in root.iterdir() if item.is_dir() and not item.is_symlink()),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    protected: dict[Path, str] = {current: "current"}
    for release in (item for item in releases if item != current):
        if sum(reason == "rollback" for reason in protected.values()) >= keep_rollbacks:
            break
        protected[release] = "rollback"
    for release in systemd_releases(root):
        protected[release] = "unit-reference"
    for name in os.environ.get("MRANKED_PROTECTED_RELEASES", "").split(","):
        if name.strip():
            if Path(name.strip()).name != name.strip():
                raise ValueError("protected releases must be basenames")
            protected[root / name.strip()] = "explicit-rollback-or-forensic"
    for release in process_releases(root, proc_root):
        protected[release] = "in-use"

    # Mount protection is independent of whether Docker cleanup is enabled.
    if shutil.which("docker"):
        for release in docker_mount_releases(root):
            protected[release] = "in-use"

    cutoff_ns = (time.time_ns() - min_age_hours * 3_600 * 1_000_000_000)
    candidates = 0
    removed = 0
    approved = {name for name in os.environ.get("MRANKED_APPROVED_RELEASE_REMOVALS", "").split(",") if name}
    for release in releases:
        if reason := protected.get(release):
            print(f"keep release={release.name} reason={reason}")
        elif release.stat().st_mtime_ns >= cutoff_ns:
            print(f"keep release={release.name} reason=young")
        else:
            candidates += 1
            if apply and auto_remove != "1" and release.name not in approved:
                print(f"keep release={release.name} reason=needs-explicit-review")
            elif apply:
                shutil.rmtree(release)
                removed += 1
                print(f"removed release={release.name}")
            else:
                print(f"would-remove release={release.name}")

    if docker_enabled == "1" and shutil.which("docker"):
        run_docker_gc(docker_age_hours, apply)
    metrics: dict[str, float] = {
        "mranked_host_gc_last_run_unixtime": time.time(),
        "mranked_host_gc_releases": len([item for item in root.iterdir() if item.is_dir()]),
        "mranked_host_gc_release_candidates": candidates,
        "mranked_host_gc_releases_removed": removed,
    }
    reclaimable = docker_reclaimable_bytes()
    if reclaimable is not None:
        metrics["mranked_host_docker_reclaimable_bytes"] = reclaimable
    write_metrics(os.environ.get("MRANKED_HOST_GC_METRICS_FILE", ""), metrics)
    print(f"host-storage-gc apply={str(apply).lower()} release_candidates={candidates} removed={removed}")
    return candidates


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    collect(arguments.apply)
