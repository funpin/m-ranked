import os
import json, random, api, find_posts as fp
random.seed(20261013)
accounts = [a for a in json.load(open(os.environ.get("MR_WORK", ".") + "/accounts.json")) if a["enabled"]]
by = {p: [a for a in accounts if a["platform"] == p] for p in ("vk", "telegram", "max")}
chosen = random.sample(by["vk"], 12) + random.sample(by["telegram"], 8) + random.sample(by["max"], 8)
mirea = [a for a in by["vk"] if a["institution"].startswith("РТУ МИРЭА") or a["username"] in ("rtumirea", "mirea_official")]
out = {}
def take(a, k):
    r = api.get(f"/api/v1/accounts/{a['accountId']}/publications", limit=200)
    items = [it for it in r["items"] if "2026-09-22" <= it["publishedAt"][:10] <= "2026-10-12" and not it.get("repost")]
    picked = items if k is None else random.sample(items, min(k, len(items)))
    for it in picked:
        _, pts = fp.history(it["publicationId"])
        out[f"{a['platform']}:{a['username']}:{it['externalId']}"] = {
            "meta": {**it, "platform": a["platform"]}, "points": pts, "analysis": {"analyzedAt": None},
            "account": a["username"], "institution": a["institution"]}
    json.dump(out, open(os.environ.get("MR_WORK", ".") + "/sample_posts.json", "w"), ensure_ascii=False)
    print(a["platform"], a["username"], len(picked), flush=True)
for a in mirea: take(a, None)
for a in chosen:
    if a not in mirea: take(a, 10)
print("done", len(out))
