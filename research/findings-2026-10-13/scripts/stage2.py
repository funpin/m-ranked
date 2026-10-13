"""Promotion candidates: posts of screened accounts, features inside the screened window."""
import os
import json, random, statistics
from datetime import datetime, timedelta, timezone, date
import api, find_posts as fp
from promo_features import features, MSK
random.seed(7)
runs = json.load(open(os.environ.get("MR_WORK", ".") + "/screen_all.json"))
accounts = {a["accountId"]: a for a in json.load(open(os.environ.get("MR_WORK", ".") + "/accounts.json"))}
out = json.load(open(os.environ.get("MR_WORK", ".") + "/stage2_posts.json")) if os.path.exists(os.environ.get("MR_WORK", ".") + "/stage2_posts.json") else {}
for run in runs:
    inst, platform, user, first, last, days, vratio, erratio, excess, acc_id = run
    lo = (date.fromisoformat(first) - timedelta(days=10)).isoformat()
    r = api.get(f"/api/v1/accounts/{acc_id}/publications", limit=200)
    items = [it for it in r["items"] if lo <= it["publishedAt"][:10] <= last and not it.get("repost")]
    if not items: continue
    med = statistics.median([(it["views"] or {}).get("value") or 0 for it in r["items"]])
    hot = [it for it in items if ((it["views"] or {}).get("value") or 0) >= 2 * med]
    rest = [it for it in items if it not in hot]
    picked = hot[:15] + random.sample(rest, min(5, len(rest)))
    for it in picked:
        key = f"{platform}:{user}:{it['externalId']}"
        if key in out: continue
        _, pts = fp.history(it["publicationId"])
        out[key] = {"meta": {**it, "platform": platform}, "points": pts, "run": run, "accountMedianViews": med,
                    "hot": it in hot, "analysis": {"analyzedAt": None}}
    json.dump(out, open(os.environ.get("MR_WORK", ".") + "/stage2_posts.json", "w"), ensure_ascii=False)
    print(inst, platform, len(items), "hot", len(hot), flush=True)
print("done", len(out))
