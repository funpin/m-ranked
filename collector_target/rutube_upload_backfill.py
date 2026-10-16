"""One-off: fill ``ingest.publication.uploaded_at`` for already stored RUTUBE videos.

Videos inside the tracking window get the date from the collector itself; older
ones are never asked again. Server 2 services have no route to rutube.ru and the
Server 1 database does not reach Server 2, so the backfill is split in two:

1. List the videos still without a date on the target database::

       psql -Atc "SELECT DISTINCT i.external_id
                    FROM ingest.publication p
                    JOIN ingest.publication_identity i ON i.publication_id = p.id
                    JOIN catalog.platform_account a ON a.id = i.platform_account_id
                   WHERE a.platform = 'rutube' AND p.uploaded_at IS NULL" > ids.txt

2. Where rutube.ru is reachable, ask the public API and print SQL::

       python -m collector_target.rutube_upload_backfill ids.txt > backfill.sql

3. Apply ``backfill.sql`` with psql (``SET ROLE migration_owner``) on each
   database. It only fills empty dates, so a second run changes nothing.

Videos RUTUBE no longer serves (404/410 ``missing``, 403 ``forbidden`` — the
answer for a deleted video) keep an empty date; counts go to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import re
import sys
from typing import Iterable, Sequence, TextIO

import httpx

from collector_runtime.rutube import RutubeClient

VIDEO_ID = re.compile(r"[0-9A-Za-z_-]{1,64}")
STATUS_BUCKETS = {404: "missing", 410: "missing", 403: "forbidden"}


def read_ids(lines: Iterable[str]) -> tuple[list[str], int]:
    """Unique video ids in input order and the number of rejected lines."""
    ids: dict[str, None] = {}
    invalid = 0
    for line in lines:
        value = line.strip()
        if not value:
            continue
        if VIDEO_ID.fullmatch(value):
            ids.setdefault(value, None)
        else:
            invalid += 1
    return list(ids), invalid


async def fetch_upload_times(
    client: RutubeClient, ids: Sequence[str], concurrency: int = 4,
) -> tuple[list[tuple[str, datetime]], Counter[str]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    counts: Counter[str] = Counter()

    async def one(video_id: str) -> tuple[str, datetime] | None:
        async with semaphore:
            try:
                video = await client.video(video_id)
            except httpx.HTTPStatusError as error:
                # 403 RUTUBE отдаёт и на удалённое видео («Видео удалено»).
                counts[STATUS_BUCKETS.get(error.response.status_code, "error")] += 1
                return None
            except (httpx.HTTPError, ValueError):
                counts["error"] += 1
                return None
        if video.uploaded_at is None:
            counts["no_created_ts"] += 1
            return None
        counts["found"] += 1
        return video_id, video.uploaded_at

    results = await asyncio.gather(*(one(video_id) for video_id in ids))
    return [row for row in results if row is not None], counts


def backfill_sql(rows: Iterable[tuple[str, datetime]], chunk: int = 500) -> str:
    """UPDATE statements that set only missing dates of RUTUBE publications."""
    values: list[str] = []
    for video_id, uploaded_at in rows:
        if not VIDEO_ID.fullmatch(video_id):
            raise ValueError(f"not a RUTUBE video id: {video_id!r}")
        moment = uploaded_at.astimezone(timezone.utc).isoformat()
        values.append(f"('{video_id}', '{moment}'::timestamptz)")
    statements = ["BEGIN;", "SET LOCAL lock_timeout = '5s';"]
    for start in range(0, len(values), max(1, chunk)):
        statements.append(
            "UPDATE ingest.publication AS p SET uploaded_at = v.uploaded_at\n"
            "  FROM (VALUES\n    "
            + ",\n    ".join(values[start:start + chunk])
            + "\n  ) AS v(external_id, uploaded_at),\n"
            "  ingest.publication_identity AS i, catalog.platform_account AS a\n"
            " WHERE i.external_id = v.external_id AND i.publication_id = p.id\n"
            "   AND a.id = i.platform_account_id AND a.platform = 'rutube'\n"
            "   AND p.uploaded_at IS NULL;"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n"


async def _run(ids: Sequence[str], api_base: str, concurrency: int):
    client = RutubeClient(api_base)
    try:
        return await fetch_upload_times(client, ids, concurrency)
    finally:
        await client.close()


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", type=argparse.FileType("r"),
                        help="file with one RUTUBE video id per line, '-' for stdin")
    parser.add_argument("--api-base", default="https://rutube.ru/api")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args(argv)
    ids, invalid = read_ids(args.ids)
    rows, counts = asyncio.run(_run(ids, args.api_base, args.concurrency))
    out.write(backfill_sql(rows))
    counts["invalid_id"] = invalid
    print(json.dumps({"ids": len(ids), **counts}, sort_keys=True), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
