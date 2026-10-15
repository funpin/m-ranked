"""Per-post features of a paid-promotion wave, on an hourly calendar grid (MSK)."""
import bisect, json, statistics, sys
from datetime import datetime, timedelta, timezone
MSK = timezone(timedelta(hours=3))
H = timedelta(hours=1)

def hourly(entry, start, end):
    pts = sorted(entry["points"], key=lambda p: p["observedAt"])
    ts = [datetime.fromisoformat(p["observedAt"]) for p in pts]
    def val(t, m):
        i = bisect.bisect_right(ts, t) - 1
        while i >= 0 and (pts[i][m] or {}).get("value") is None: i -= 1
        return (pts[i][m] or {}).get("value", 0) if i >= 0 else 0
    cells, t = [], start
    while t < end:
        cells.append((t, val(t + H, "views") - val(t, "views"), val(t + H, "reactions") - val(t, "reactions")))
        t += H
    return cells

def features(entry, start, end):
    """start/end — window of the suspected wave (aware datetimes)."""
    published = datetime.fromisoformat(entry["meta"]["publishedAt"])
    wave = hourly(entry, start, end)
    before_start = max(published + timedelta(hours=24), start - timedelta(hours=48))
    before = hourly(entry, before_start, start) if before_start < start else []
    after = hourly(entry, end, end + timedelta(hours=12))
    v = sum(c[1] for c in wave); r = sum(c[2] for c in wave)
    night = [c[1] for c in wave if c[0].astimezone(MSK).hour < 6]
    day = [c[1] for c in wave if 9 <= c[0].astimezone(MSK).hour < 21]
    last3 = sum(c[1] for c in wave[-3:]) / 3 if len(wave) >= 3 else 0
    first_after = sum(c[1] for c in after[:6]) / 6 if after else None
    early = hourly(entry, published, published + timedelta(hours=24))
    ev, er = sum(c[1] for c in early), sum(c[2] for c in early)
    return {
        "ageAtOnsetH": round((start - published).total_seconds() / 3600, 1),
        "waveViews": v, "waveReactions": r, "waveRate": round(v / max(len(wave), 1), 1),
        "beforeRate": round(sum(c[1] for c in before) / len(before), 1) if before else None,
        "nightToDay": round(statistics.mean(night) / max(statistics.mean(day), 1e-9), 2) if night and day else None,
        "wavePerK": round(1000 * r / max(v, 1), 2), "firstDayPerK": round(1000 * er / max(ev, 1), 2),
        "stopRatio": round(last3 / max(first_after, 0.5), 1) if first_after is not None else None,
    }

if __name__ == "__main__":
    data = json.load(open(sys.argv[1]))
    start = datetime.fromisoformat(sys.argv[2]).replace(tzinfo=MSK); end = datetime.fromisoformat(sys.argv[3]).replace(tzinfo=MSK)
    for name in sys.argv[4].split(","):
        print(name, data[name]["meta"]["externalId"], features(data[name], start, end))
