"""B1 features on VK posts: reaction episode on an hourly MSK grid.

Hour cell is known when the readings bracketing both its edges are at most
MAX_GAP apart (or equal edges = proved plateau). Episode: peak hour of
reactions, widened over hours >= max(FLOOR, peak*SHARE), up to one weak hour.
"""
import pickle, sys, json, math
import numpy as np
H = 3600.0
MAX_GAP = 1.6 * H
FLOOR, SHARE = 3.0, 0.2
DIP = 2
MSK = 3 * H

def grid(points, col):
    pts = [(p[0], p[col]) for p in points if p[col] is not None]
    if len(pts) < 3: return None
    t = np.array([p[0] for p in pts]); v = np.maximum.accumulate(np.array([p[1] for p in pts], float))
    h0 = math.ceil((t[0] + MSK) / H) * H - MSK; h1 = math.floor((t[-1] + MSK) / H) * H - MSK
    if h1 - h0 < 3 * H: return None
    edges = np.arange(h0, h1 + 1, H)
    c = np.interp(edges, t, v)
    idx = np.searchsorted(t, edges)  # first reading >= edge
    lo = np.clip(idx - 1, 0, len(t) - 1); hi = np.clip(idx, 0, len(t) - 1)
    exact = t[hi] == edges
    gap = np.where(exact, 0, t[hi] - t[lo]); flat = v[hi] == v[lo]
    ok_edge = (gap <= MAX_GAP) | flat
    known = ok_edge[:-1] & ok_edge[1:]
    return edges, c, known

def features(post):
    g = grid(post["points"], 2); gv = grid(post["points"], 1)
    if g is None or gv is None: return None
    edges, cr, known = g
    cv = np.interp(edges, gv[0], gv[1]); kv = np.interp(edges[:-1], gv[0][:-1], gv[2].astype(float)) > .5
    r = np.diff(cr); vv = np.diff(cv)
    k = known & kv
    if not k.any(): return None
    rr = np.where(k, r, -1)
    p = int(rr.argmax()); peak = r[p]
    if peak < FLOOR: return {"peak": float(peak)}
    thr = max(FLOOR, peak * SHARE)
    b = p
    while True:
        nxt = next((j for j in range(b - 1, max(-1, b - 2 - DIP), -1) if k[j] and r[j] >= thr), None)
        if nxt is None or not k[nxt:b].all(): break
        b = nxt
    e = p
    while True:
        nxt = next((j for j in range(e + 1, min(len(r), e + 2 + DIP)) if k[j] and r[j] >= thr), None)
        if nxt is None or not k[e + 1:nxt + 1].all(): break
        e = nxt
    hours = ((edges[b:e + 1] + MSK) % 86400) // H
    ep_r = float(r[b:e + 1].sum()); ep_v = float(vv[b:e + 1].sum())
    night = float(r[b:e + 1][hours < 6].sum())
    start_age = (edges[b] - post["published"]) / H
    # before: from publication (or 12 h) to episode start
    pre0 = max(0, b - 12)
    pre_r = float(r[pre0:b].sum()); pre_v = float(vv[pre0:b].sum()); pre_known = bool(k[pre0:b].all()) if b > pre0 else False
    # cliff: after episode, >=4 known hours with zero reactions, views continuing
    cliff = None
    if e + 4 < len(r) and k[e + 1:e + 5].all():
        after_r = float(r[e + 1:e + 5].sum()); after_v = float(vv[e + 1:e + 5].sum())
        last = float(r[max(b, e - 1):e + 1].mean())
        cliff = {"lastRate": last, "afterR": after_r, "afterV": after_v}
    return {"peak": float(peak), "start_age": start_age, "hours": int(e - b + 1), "epR": ep_r, "epV": ep_v,
            "night": night / ep_r if ep_r else 0.0, "preR": pre_r, "preV": pre_v, "preKnown": pre_known,
            "preHours": int(b - pre0), "cliff": cliff, "startMsk": int(hours[0]), "endMsk": int(hours[-1])}

if __name__ == "__main__":
    posts = pickle.load(open(sys.argv[1], "rb"))
    out = {}
    for post in posts:
        f = features(post)
        if f: out[post["id"]] = {**f, "type": post["type"], "username": post["username"], "published": post["published"]}
    json.dump(out, open(sys.argv[2], "w"))
    print(len(out))
