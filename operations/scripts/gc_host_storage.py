#!/usr/bin/env python3
"""Safely bound immutable releases and unused Docker artifacts."""

from __future__ import annotations

import argparse
import json
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
            except OSError:
                continue
            if target is not None and target.is_dir():
                active.add(target)
    return active


def docker_mount_releases(root: Path) -> set[Path]:
    identifiers = subprocess.run(
        ["docker", "ps", "-q"], check=True, text=True, capture_output=True
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


def run_docker_gc(age_hours: int, apply: bool) -> None:
    if not apply:
        print(f"would-prune docker-unused-older-than={age_hours}h")
        print("would-prune docker-volume-label=m-ranked.gc=ephemeral")
        return
    commands = (
        ["docker", "container", "prune", "--force", "--filter", f"until={age_hours}h"],
        ["docker", "image", "prune", "--all", "--force", "--filter", f"until={age_hours}h"],
        ["docker", "builder", "prune", "--all", "--force", "--filter", f"until={age_hours}h"],
        ["docker", "network", "prune", "--force", "--filter", f"until={age_hours}h"],
        ["docker", "volume", "prune", "--all", "--force", "--filter", "label=m-ranked.gc=ephemeral"],
    )
    for command in commands:
        subprocess.run(command, check=True)


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
    docker_enabled = os.environ.get("MRANKED_DOCKER_PRUNE_ENABLED", "1")
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
    for release in process_releases(root, proc_root):
        protected[release] = "in-use"

    if docker_enabled == "1" and shutil.which("docker"):
        for release in docker_mount_releases(root):
            protected[release] = "in-use"

    cutoff_ns = (time.time_ns() - min_age_hours * 3_600 * 1_000_000_000)
    candidates = 0
    for release in releases:
        if reason := protected.get(release):
            print(f"keep release={release.name} reason={reason}")
        elif release.stat().st_mtime_ns >= cutoff_ns:
            print(f"keep release={release.name} reason=young")
        else:
            candidates += 1
            if apply:
                shutil.rmtree(release)
                print(f"removed release={release.name}")
            else:
                print(f"would-remove release={release.name}")

    if docker_enabled == "1" and shutil.which("docker"):
        run_docker_gc(docker_age_hours, apply)
    print(f"host-storage-gc apply={str(apply).lower()} release_candidates={candidates}")
    return candidates


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    collect(arguments.apply)
