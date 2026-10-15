import pickle, sys, collections
from datetime import date
import anomaly_analysis.v2.reach_findings as rf
items, names = pickle.load(open(sys.argv[1], 'rb'))
MFTI = ('26aabf8e', '5d9369ab', 'f3e2f2e7', 'bb6f379e', '85b17359')
mipt = next(a for a, n in names.items() if n == 'miptru')
day = date(2026, 10, 14)
def run(label, **kw):
    saved = {k: getattr(rf, k) for k in kw}
    for k, v in kw.items(): setattr(rf, k, v)
    try:
        found = rf.promotion_findings(items, day)
    finally:
        for k, v in saved.items(): setattr(rf, k, v)
    members = {str(m) for f in found for m in f.members}
    tp = sum(any(m.startswith(p) for m in members) for p in MFTI)
    mipt_other = sum(1 for f in found if f.account_id == mipt for m in f.members if not any(str(m).startswith(p) for p in MFTI))
    print(f"{label:38s} accounts {len(found):3d} posts {len(members):4d} | MFTI {tp}/5, other MFTI {mipt_other}")
    return found
base = run("prod: x5, 2 days, 300/day")
for ex in (10, 15, 20):
    run(f"excess x{ex}", PROMOTION_EXCESS=float(ex))
for d in (3, 4):
    run(f"min days {d}", PROMOTION_MIN_DAYS=d)
for v in (500, 1000):
    run(f"min views/day {v}", PROMOTION_MIN_VIEWS=v)
run("x10, 3 days", PROMOTION_EXCESS=10.0, PROMOTION_MIN_DAYS=3)
run("x15, 3 days", PROMOTION_EXCESS=15.0, PROMOTION_MIN_DAYS=3)
run("x10, 3 days, 500/day", PROMOTION_EXCESS=10.0, PROMOTION_MIN_DAYS=3, PROMOTION_MIN_VIEWS=500)
run("night 0.12", PROMOTION_NIGHT_SHARE=0.12)
run("response 0.3", PROMOTION_RESPONSE=0.3)
pickle.dump(base, open(sys.argv[2], 'wb'))
