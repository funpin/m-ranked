import pickle, numpy as np, collections, statistics
posts = pickle.load(open('vk.pkl', 'rb'))
by = collections.defaultdict(list)
for p in posts:
    if p['type'] == 'video': continue
    pts = [x for x in p['points'] if x[1] is not None and x[2] is not None]
    if not pts: continue
    age = pts[0][0] - p['published']
    if age > 1800 or pts[0][1] < 20: continue
    by[p['username']].append(pts[0][2] / pts[0][1])
print("accounts", len(by), "posts", sum(map(len, by.values())))
eligible = {a: v for a, v in by.items() if len(v) >= 10}
print("accounts with >=10 posts", len(eligible))
for T in (0.15, 0.2, 0.25, 0.3, 0.4):
    share = {a: sum(x >= T for x in v) / len(v) for a, v in eligible.items()}
    others = sorted(share.values())
    def p90_without(a):
        o = [s for b, s in share.items() if b != a]
        return statistics.quantiles(o, n=10, method='inclusive')[-1]
    top = sorted(share.items(), key=lambda x: -x[1])[:6]
    print(f"T={T}: p90 {statistics.quantiles(others, n=10, method='inclusive')[-1]:.3f}; top", [(a, round(s, 3), len(eligible[a]), round(p90_without(a), 3)) for a, s in top])
med = sorted(((round(statistics.median(v), 3), a, len(v)) for a, v in eligible.items()), reverse=True)[:8]
print("median R/V first:", med)
