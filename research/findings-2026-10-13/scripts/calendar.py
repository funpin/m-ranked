import json, sys, bisect
from datetime import datetime, timezone, timedelta
msk = timezone(timedelta(hours=3))
data = json.load(open(sys.argv[1])); names = sys.argv[2].split(",")
start = datetime.fromisoformat(sys.argv[3]).replace(tzinfo=msk); end = datetime.fromisoformat(sys.argv[4]).replace(tzinfo=msk)
step = timedelta(hours=float(sys.argv[5])); metric = sys.argv[6] if len(sys.argv) > 6 else "views"
series = {}
for n in names:
    pts = sorted(data[n]["points"], key=lambda p: p["observedAt"])
    ts = [datetime.fromisoformat(p["observedAt"]) for p in pts]
    series[n] = (ts, pts)
def val(n, t, m):
    ts, pts = series[n]; i = bisect.bisect_right(ts, t) - 1
    while i >= 0 and (pts[i][m] or {}).get("value") is None: i -= 1
    return (pts[i][m] or {}).get("value", 0) if i >= 0 else 0
print("MSK          " + " ".join(f"{n[-9:]:>16}" for n in names))
t = start
while t < end:
    cells = []
    for n in names:
        dv = val(n, t + step, "views") - val(n, t, "views"); dr = val(n, t + step, "reactions") - val(n, t, "reactions")
        ds = val(n, t + step, "shares") - val(n, t, "shares")
        cells.append(f"{dv:7d}/{dr:4d}/{ds:3d}")
    print(t.strftime("%d.%m %H:%M"), " ".join(f"{c:>16}" for c in cells))
    t += step
