"""VK cohort sample for thresholds: every enabled VK account, posts of 15.09–12.10,
up to 12 random non-video and 6 random video posts per account (read-only, ≤ 1 rps)."""
import hashlib, json, os, random, urllib.parse
import api
random.seed(20261014)
WORK = os.environ.get("MR_WORK", ".")
accounts = [a for a in json.load(open(f"{WORK}/accounts.json")) if a["platform"] == "vk" and a["enabled"]]
path = f"{WORK}/cohort_vk.json"
FIELDS = ("views", "reactions", "comments", "shares")


def slim(point):
    """Только то, что читает series_from_rows: ~5 % исходного ответа."""
    out = {"observedAt": point["observedAt"], "ageHours": point["ageHours"],
           "intervalUncertain": point.get("intervalUncertain"), "quality": point.get("quality")}
    for field in FIELDS:
        cell = point.get(field) or {}
        out[field] = {"value": cell.get("value"), "quality": cell.get("quality")}
    return out


def history(publication_id):
    """История поста без дискового кэша сырых ответов: они весят ~0,5 МБ на пост."""
    points, cursor = [], None
    while True:
        query = {"limit": 3000, "cursor": cursor}
        r = api.get(f"/api/v1/publications/{publication_id}/history", **query)
        url = api.BASE + f"/api/v1/publications/{publication_id}/history?" + urllib.parse.urlencode(
            {k: v for k, v in query.items() if v is not None})
        cached = os.path.join(api.CACHE, hashlib.sha1(url.encode()).hexdigest() + ".json")
        if os.path.exists(cached):
            os.remove(cached)
        points += [slim(point) for point in (r.get("items") or r.get("points") or [])]
        cursor = r.get("nextCursor")
        if not cursor:
            return points
out = json.load(open(path)) if os.path.exists(path) else {}
for entry in out.values():
    entry["points"] = [slim(point) for point in entry["points"]]
for a in accounts:
    r = api.get(f"/api/v1/accounts/{a['accountId']}/publications", limit=200)
    items = [it for it in r.get("items", []) if "2026-09-15" <= it["publishedAt"][:10] <= "2026-10-12" and not it.get("repost")]
    videos = [it for it in items if it.get("publicationType") == "video"]
    others = [it for it in items if it.get("publicationType") != "video"]
    picked = random.sample(others, min(12, len(others))) + random.sample(videos, min(6, len(videos)))
    for it in picked:
        key = f"vk:{a['username']}:{it['externalId']}"
        if key in out: continue
        pts = history(it["publicationId"])
        out[key] = {"meta": {**it, "platform": "vk"}, "points": pts, "analysis": {"analyzedAt": None},
                    "account": a["username"], "institution": a["institution"], "subscribers": a.get("subscriberCount")}
    json.dump(out, open(path, "w"), ensure_ascii=False)
    print(a["username"], len(picked), len(out), flush=True)
print("done", len(out))
