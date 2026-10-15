import json, statistics, sys
data = json.load(open(sys.argv[1]))
V_RATIO, ER_RATIO, MIN_RUN = 1.4, 0.8, 3
rows = []
for acc_id, entry in data.items():
    a, pts = entry["account"], [p for p in entry["daily"].get("points", []) if p["day"] < "2026-10-13"]
    if len(pts) < 14: continue
    from datetime import date
    weekend = lambda p: date.fromisoformat(p["day"]).weekday() >= 5
    views = [p["totalViews"] or 0 for p in pts]
    med_v = statistics.median(views)
    base = {kind: statistics.median([p["totalViews"] or 0 for p in pts if weekend(p) == kind] or [med_v]) for kind in (False, True)}
    ers = [p["totalReactions"] / p["totalViews"] for p in pts if p["totalViews"]]
    med_er = statistics.median(ers) if ers else 0
    if med_v < 200: continue
    run = []
    def flush():
        if len(run) >= MIN_RUN:
            v = sum(p["totalViews"] for p in run); r = sum(p["totalReactions"] for p in run)
            er_ratio = (r / v) / med_er if med_er else 0
            if er_ratio <= ER_RATIO:
                rows.append((a["institution"], a["platform"], a["username"], run[0]["day"], run[-1]["day"], len(run),
                             round(sum(p["totalViews"] / max(base[weekend(p)], 1) for p in run) / len(run), 2), round(er_ratio, 2), int(sum(p["totalViews"] - base[weekend(p)] for p in run)), acc_id))
    for p in pts:
        if (p["totalViews"] or 0) >= V_RATIO * max(base[weekend(p)], 1): run.append(p)
        else: flush(); run = []
    flush()
rows.sort(key=lambda r: -r[8])
print(f"{len(data)} accounts; {len(rows)} runs")
for r in rows: print(" | ".join(map(str, r[:9])))
json.dump(rows, open(sys.argv[2], "w"), ensure_ascii=False)
