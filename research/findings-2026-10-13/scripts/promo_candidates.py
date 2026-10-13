import os
import json, statistics, sys
from collections import defaultdict
from datetime import datetime, timedelta, date
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from promo_features import features, MSK
SP = os.environ.get("MR_WORK", ".")
posts = json.load(open(f"{SP}/stage2_posts.json"))
EXCESS, RESPONSE, NIGHT, STOP = 5.0, 0.35, 0.6, 8.0
by_run = defaultdict(list)
for key, e in posts.items():
    by_run[tuple(e["run"][:5])].append((key, e))
rows = []
for run, items in by_run.items():
    inst, platform, user, first, last = run
    start = datetime.combine(date.fromisoformat(first) - timedelta(days=1), datetime.min.time(), MSK)
    end = datetime.combine(date.fromisoformat(last) + timedelta(days=1), datetime.min.time(), MSK)
    feats = {}
    for key, e in items:
        pub = datetime.fromisoformat(e["meta"]["publishedAt"])
        s = max(start, pub + timedelta(hours=6))
        if s >= end - timedelta(hours=24): continue
        feats[key] = features(e, s, end)
    controls = [f["waveRate"] for k, f in feats.items() if not dict(items)[k]["hot"]]
    base = statistics.median(controls) if controls else None
    for key, f in feats.items():
        excess = f["waveRate"] / max(base, 0.5) if base is not None else None
        resp = f["wavePerK"] / f["firstDayPerK"] if f["firstDayPerK"] else (0 if f["wavePerK"] < 1 else 9)
        ok = (excess is not None and excess >= EXCESS and resp <= RESPONSE
              and f["nightToDay"] is not None and f["nightToDay"] <= NIGHT)
        rows.append({"key": key, "inst": inst, "platform": platform, "run": f"{first}..{last}", "hot": dict(items)[key]["hot"],
                     "excess": round(excess, 1) if excess is not None else None, "response": round(resp, 2),
                     "stop": f["stopRatio"] is not None and f["stopRatio"] >= STOP, "candidate": ok, **f,
                     "window": [start.isoformat(), end.isoformat()]})
json.dump(rows, open(f"{SP}/promo_rows.json", "w"), ensure_ascii=False)
cand = [r for r in rows if r["candidate"]]
print(len(rows), "posts checked;", len(cand), "candidates")
by = defaultdict(list)
for r in cand: by[(r["inst"], r["platform"], r["run"])].append(r)
for k, rs in sorted(by.items(), key=lambda x: -len(x[1])):
    print(k, len(rs), [(r["key"].split(":")[-1], r["excess"], r["response"], r["nightToDay"], r["stopRatio"]) for r in rs][:8])
