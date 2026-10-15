import pickle, sys, collections, statistics
from datetime import date, timedelta
import anomaly_analysis.v2.reach_findings as rf
items, names = pickle.load(open(sys.argv[1], 'rb'))
MFTI = ('26aabf8e', '5d9369ab', 'f3e2f2e7', 'bb6f379e', '85b17359')
day = date(2026, 10, 14); start = day - timedelta(days=rf.WINDOW_DAYS)
def evaluate(excess, shared, strong_days, strong_excess, strong_views, show=False):
    rf.PROMOTION_EXCESS = excess
    by = {a: [p for p in ps if p.platform in rf.PROMOTION_PLATFORMS and p.ledger.days] for a, ps in rf._own(items, day).items()}
    cands = {a: rf._promotion_days(ps, start, day) for a, ps in by.items() if ps}
    busy = collections.Counter(d for f in cands.values() for d in {i[1] for days in f.values() for i in days})
    limit = max(2, rf.WAVE_PLATFORM_SHARE * len(cands))
    out = {}
    for a, found in cands.items():
        runs = {}
        for pid, days in found.items():
            run = rf._longest_run([i for i in days if busy[i[1]] < limit])
            if len(run) >= rf.PROMOTION_MIN_DAYS: runs[pid] = run
        keep = {}
        for pid, run in runs.items():
            mine = {i[1] for i in run}
            campaign = any(len(mine & {i[1] for i in other}) >= shared for o, other in runs.items() if o != pid)
            strong = (len(run) >= strong_days and statistics.median(i[4] for i in run) >= strong_excess
                      and sum(i[2] for i in run) >= strong_views)
            if campaign or strong: keep[pid] = ("campaign" if campaign else "strong", len(run), run[0][1][5:], round(statistics.median(i[4] for i in run)), sum(i[2] for i in run))
        if keep: out[a] = keep
    posts = {str(p) for k in out.values() for p in k}
    tp = sum(any(m.startswith(p) for m in posts) for p in MFTI)
    print(f"x{excess:g} shared>={shared} strong {strong_days}d x{strong_excess} {strong_views}v: accounts {len(out)} posts {len(posts)} MFTI {tp}/5")
    if show:
        for a, k in sorted(out.items(), key=lambda kv: -len(kv[1])):
            print(f"   {names[a]:22s}", sorted(k.values(), key=lambda r: r[2]))
for args in ((10., 2, 3, 20, 5000), (10., 2, 3, 30, 10000), (10., 2, 4, 20, 10000), (10., 3, 3, 20, 5000), (5., 2, 3, 20, 5000)):
    evaluate(*args)
evaluate(10., 2, 3, 20, 5000, show=True)
