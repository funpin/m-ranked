"""Share of reactions per wall view in the first minutes, VK posts (videos excluded)."""
import json, sys, bisect, statistics
from collections import defaultdict
data = {}
for f in sys.argv[1:]:
    data.update(json.load(open(f)))
def at(pts, age, m):
    ages = [p["ageHours"] for p in pts]; i = bisect.bisect_right(ages, age) - 1
    while i >= 0 and (pts[i][m] or {}).get("value") is None: i -= 1
    return (pts[i][m] or {}).get("value") if i >= 0 else None
rows = defaultdict(list)
for key, e in data.items():
    meta = e["meta"]
    if (meta.get("platform") or "vk") != "vk" or meta.get("publicationType") == "video": continue
    pts = sorted(e["points"], key=lambda p: p["ageHours"])
    if not pts or pts[0]["ageHours"] > 0.15: continue
    out = {}
    for label, age in (("15m", 0.25), ("1h", 1.0)):
        v, r = at(pts, age, "views"), at(pts, age, "reactions")
        out[label] = (r / v) if v and v >= 20 and r is not None else None
    acc = e.get("account") or key.split(":")[1]
    rows[acc].append(out)
summary = []
for acc, items in rows.items():
    s15 = [x["15m"] for x in items if x["15m"] is not None]; s1 = [x["1h"] for x in items if x["1h"] is not None]
    if len(s15) < 3: continue
    summary.append((acc, len(s15), round(statistics.median(s15), 3), round(max(s15), 3), round(statistics.median(s1), 3) if s1 else None,
                    sum(1 for x in s15 if x >= 0.4)))
summary.sort(key=lambda r: -r[2])
print("account | posts | median R/V at 15 min | max | median at 1 h | posts ≥ 40 % at 15 min")
for r in summary: print(" | ".join(map(str, r)))
