"""Синтетика: чувствительность и ложные срабатывания пакетов, волн и ночного притока.

usage: python -I eval_synthetic.py BASE_DSN CAND_DSN OUT_DIR [posts|ledgers]

posts   — 75 постов контрольной группы на площадку (22.09–07.10, зерно 20261012):
          исходный ряд (ложное — признак 1 «short_views» ≥ 0,7), затем вживление
          пакета size × min(1, (t − onset)/duration) в просмотры; Telegram с
          тысячи — показ «три значащие цифры» с quality=rounded.
ledgers — сводки постов кандидата: вживление часов притока на последние N постов
          20 контрольных аккаунтов (волны) и ровного ночного притока (суточный
          ритм); исходные сводки — ложные находки.
"""
import csv
import random
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row

from anomaly_analysis.v2.account_findings import LedgerPost
from anomaly_analysis.v2.detectors import DetectorContext, linear_feed
from anomaly_analysis.v2.domain import Metric
from anomaly_analysis.v2.reach_findings import flat_day_findings, wave_findings
from anomaly_analysis.v2.series import CollectionCadence, prepare
from anomaly_analysis.v2.store import PostgresAnomalyStore, SeriesTarget
from anomaly_analysis.v2.tail_ledger import TailLedger, ledger_from_payload

SEED = 20261012
AS_OF = datetime(2026, 10, 8, tzinfo=timezone.utc)
COMPUTED_FOR = date(2026, 10, 8)
SIZES, DURATIONS, ONSETS = (500, 1000, 2000, 5000), (2, 4, 6), (0, 3, 8)
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from eval_diff import control_group, load  # noqa: E402


def tg_display(value):
    if value is None or value < 1000:
        return value
    unit = 10 ** (len(str(value)) - 3)
    return value // unit * unit


def inject(series, onset_h, duration_h, size):
    published = series.published_at
    views = []
    for at, value in zip(series.observed_at, series.values[Metric.VIEWS]):
        hours = (at - published).total_seconds() / 3600
        add = 0 if hours < onset_h else size * min(1.0, (hours - onset_h) / duration_h)
        views.append(None if value is None else int(value + add))
    quality = series.qualities[Metric.VIEWS]
    if series.platform == "telegram":
        quality = tuple("rounded" if v is not None and v >= 1000 else q for v, q in zip(views, quality))
        views = [tg_display(v) for v in views]
    return replace(series, values={**series.values, Metric.VIEWS: tuple(views)},
                   qualities={**series.qualities, Metric.VIEWS: tuple(quality)})


def view_signs(series):
    prepared = prepare(series, AS_OF, CollectionCadence())
    return [s for s in linear_feed.detect(prepared, DetectorContext(series.platform)) if s.metric is Metric.VIEWS]


def background_rate(series, onset_h):
    """Темп просмотров в час до начала пакета (или в час после его конца, если начало — публикация)."""
    published, rows = series.published_at, list(zip(series.observed_at, series.values[Metric.VIEWS]))

    def at(hours):
        moment = published + timedelta(hours=hours)
        before = [v for t, v in rows if t <= moment and v is not None]
        return before[-1] if before else None
    lo, hi = (onset_h - 1, onset_h) if onset_h >= 1 else (onset_h + 7, onset_h + 8)
    a, b = at(lo), at(hi)
    return None if a is None or b is None else max(0, b - a)


def after_rate(series, end_h):
    """Темп живого притока в два часа после пакета (до вживления)."""
    published, rows = series.published_at, list(zip(series.observed_at, series.values[Metric.VIEWS]))

    def at(hours):
        moment = published + timedelta(hours=hours)
        before = [v for t, v in rows if t <= moment and v is not None]
        return before[-1] if before else None
    a, b = at(end_h), at(end_h + 2)
    return None if a is None or b is None else max(0, b - a) / 2


def dense(series, until_h):
    """Замеры с публикации до until_h не реже 45 минут."""
    ages = [(t - series.published_at).total_seconds() for t in series.observed_at if
            (t - series.published_at).total_seconds() <= until_h * 3600]
    return bool(ages) and ages[0] <= 45 * 60 and all(b - a <= 45 * 60 for a, b in zip(ages, ages[1:]))


def posts_part(base_dsn, cand_dsn, out):
    base_posts, base_found = load(base_dsn)
    _, cand_found = load(cand_dsn)
    control = control_group(base_posts, base_found, cand_found)
    rng = random.Random(SEED)
    chosen = []
    for platform in ("telegram", "vk", "max", "rutube"):
        pool = sorted(key for key, row in base_posts.items() if row["account_id"] in control
                      and row["platform"] == platform and row["published_at"] >= datetime(2026, 9, 22, tzinfo=timezone.utc))
        chosen += rng.sample(pool, min(75, len(pool)))
    store = PostgresAnomalyStore(cand_dsn)
    rows, false_alarms = [], []
    with psycopg.connect(cand_dsn, row_factory=dict_row) as connection:
        published = {r["id"]: r["published_at"] for r in connection.execute(
            "SELECT id::text, published_at FROM ingest.publication WHERE id = ANY(%s::uuid[])", (chosen,))}
    for key in chosen:
        from uuid import UUID
        series = store.read_series([SeriesTarget(UUID(key), published[key])]).get(UUID(key))
        if series is None or Metric.VIEWS not in series.values:
            continue
        if any(s.render.get("mode") == "short_views" and s.strength >= 0.7 for s in view_signs(series)):
            false_alarms.append(key)
        for size in SIZES:
            for duration in DURATIONS:
                for onset in ONSETS:
                    signs = view_signs(inject(series, onset, duration, size))
                    start = series.published_at + timedelta(hours=onset)
                    end = start + timedelta(hours=duration)
                    hit = [s for s in signs if s.strength >= 0.7 and s.interval.start < end and start < s.interval.end]
                    background = background_rate(series, onset)
                    ratio = None if background is None else (size / duration) / max(background, 1)
                    after = after_rate(series, onset + duration)
                    drop = None if after is None else (size / duration + after) / max(after, 1)
                    clock = (end + timedelta(hours=3)).hour
                    rows.append([key, series.platform, size, duration, onset, round(ratio, 2) if ratio else "",
                                 int(bool(hit)), int(any(s.render.get("mode") == "short_views" for s in hit)),
                                 round(drop, 2) if drop else "", clock, int(dense(series, onset + duration + 2))])
    with open(f"{out}/synthetic_posts.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "platform", "size", "duration", "onset", "rate_to_background", "found", "found_short",
                         "drop_after", "end_clock_msk", "dense"])
        writer.writerows(rows)
    print(f"posts: {len(set(r[0] for r in rows))}, false alarms on originals: {len(false_alarms)} {false_alarms}")
    # Видимые проверке по построению: обрыв днём (08–20 МСК), темп после пакета
    # падает не меньше чем в 5 раз, замеры не реже 45 минут.
    visible = [r for r in rows if r[8] != "" and r[8] >= 5 and 8 <= r[9] < 20 and r[10]]
    by = defaultdict(lambda: [0, 0])
    for r in visible:
        if r[2] >= 1000:
            by[r[1]][0] += r[6]
            by[r[1]][1] += 1
    for platform, (found, total) in sorted(by.items()):
        print(f"  visible by design, size>=1000: {platform:<8} {found}/{total} = {100 * found / max(total, 1):.0f} %")
    table = defaultdict(lambda: [0, 0])
    for row in rows:
        if row[5] != "" and row[5] >= 3:
            cell = table[(row[1], row[2])]
            cell[0] += row[6]
            cell[1] += 1
    for (platform, size), (found, total) in sorted(table.items()):
        print(f"  {platform:<8} size={size:<5} rate≥3×bg: found {found}/{total} = {100 * found / max(total, 1):.0f} %")


def ledgers_part(base_dsn, cand_dsn, out):
    base_posts, base_found = load(base_dsn)
    _, cand_found = load(cand_dsn)
    control = sorted(control_group(base_posts, base_found, cand_found))
    with psycopg.connect(cand_dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            """SELECT s.publication_id, p.primary_account_id AS account_id, a.platform::text AS platform,
                      s.published_at, p.is_repost, s.tail_ledger
                 FROM analytics.post_anomaly_state s
                 JOIN ingest.visible_publication p ON p.id = s.publication_id
                 JOIN catalog.visible_platform_account a ON a.id = p.primary_account_id
                WHERE s.published_at >= %s AND s.published_at < %s AND s.tail_ledger_version = 5""",
            (AS_OF - timedelta(days=30), AS_OF)).fetchall()
    posts = [LedgerPost(r["publication_id"], r["account_id"], r["platform"], r["published_at"], r["is_repost"],
                        ledger) for r in rows if (ledger := ledger_from_payload(r["tail_ledger"])) is not None]
    rng = random.Random(SEED)
    controls = {str(a) for a in control}
    accounts = sorted({str(p.account_id) for p in posts if str(p.account_id) in controls})
    picked = rng.sample(accounts, min(20, len(accounts)))
    original_waves = [f for f in wave_findings(posts, COMPUTED_FOR) if str(f.account_id) in controls]
    original_flat = [f for f in flat_day_findings(posts, COMPUTED_FOR) if str(f.account_id) in controls]
    print(f"control accounts: {len(accounts)}; false wave findings: {len(original_waves)}; "
          f"false rhythm findings: {len(original_flat)}")
    results = []
    for depth in (10, 20, 40):
        found = eligible = 0
        for account in picked:
            own = sorted((p for p in posts if str(p.account_id) == account and not p.is_repost),
                         key=lambda p: p.published_at)
            additions = defaultdict(list)
            usable = True
            for day in (12, 25):
                moment = AS_OF - timedelta(days=30) + timedelta(days=day, hours=14)
                older = [p for p in own if p.published_at <= moment - timedelta(days=1)]
                if len(older) < depth:
                    usable = False
                    break
                for p in older[-depth:]:
                    additions[p.publication_id] += [(int(moment.timestamp() // 3600) + h, 800, 0) for h in range(6)]
            if not usable:
                continue
            eligible += 1
            changed = [replace(p, ledger=replace(p.ledger, surges=tuple(sorted(p.ledger.surges + tuple(additions[p.publication_id])))))
                       if p.publication_id in additions else p for p in posts]
            found += any(str(f.account_id) == account and f.status == 2 for f in wave_findings(changed, COMPUTED_FOR))
        results.append(("waves_status2", depth, found, eligible))
    for night in (0.6, 1.0):
        found = 0
        for account in picked:
            def lift(p):
                if str(p.account_id) != account or p.ledger.hours is None:
                    return p
                views = p.ledger.hours[0]
                flat_add = int(max(views) * night)
                return replace(p, ledger=replace(p.ledger, hours=(tuple(v + flat_add for v in views), p.ledger.hours[1])))
            found += any(str(f.account_id) == account for f in flat_day_findings([lift(p) for p in posts], COMPUTED_FOR))
        results.append(("flat_night", night, found, len(picked)))
    for kind, value, found, total in results:
        print(f"  {kind} {value}: found {found}/{total}")
    with open(f"{out}/synthetic_ledgers.csv", "w", newline="") as handle:
        csv.writer(handle).writerows([("kind", "param", "found", "total"), *results])


if __name__ == "__main__":
    base, cand, out, part = sys.argv[1:5]
    (posts_part if part == "posts" else ledgers_part)(base, cand, out)
