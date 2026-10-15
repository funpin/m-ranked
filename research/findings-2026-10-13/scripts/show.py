import json, sys
from datetime import datetime, timezone, timedelta
d = json.load(open(sys.argv[1]))[sys.argv[2]]
pts = sorted(d["points"], key=lambda p: p["observedAt"])
lo, hi = float(sys.argv[3]) if len(sys.argv) > 3 else 0, float(sys.argv[4]) if len(sys.argv) > 4 else 1e9
prev = None
msk = timezone(timedelta(hours=3))
for p in pts:
    a = p["ageHours"]
    if not (lo <= a <= hi): prev = p; continue
    gap = a - prev["ageHours"] if prev else 0
    t = datetime.fromisoformat(p["observedAt"]).astimezone(msk).strftime("%d.%m %H:%M")
    v = lambda m: (p[m] or {}).get("value")
    print(f"{a:8.2f}h {t} gap={gap:6.2f}h V={v('views')} R={v('reactions')} C={v('comments')} S={v('shares')} q={p['quality']} unc={p['intervalUncertain']} syn={p['synthetic']}")
    prev = p
