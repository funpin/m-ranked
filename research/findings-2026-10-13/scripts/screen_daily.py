import os
import json, api
accounts = [a for a in json.load(open(os.environ.get("MR_WORK", ".") + "/accounts.json")) if a["platform"] in ("vk", "telegram", "max") and a["enabled"]]
out = {}
for i, a in enumerate(accounts):
    out[a["accountId"]] = {"account": a, "daily": api.get(f"/api/v1/accounts/{a['accountId']}/daily-series")}
    if i % 25 == 0:
        print(i, flush=True); json.dump(out, open(os.environ.get("MR_WORK", ".") + "/daily_all.json", "w"), ensure_ascii=False)
json.dump(out, open(os.environ.get("MR_WORK", ".") + "/daily_all.json", "w"), ensure_ascii=False)
print("done", len(out))
