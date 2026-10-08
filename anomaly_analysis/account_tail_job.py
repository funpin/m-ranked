"""Ночной профиль позднего отклика и аккаунтные находки: python -m anomaly_analysis.account_tail_job.

Читает только сводки постов (analytics.post_anomaly_state.tail_ledger,
~200 байт на пост) и часы признаков синхронного подъёма из их выводов — то,
что работник анализа уже построил из прочитанных им рядов; замеры не читаются. Пишет строку на аккаунт в
analytics.account_tail_profile и удаляет строки старше срока хранения, затем
переписывает analytics.account_anomaly_finding. Метод и пороги —
anomaly_analysis/v2/account_tail.py и v2/account_findings.py.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import time

from .metrics import write_textfile
from .v2.account_findings import (
    METHOD_VERSION as FINDINGS_VERSION, WINDOW_DAYS, LedgerPost, SynchronyEvent, findings, with_texts,
)
from .v2.account_tail import POSTS_FROM_DAYS, POSTS_UNTIL_DAYS, PostLedger, profiles, window_end
from .v2.store import PostgresAnomalyStore
from .v2.tail_ledger import MOSCOW, ledger_from_payload

RETENTION_DAYS = 90

log = logging.getLogger("anomaly_analysis.account_tail_job")


def run(store: PostgresAnomalyStore, computed_for: date, retention_days: int = RETENTION_DAYS):
    accounts = store.read_tail_accounts()
    end = window_end(computed_for)
    rows = store.read_tail_ledgers(end - timedelta(days=POSTS_FROM_DAYS), end - timedelta(days=POSTS_UNTIL_DAYS))
    posts = []
    for row in rows:
        ledger = ledger_from_payload(row["tail_ledger"])
        platform = accounts.get(row["account_id"])
        if ledger is not None and platform is not None:
            posts.append(PostLedger(row["publication_id"], row["account_id"], platform, row["published_at"], ledger))
    result = profiles(posts, accounts, computed_for)
    store.write_tail_profiles(result, computed_for - timedelta(days=retention_days))
    return result, len(posts)


def run_findings(store: PostgresAnomalyStore, computed_for: date, tail_profiles=()):
    end = window_end(computed_for)
    start = end - timedelta(days=WINDOW_DAYS)
    posts = []
    for row in store.read_finding_ledgers(start, end):
        ledger = ledger_from_payload(row["tail_ledger"])
        if ledger is not None:
            posts.append(LedgerPost(row["publication_id"], row["account_id"], row["platform"],
                                    row["published_at"], bool(row["is_repost"]), ledger,
                                    row.get("institution_id")))
    tail_status = {item.account_id: (item.platform, item.status, {**item.metrics})
                   for item in tail_profiles if item.status is not None}
    persistent = [account for account, (_, status, _) in tail_status.items() if status == 2]
    late = store.read_late_members(persistent, start, end)
    synchrony = [SynchronyEvent(row["account_id"], row["platform"], row["publication_id"], row["hour"])
                 for row in store.read_synchrony_events(start, end)]
    result = [with_texts(item) for item in findings(posts, computed_for, late, tail_status, synchrony)]
    store.write_account_findings(result, FINDINGS_VERSION)
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    dsn = os.environ.get("ANOMALY_DATABASE_URL", "").strip()
    if not dsn:
        raise SystemExit("ANOMALY_DATABASE_URL is required")
    metrics_value = os.environ.get("ANOMALY_TAIL_METRICS_FILE", "").strip()
    started = time.monotonic()
    # Окно заканчивается московской полночью: последние полные сутки — вчера.
    computed_for = datetime.now(timezone.utc).astimezone(MOSCOW).date()
    store = PostgresAnomalyStore(dsn)
    result, posts = run(store, computed_for)
    found = run_findings(store, computed_for, result)
    statuses = Counter((item.platform, "abstain" if item.status is None else str(item.status)) for item in result)
    log.info("account tail profiles for %s: %d accounts, %d post ledgers, %s", computed_for, len(result), posts,
             dict(sorted(statuses.items())))
    samples = [("tail_last_run_unixtime", "gauge", {}, time.time()),
               ("tail_run_seconds", "gauge", {}, time.monotonic() - started),
               ("tail_post_ledgers", "gauge", {}, posts)]
    samples += [("tail_profiles", "gauge", {"platform": platform, "status": status}, count)
                for (platform, status), count in sorted(statuses.items())]
    kinds = Counter((item.platform, item.kind) for item in found)
    log.info("account findings for %s: %s", computed_for, dict(sorted(kinds.items())))
    samples += [("account_findings", "gauge", {"platform": platform, "kind": kind}, count)
                for (platform, kind), count in sorted(kinds.items())]
    write_textfile(Path(metrics_value) if metrics_value else None, samples)


if __name__ == "__main__":
    main()
