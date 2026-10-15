"""View packs: a flat-rate inflow of views for >=2 hours that stops abruptly.

Per post, hourly view increments by age (research.pha). A run is a maximal
stretch of hours whose rate is >= half the run maximum and >= MIN_RATE. The
run is a pack when it lasts 2..10 hours, the hour after it (and the one after
that) drop below CLIFF x the run mean, and the run is not the natural first
hours decay (rate inside the run does not fall monotonically by >2x).

Input (from build.sql tables), in directory DIR:
  \copy (select pid, ah, dv, dr, extract(epoch from maxgap)::int gap from research.pha order by pid, ah) to DIR/pha.csv csv header
  \copy (select id pid, account_id, platform, uname, institution_id, published_at, is_repost, publication_type,
         a0, v1h, v24, v72, vmx, r24, rmx, lvl, sig from research.pfa) to DIR/pfa.csv csv header
Run: python3 -I viewpack.py DIR   ->  DIR/viewpacks.csv and a per-account table.
"""
import sys
import numpy as np
import pandas as pd

S = sys.argv[1]
MIN_RATE = 150
CLIFF = 0.2

pha = pd.read_csv(f"{S}/pha.csv")
pfa = pd.read_csv(f"{S}/pfa.csv")
meta = pfa.set_index("pid")

rows = []
for pid, g in pha.groupby("pid", sort=False):
    ah = g.ah.to_numpy()
    H = int(ah.max()) + 1
    if H < 4:
        continue
    dv = np.zeros(H); dr = np.zeros(H); seen = np.zeros(H, bool)
    dv[ah] = g.dv.fillna(0).to_numpy(); dr[ah] = g.dr.fillna(0).to_numpy(); seen[ah] = True
    i = 0
    while i < H:
        if dv[i] < MIN_RATE:
            i += 1; continue
        j = i
        peak = dv[i]
        while j + 1 < H and dv[j + 1] >= max(MIN_RATE, 0.5 * max(peak, dv[j + 1])):
            j += 1; peak = max(peak, dv[j])
        L = j - i + 1
        run = dv[i:j + 1]
        mean = run.mean()
        after = dv[j + 1:j + 3]
        before = dv[max(0, i - 2):i]
        ok = (2 <= L <= 10 and len(after) == 2 and seen[j + 1:j + 3].all()
              and after.max() <= CLIFF * mean
              and run.min() >= 0.5 * run.max())
        if ok:
            prior = dv[:i].sum()
            rows.append(dict(pid=pid, start_h=i, hours=L, rate=mean, views=run.sum(), reacts=dr[i:j + 1].sum(),
                             before_rate=before.mean() if len(before) else np.nan, prior_views=prior,
                             after_rate=after.mean()))
        i = j + 1

res = pd.DataFrame(rows)
res = res.join(meta[["account_id", "platform", "uname", "published_at", "vmx", "rmx", "lvl", "sig", "is_repost"]], on="pid")
res["r_per_k"] = 1000 * res.reacts / res.views
res["post_r_per_k"] = 1000 * res.rmx / res.vmx
res.to_csv(f"{S}/viewpacks.csv", index=False)

posts = pfa.groupby(["platform", "uname", "account_id"]).size().rename("posts")
agg = res.groupby(["platform", "uname", "account_id"]).agg(
    pack_posts=("pid", "nunique"), packs=("pid", "size"), pack_views=("views", "sum"),
    med_rate=("rate", "median"), med_hours=("hours", "median"), med_start=("start_h", "median"),
    r_per_k=("r_per_k", "median"), post_r_per_k=("post_r_per_k", "median"),
    lvl0=("lvl", lambda s: int((s.fillna(0) == 0).sum())))
agg = agg.join(posts).join(pfa.groupby("account_id").vmx.sum().rename("acc_views"), on="account_id")
agg["share_posts"] = agg.pack_posts / agg.posts
agg["share_views"] = agg.pack_views / agg.acc_views
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 200)
print(res.groupby("platform").size())
print(agg.sort_values("share_posts", ascending=False).head(40).round(3).to_string())
