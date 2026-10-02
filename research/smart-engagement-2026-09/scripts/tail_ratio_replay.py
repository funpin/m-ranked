"""H68: replay of the late-engagement ledger, pattern 13 and account profile on a compact extraction.

Input: CSV of exact-quality candidate points (read-only extraction, kept outside Git):
account,platform,publication,published_at,observed_at,views,reactions,vq,rq,uncertain
Only points aged 18-30 h and 60 h-15 d are needed; the product code sees the full series,
but the ledger and pattern 13 use nothing outside these ages.

Uses the production functions unchanged: tail_ledger.build_ledger, detectors.late_engagement
thresholds and account_tail.profiles. Prints a JSON summary; optional per-account names come
from a separate JSON {account_id: short_name} (kept outside Git as well).
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import random
from collections import Counter, defaultdict
from datetime import date, datetime
import gzip
import json
import math
from pathlib import Path
from uuid import UUID

from scipy.stats import poisson

from anomaly_analysis.v2.account_tail import PostLedger, profiles
from anomaly_analysis.v2.detectors import late_engagement as p13
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.tail_ledger import Point, build_ledger


def load(path: Path):
    posts: dict[UUID, dict] = {}
    with gzip.open(path, "rt", newline="") as stream:
        for row in csv.reader(stream):
            if len(row) != 10 or row[0] == "account":
                continue
            account, platform, publication, published, observed, views, reactions, vq, rq, uncertain = row
            item = posts.setdefault(UUID(publication), {
                "account": UUID(account), "platform": platform,
                "published": datetime.fromisoformat(published), "rows": []})
            item["rows"].append((datetime.fromisoformat(observed), int(views) if views else None,
                                 int(reactions) if reactions else None, vq or "unknown", rq or "unknown",
                                 uncertain == "t"))
    return posts


def series(publication: UUID, item: dict) -> PostSeries:
    rows = sorted(item["rows"])
    return PostSeries(publication, item["account"], item["platform"], item["published"], False,
                      tuple(row[0] for row in rows),
                      {Metric.VIEWS: tuple(row[1] for row in rows), Metric.REACTIONS: tuple(row[2] for row in rows)},
                      qualities={Metric.VIEWS: tuple(row[3] for row in rows),
                                 Metric.REACTIONS: tuple(row[4] for row in rows)},
                      interval_uncertain=tuple(row[5] for row in rows))


def pattern13(ledger) -> bool:
    """Same thresholds as detectors.late_engagement.detect, applied to the ledger."""
    late, early = ledger.late, ledger.early
    if ledger.rounded or late is None or early is None or early.views < p13.MIN_EARLY_VIEWS or late[1] < p13.MIN_LATE_REACTIONS:
        return False
    early_rate = (early.reactions + 0.5) / (early.views + 1)
    if ((late[1] + 0.5) / (late[0] + 1)) / early_rate < p13.MIN_RATIO:
        return False
    tail = float(poisson.sf(late[1] - 1, max(early_rate * late[0], 1e-9)))
    return (-math.log10(tail) if tail > 0 else p13.FULL_SURPRISE) >= p13.MIN_SURPRISE


def inject(item: PostLedger, mode: str, dose: int, session_day: str | None) -> PostLedger:
    """Counterfactual additions on top of the observed ledger (no views unless stated).

    daily: +1 reaction on each covered late day, at most `dose` per post — a steady
    organised supply that is present over the whole window, fit and calibration alike.
    session: one ordinary archive reader on one day: +1 view and +1 reaction on every
    old post observed that day.
    """
    ledger = item.ledger
    if ledger.late is None or not ledger.covered:
        return item
    growth = dict(ledger.growth)
    added_r = added_v = 0
    if mode == "daily":
        for day in ledger.covered[:dose]:
            growth[day] = growth.get(day, 0) + 1
            added_r += 1
    elif mode == "session" and session_day in ledger.covered:
        growth[session_day] = growth.get(session_day, 0) + 1
        added_r = added_v = 1
    if not added_r:
        return item
    end = ledger.end
    return replace(item, ledger=replace(ledger, end=Point(end.age, end.views + added_v, end.reactions + added_r),
                                        growth=growth))


def sensitivity(ledgers, accounts, computed_for, *, per_platform: int, seed: int) -> dict:
    """Inject into accounts that are ordinary (status 0) on the observed data."""
    base = {item.account_id: item for item in profiles(ledgers, accounts, computed_for)}
    rng = random.Random(seed)
    days = sorted({day for item in ledgers for day in item.ledger.covered})
    report: dict = {}
    for platform in sorted(set(accounts.values())):
        ordinary = sorted((account for account, row in base.items() if row.platform == platform and row.status == 0),
                          key=str)
        chosen = rng.sample(ordinary, min(per_platform, len(ordinary)))
        if not chosen:
            continue
        cases = {f"daily_{dose}": ("daily", dose) for dose in (2, 3, 5, 10)}
        cases["session_once"] = ("session", 1)
        report[platform] = {"accounts": len(chosen)}
        for name, (mode, dose) in cases.items():
            outcome = Counter()
            for account in chosen:
                session_day = rng.choice(days[-14:]) if days else None
                changed = [inject(item, mode, dose, session_day) if item.account_id == account else item
                           for item in ledgers]
                row = next(item for item in profiles(changed, accounts, computed_for) if item.account_id == account)
                outcome["abstain" if row.status is None else str(row.status)] += 1
            report[platform][name] = dict(sorted(outcome.items()))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("points", type=Path)
    parser.add_argument("--computed-for", type=date.fromisoformat, required=True)
    parser.add_argument("--names", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sensitivity", type=int, default=0, help="ordinary accounts per platform to inject into")
    parser.add_argument("--seed", type=int, default=20260928)
    arguments = parser.parse_args()
    names = json.loads(arguments.names.read_text()) if arguments.names else {}
    posts = load(arguments.points)
    ledgers, accounts, signs = [], {}, Counter()
    by_account: Counter = Counter()
    eligible = Counter()
    for publication, item in posts.items():
        ledger = build_ledger(series(publication, item))
        accounts[item["account"]] = item["platform"]
        ledgers.append(PostLedger(publication, item["account"], item["platform"], item["published"], ledger))
        if ledger.late is not None and ledger.early is not None:
            eligible[item["platform"]] += 1
            hit = pattern13(ledger)
            signs[item["platform"]] += hit
            by_account[item["account"]] += hit
    result = profiles(ledgers, accounts, arguments.computed_for)
    summary: dict = {"computedFor": arguments.computed_for.isoformat(), "posts": len(posts), "platforms": {}}
    for platform in sorted(set(accounts.values())):
        rows = [item for item in result if item.platform == platform]
        statuses = Counter("abstain:" + item.abstain_reason if item.status is None else str(item.status) for item in rows)
        cohort = next((item.metrics["cohort"] for item in rows if item.metrics.get("cohort")), None)
        flagged = sorted(((item.metrics["ratio"], names.get(str(item.account_id), str(item.account_id)[:8]), item.status,
                           item.metrics["lateReactions"], item.metrics["activeDays"], item.metrics["activeWeeks"],
                           item.metrics["halves"]["earlier"]["ratio"], item.metrics["halves"]["recent"]["ratio"])
                          for item in rows if item.status), reverse=True)
        summary["platforms"][platform] = {
            "accounts": len(rows), "statuses": dict(sorted(statuses.items())), "cohort": cohort,
            "postsWithLedger": eligible[platform], "pattern13Posts": signs[platform],
            "pattern13Accounts": sum(1 for item in rows if by_account[item.account_id]),
            "pattern13Top": [[names.get(str(item.account_id), str(item.account_id)[:8]), by_account[item.account_id],
                              item.status] for item in sorted(rows, key=lambda row: -by_account[row.account_id])[:8]
                             if by_account[item.account_id]],
            "flagged": [dict(zip(("ratio", "account", "status", "lateReactions", "activeDays", "activeWeeks",
                                  "earlierRatio", "recentRatio"), row)) for row in flagged],
        }
        if names:
            summary["platforms"][platform]["named"] = {
                names[str(item.account_id)]: {"status": item.status, "reason": item.abstain_reason,
                                               "ratio": item.metrics["ratio"], "rank": (item.metrics.get("cohort") or {}).get("rank")}
                for item in rows if str(item.account_id) in names}
    if arguments.sensitivity:
        summary["sensitivity"] = sensitivity(ledgers, accounts, arguments.computed_for,
                                             per_platform=arguments.sensitivity, seed=arguments.seed)
    text = json.dumps(summary, ensure_ascii=False, indent=1)
    if arguments.output:
        arguments.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
