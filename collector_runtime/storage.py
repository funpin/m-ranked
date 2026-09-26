"""Disk admission control. No DB mutation and no dependency on a daemon."""
from __future__ import annotations
from dataclasses import dataclass
import os
import shutil

@dataclass
class CollectionDiskGate:
    path: str
    pause_free_bytes: int = 2_000_000_000
    resume_free_bytes: int = 3_000_000_000
    paused: bool = False

    def __post_init__(self):
        if not 0 < self.pause_free_bytes < self.resume_free_bytes:
            raise ValueError("disk resume reserve must exceed pause reserve")

    def allows_cycle(self) -> bool:
        try:
            usage = shutil.disk_usage(self.path)
            fs = os.statvfs(self.path)
        except OSError:
            self.paused = True
            return False
        free = usage.free
        # Start conservatively after restart: the hysteresis band is closed.
        threshold = self.resume_free_bytes if self.paused else self.pause_free_bytes
        percent = 15 if self.paused else 10
        inode_percent = 10 if self.paused else 5
        self.paused = (free <= max(threshold, usage.total * percent // 100)
                       or (fs.f_files > 0 and fs.f_favail * 100 <= fs.f_files * inode_percent))
        return not self.paused


def heavy_job_allowed(path: str, peak_bytes: int, reserve_bytes: int = 0) -> bool:
    if peak_bytes < 0 or reserve_bytes < 0:
        raise ValueError("negative disk budget")
    usage = shutil.disk_usage(path)
    fs = os.statvfs(path)
    return (usage.free >= peak_bytes + max(reserve_bytes, usage.total // 5)
            and (fs.f_files == 0 or fs.f_favail * 100 > fs.f_files * 10))
