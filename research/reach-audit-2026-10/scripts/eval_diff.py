"""«До/после»: уровни постов и аккаунтные находки двух прогонов на копиях БД.

usage: python -I eval_diff.py BASE_DSN CAND_DSN OUT_DIR

Пишет OUT_DIR/diff.csv (посты, у которых изменился уровень или набор
признаков), OUT_DIR/findings.csv (находки обоих прогонов) и печатает матрицу
переходов уровней по площадкам и контрольную группу.
"""
import csv
import sys
from collections import Counter, defaultdict
from statistics import median

import psycopg
from psycopg.rows import dict_row

POSTS = """
SELECT s.publication_id::text AS id, a.platform::text AS platform, a.current_username AS uname,
       a.id::text AS account_id, i.short_name AS institution, s.published_at, s.level,
       COALESCE((SELECT string_agg(DISTINCT (e->>'pattern') || COALESCE(':' || (e->'render'->>'mode'), ''), ','
                                   ORDER BY (e->>'pattern') || COALESCE(':' || (e->'render'->>'mode'), ''))
                   FROM jsonb_array_elements(s.signals) e), '') AS signs
  FROM analytics.post_anomaly_state s
  JOIN ingest.visible_publication p ON p.id = s.publication_id
  JOIN catalog.visible_platform_account a ON a.id = p.primary_account_id
  LEFT JOIN catalog.institution i ON i.id = a.institution_id
 WHERE s.published_at >= '2026-09-01' AND s.published_at < '2026-10-08'"""
FINDINGS = """
SELECT f.account_id::text AS account_id, f.platform, f.kind, f.status, a.current_username AS uname,
       i.short_name AS institution, cardinality(f.members) AS members
  FROM analytics.account_anomaly_finding f
  JOIN catalog.platform_account a ON a.id = f.account_id
  LEFT JOIN catalog.institution i ON i.id = a.institution_id"""


def load(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        posts = {row["id"]: row for row in connection.execute(POSTS)}
        found = {(row["account_id"], row["kind"]): row for row in connection.execute(FINDINGS)}
    return posts, found


def control_group(base_posts, base_found, cand_found):
    """Аккаунты без находок в обоих прогонах и с долей уровня 3 не выше медианы площадки (по базе)."""
    flagged = {account for account, _ in base_found} | {account for account, _ in cand_found}
    by_account = defaultdict(list)
    for row in base_posts.values():
        by_account[row["account_id"]].append(row)
    share = {account: sum(r["level"] == 3 for r in rows) / len(rows) for account, rows in by_account.items()}
    platform = {account: rows[0]["platform"] for account, rows in by_account.items()}
    medians = {p: median([s for a, s in share.items() if platform[a] == p]) for p in set(platform.values())}
    return {account for account in by_account
            if account not in flagged and share[account] <= medians[platform[account]]}


def main(base_dsn, cand_dsn, out):
    base_posts, base_found = load(base_dsn)
    cand_posts, cand_found = load(cand_dsn)
    control = control_group(base_posts, base_found, cand_found)
    transitions, control_posts, control_up = Counter(), 0, []
    with open(f"{out}/diff.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "platform", "institution", "uname", "account_id", "published_at",
                         "base", "cand", "base_signs", "cand_signs", "control"])
        for key, cand in cand_posts.items():
            base = base_posts.get(key)
            if base is None:
                continue
            transitions[(cand["platform"], base["level"], cand["level"])] += 1
            in_control = cand["account_id"] in control
            control_posts += in_control
            if in_control and cand["level"] > base["level"]:
                control_up.append(key)
            if base["level"] != cand["level"] or base["signs"] != cand["signs"]:
                writer.writerow([key, cand["platform"], cand["institution"], cand["uname"], cand["account_id"],
                                 cand["published_at"], base["level"], cand["level"], base["signs"],
                                 cand["signs"], int(in_control)])
    with open(f"{out}/findings.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["run", "platform", "institution", "uname", "kind", "status", "members"])
        for run, found in (("base", base_found), ("cand", cand_found)):
            for row in sorted(found.values(), key=lambda r: (r["platform"], r["institution"] or "", r["kind"])):
                writer.writerow([run, row["platform"], row["institution"], row["uname"], row["kind"],
                                 row["status"], row["members"]])
    print("level transitions (platform: base -> cand: posts):")
    for (platform, before, after), count in sorted(transitions.items()):
        if before != after:
            print(f"  {platform}: {before} -> {after}: {count}")
    print(f"control group: {len(control)} accounts, {control_posts} posts, level up: {len(control_up)} "
          f"({100 * len(control_up) / max(control_posts, 1):.2f} %)")
    added = sorted(set(cand_found) - set(base_found), key=lambda k: (cand_found[k]["kind"], cand_found[k]["platform"]))
    removed = sorted(set(base_found) - set(cand_found))
    print(f"findings added: {len(added)}")
    for key in added:
        row = cand_found[key]
        print(f"  {row['kind']:<18} {row['platform']:<8} st={row['status']} {row['institution']} ({row['uname']}) "
              f"members={row['members']}")
    print(f"findings removed: {len(removed)}")
    for key in removed:
        row = base_found[key]
        print(f"  {row['kind']:<18} {row['platform']:<8} st={row['status']} {row['institution']} ({row['uname']})")
    changed = [k for k in set(base_found) & set(cand_found) if base_found[k]["status"] != cand_found[k]["status"]]
    print(f"findings with changed status: {len(changed)}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
