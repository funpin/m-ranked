from __future__ import annotations

import csv
import gzip
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Settings
from .database import Database, iso

logger = logging.getLogger(__name__)


ARCHIVE_COLUMNS = (
    "username", "channel_title", "telegram_message_id", "published_at",
    "discovered_at", "history_complete", "post_type", "measured_at",
    "age_seconds", "total_reactions", "delta_total", "views_count",
    "delta_views", "reactions_json", "delta_by_reaction_json",
    "interval_uncertain", "spike", "synthetic",
)


def _archive_path(root: Path, post: object) -> Path:
    published = datetime.fromisoformat(post["published_at"])
    month = published.strftime("%Y-%m")
    safe_username = "".join(ch for ch in str(post["username"]) if ch.isalnum() or ch in "_-")
    return root / month / f"{safe_username}-{post['telegram_message_id']}.csv.gz"


def archive_and_purge(settings: Settings, db: Database, now: datetime | None = None) -> int:
    """Archive every expired post atomically, then remove it from live SQLite."""
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=settings.retention_days)
    removed = 0
    for post in db.expired_posts(iso(cutoff)):
        target = _archive_path(settings.archive_dir, post)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            rows = db.archive_rows(int(post["id"]))
            fd, temp_name = tempfile.mkstemp(prefix=".archive-", suffix=".csv.gz", dir=target.parent)
            os.close(fd)
            temp = Path(temp_name)
            try:
                with gzip.open(temp, "wt", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(ARCHIVE_COLUMNS)
                    writer.writerows([[row[column] for column in ARCHIVE_COLUMNS] for row in rows])
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
        db.delete_post(int(post["id"]))
        removed += 1
    if removed:
        logger.info("archived and purged %s posts older than %s days", removed, settings.retention_days)
    return removed
