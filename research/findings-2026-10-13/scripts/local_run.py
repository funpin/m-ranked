"""Rebuild a post's series from public-API history and run the v2 analysis locally."""
import json, sys
from datetime import datetime
from uuid import UUID

from anomaly_analysis.v2.store import series_from_rows
from anomaly_analysis.v2.levels import assess, compact
from anomaly_analysis.v2.domain import Metric

PLATFORM = {"vk": "vk", "telegram": "telegram", "max": "max", "rutube": "rutube"}

def series(entry, platform):
    meta = entry["meta"]
    pts = sorted(entry["points"], key=lambda p: p["observedAt"])
    rows, seen = [], set()
    for p in pts:
        if p["observedAt"] in seen: continue
        seen.add(p["observedAt"])
        row = {"id": UUID(meta["publicationId"]), "primary_account_id": UUID(int=0), "platform": platform,
               "published_at": datetime.fromisoformat(meta["publishedAt"]), "is_repost": bool(meta.get("repost")),
               "observed_at": datetime.fromisoformat(p["observedAt"]), "interval_uncertain": bool(p.get("intervalUncertain")),
               "reaction_breakdown": p.get("reactionsBreakdown") or None, "publication_type": meta.get("publicationType")}
        for m in Metric:
            cell = p.get(m.value) or {}
            row[f"{m.value}_count"] = cell.get("value")
            row[f"{m.value}_quality"] = cell.get("quality") or ("missing" if cell.get("value") is None else p.get("quality"))
        rows.append(row)
    return series_from_rows(rows)

def run(entry, platform, analyzed_at=None):
    s = series(entry, platform)
    moment = datetime.fromisoformat(analyzed_at) if analyzed_at else None
    return assess(s, analyzed_at=moment)

if __name__ == "__main__":
    data = json.load(open(sys.argv[1]))
    for name in sys.argv[2:]:
        e = data[name]
        platform = "telegram" if e["meta"]["externalId"].startswith("m:") else "vk"
        v = run(e, platform, e["analysis"].get("analyzedAt"))
        c = compact(v)
        print(name, "local level", c.get("level"), "| prod level", e["analysis"]["level"])
        for s in v.signs:
            print("   ", s.pattern, s.metric.value, s.interval.start.isoformat()[:16], s.interval.end.isoformat()[:16], round(s.strength, 2), s.formula[:140])
