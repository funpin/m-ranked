import json, numpy as np, sys
d = json.load(open('b1.json'))
def lift(f):
    if f['preV'] < 50 or f['epV'] <= 0: return None
    return (f['epR'] / f['epV']) / ((f['preR'] + 1) / (f['preV'] + 1))
for typ in ('video', 'other'):
    eps = [f for f in d.values() if 'epR' in f and f['epR'] >= 30 and ((f['type'] == 'video') == (typ == 'video'))]
    print(f"== {typ}: posts {sum(1 for f in d.values() if (f['type']=='video')==(typ=='video'))}, episodes >=30 reactions {len(eps)}")
    ns = np.array([f['night'] for f in eps])
    print(" night share pctl 50/90/95/99/max:", np.round(np.percentile(ns, [50, 90, 95, 99, 100]), 3))
    for th in (0.2, 0.3, 0.4): print(f"  night>={th}: {(ns>=th).sum()}")
    lf = np.array([x for x in (lift(f) for f in eps) if x is not None])
    print(" lift n", lf.size, "pctl 50/90/95/99/max:", np.round(np.percentile(lf, [50, 90, 95, 99, 100]), 1))
    for th in (5, 10, 20, 40): print(f"  lift>={th}: {(lf>=th).sum()}")
    cl = [f for f in eps if f['cliff'] and f['cliff']['afterR'] == 0 and f['cliff']['afterV'] > 0]
    rates = np.array([f['cliff']['lastRate'] for f in cl])
    print(" cliffs to zero with views:", len(cl), "lastRate pctl 50/90/max", np.round(np.percentile(rates, [50, 90, 100]), 1) if len(cl) else None)
    for th in (5, 10, 20, 30): print(f"  cliff lastRate>={th}: {(rates>=th).sum()}")
    combo = [f for f in eps if f['night'] >= 0.3 and (lift(f) or 0) >= 10]
    print(" night>=.3 & lift>=10:", [(f['username'], round(f['night'],2), round(lift(f),1), f['epR'], f['cliff'] and round(f['cliff']['lastRate'],1)) for f in combo][:30])
