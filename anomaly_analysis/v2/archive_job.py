"""Повторный анализ месяца по данным холодного архива (задание панели, ADR-016).

Администратор просит прогнать анализ месяца заново — например, после
исправления детектора. Задание не считает ничего само: оно снимает заморозку с
постов месяца (и ставит в очередь те, у которых состояния ещё нет), а обычный
работник анализа делает им финальный анализ — тем же кодом, теми же нормами,
по ряду из файлов просмотра архива (archive_series.py) — и замораживает снова.
Задание следит за остатком и пишет ход в admin_job, пока все посты месяца не
заморожены или не вышел срок.

Запускается агентом основного сервера, когда в очереди есть задание
(m-ranked-target-archive-analysis.service), под учётной записью анализа.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
import re
import sys
import time
from typing import Any, Callable

logger = logging.getLogger("anomaly.archive_job")
MONTH = re.compile(r"^(20[0-9]{2})-(0[1-9]|1[0-2])$")
PLATFORMS = frozenset({"telegram", "vk", "max", "rutube"})
POLL_SECONDS = 30.0
DEADLINE = timedelta(hours=12)

CLAIM = """
UPDATE ops_and_admin.admin_job SET state = 'running', started_at = transaction_timestamp()
 WHERE id = (SELECT id FROM ops_and_admin.admin_job WHERE kind = 'archive_analysis' AND state = 'queued'
              ORDER BY requested_at LIMIT 1 FOR UPDATE SKIP LOCKED)
RETURNING id::text, params
"""
SCOPE = """
FROM ingest.visible_publication publication
JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
WHERE publication.published_at >= %(start)s AND publication.published_at < %(end)s
  AND publication.deleted_at IS NULL
  AND (%(platform)s::text IS NULL OR account.platform::text = %(platform)s)
"""
SEED = f"""
INSERT INTO analytics.post_anomaly_state (publication_id, published_at, next_due_at)
SELECT publication.id, publication.published_at, %(now)s {SCOPE}
ON CONFLICT (publication_id) DO NOTHING
"""
# Срок — сейчас: работник берёт свежие посты первыми, так что архивный месяц
# не обгоняет текущий анализ, а идёт следом за ним.
UNFREEZE = f"""
UPDATE analytics.post_anomaly_state state
   SET frozen = false, next_due_at = %(now)s, attempts = 0, error_code = NULL, updated_at = transaction_timestamp()
 WHERE state.publication_id IN (SELECT publication.id {SCOPE})
"""
REMAINING = f"""
SELECT count(*) FILTER (WHERE NOT state.frozen)::integer AS open,
       count(*) FILTER (WHERE NOT state.frozen AND state.error_code IS NOT NULL)::integer AS failing
  FROM analytics.post_anomaly_state state
 WHERE state.publication_id IN (SELECT publication.id {SCOPE})
"""
PROGRESS = """
UPDATE ops_and_admin.admin_job SET progress = %(progress)s::jsonb WHERE id = %(id)s::uuid
"""
FINISH = """
UPDATE ops_and_admin.admin_job SET state = %(state)s, finished_at = transaction_timestamp(),
       result = %(result)s::jsonb, error = %(error)s, progress = %(progress)s::jsonb
 WHERE id = %(id)s::uuid
"""


def scope(params: dict[str, Any]) -> dict[str, Any]:
    raw = str(params.get("month") or "")
    if not MONTH.fullmatch(raw):
        raise ValueError("job month must be YYYY-MM")
    start = date(int(raw[:4]), int(raw[5:]), 1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    platform = params.get("platform") or None
    if platform is not None and platform not in PLATFORMS:
        raise ValueError("unknown platform")
    as_utc = lambda value: datetime(value.year, value.month, value.day, tzinfo=timezone.utc)  # noqa: E731
    return {"start": as_utc(start), "end": as_utc(end), "platform": platform}


def run(connection: Any, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep) -> dict[str, Any] | None:
    job = connection.execute(CLAIM).fetchone()
    if job is None:
        return None
    progress: dict[str, Any] = {}
    try:
        window = scope(job["params"] or {})
        now = clock()
        with connection.transaction():
            seeded = connection.execute(SEED, {**window, "now": now}).rowcount
            queued = connection.execute(UNFREEZE, {**window, "now": now}).rowcount
        progress = {"queued": queued, "seeded": seeded, "open": queued}
        connection.execute(PROGRESS, {"id": job["id"], "progress": json.dumps(progress)})
        logger.info("archive analysis queued job=%s posts=%s seeded=%s", job["id"], queued, seeded)
        deadline = now + DEADLINE
        while True:
            row = connection.execute(REMAINING, window).fetchone()
            progress = {**progress, "open": row["open"], "failing": row["failing"]}
            connection.execute(PROGRESS, {"id": job["id"], "progress": json.dumps(progress)})
            if row["open"] == 0:
                state, error = "done", None
                break
            if clock() >= deadline:
                state, error = "failed", f"{row['open']} posts still open after {DEADLINE}"
                break
            sleep(POLL_SECONDS)
    except Exception as failure:  # noqa: BLE001 — итог пишется в задание
        state, error = "failed", f"{type(failure).__name__}: {failure}"[:500]
    result = {"queued": progress.get("queued", 0), "seeded": progress.get("seeded", 0)}
    connection.execute(FINISH, {"id": job["id"], "state": state, "error": error, "result": json.dumps(result),
                                "progress": json.dumps(progress)})
    logger.info("archive analysis finished job=%s state=%s", job["id"], state)
    return {"id": job["id"], "state": state, **result}


def main() -> int:
    import psycopg
    from psycopg.rows import dict_row

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("ANOMALY_DATABASE_URL is required")
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row,
                         options="-c timezone=UTC -c statement_timeout=120000") as connection:
        failed = False
        while (outcome := run(connection)) is not None:
            failed = failed or outcome["state"] != "done"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
