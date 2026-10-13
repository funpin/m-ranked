import json, sys, api
def accounts(q):
    r = api.get("/api/v1/overview", q=q, limit=5)
    return [(it["shortName"], a) for it in r["items"] for a in it.get("accounts", [])]
def find(account_id, number, pages=6):
    cursor = None
    for _ in range(pages):
        r = api.get(f"/api/v1/accounts/{account_id}/publications", limit=200, cursor=cursor)
        for it in r["items"]:
            ext = it["externalId"] or ""
            if ext.split("_")[-1] == str(number) or ext.removeprefix("m:") == str(number):
                return it
        cursor = r.get("nextCursor")
        if not cursor: return None
def history(pid):
    pts, cursor = [], None
    while True:
        r = api.get(f"/api/v1/publications/{pid}/history", limit=3000, cursor=cursor)
        pts += r.get("items") or r.get("points") or []
        cursor = r.get("nextCursor")
        if not cursor: return r, pts
if __name__ == "__main__":
    for q in sys.argv[1:]:
        for name, a in accounts(q):
            print(q, "|", name, a["platform"], a["accountId"], a["username"], a["subscriberCount"])
