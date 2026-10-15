"""Read-only GET client for the public site API: sequential, >=1 s apart, disk cache."""
import hashlib, json, os, sys, time, urllib.parse, urllib.request
BASE = os.environ["MR_BASE"]  # адрес сайта задаётся при запуске
CACHE = os.path.join(os.environ.get("MR_WORK", "."), "cache")
os.makedirs(CACHE, exist_ok=True)
_last = [0.0]
def get(path, **query):
    query = {k: v for k, v in query.items() if v is not None}
    url = BASE + path + ("?" + urllib.parse.urlencode(query) if query else "")
    key = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest() + ".json")
    if os.path.exists(key):
        return json.load(open(key))
    wait = 1.0 - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "m-ranked-analysis-readonly"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        body = {"_status": e.code, "_error": e.read()[:500].decode("utf-8", "replace")}
    _last[0] = time.time()
    body_meta = {"_url": url, "_seconds": round(_last[0] - t, 3)}
    if isinstance(body, dict): body.setdefault("_meta", body_meta)
    json.dump(body, open(key, "w"), ensure_ascii=False)
    return body
if __name__ == "__main__":
    path, *pairs = sys.argv[1:]
    print(json.dumps(get(path, **dict(p.split("=", 1) for p in pairs)), ensure_ascii=False, indent=1)[:6000])
