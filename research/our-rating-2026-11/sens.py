import final as F
from formula import *
m = '2026-10'
base = {mm: metrics(mm) for mm in ('2026-09', '2026-10')}
A = anchors(base.values())
def tot(R): return {i: v['total'] for i, v in R.items() if v['total'] is not None}
ref = tot(F.run(m, A)[0]); rref = ranks(ref)
off = official_social(m)
def cmp(name, R):
    t = tot(R); r = ranks(t)
    top = len({i for i in t if r[i] <= 20} & {i for i in ref if rref[i] <= 20})
    moves = sorted(((abs(r[i]-rref[i]), nm(i), rref[i], r[i]) for i in t if i in rref), reverse=True)[:4]
    print(f'{name:34s} rho vs ref {spearman(t, ref)[0]:.3f} | vs M {spearman(t, off)[0]:.3f} | top20 overlap {top}/20 | {[(n, a, b) for _, n, a, b in moves]}')
for floor in (0, 1000, 3000, 5000):
    cmp(f'floor {floor}', F.run(m, A, floor=floor)[0])
for lo, hi in ((5, 95), (25, 75), (0, 100)):
    cmp(f'anchors p{lo}-p{hi}', F.run(m, anchors(base.values(), lo, hi))[0])
# power 0.7 scale from 0 to p90 instead of log
import formula
orig = formula.logsub
formula.logsub = lambda x, lo, hi: 0.0 if not x or x <= 0 else max(0, min(100, 100 * (x / hi) ** 0.7))
cmp('power 0.7, 0..p90', F.run(m, A)[0])
formula.logsub = orig
# 3 platforms weighting: TG excluded when dead (no posts in month) -> renormalize
R = F.run(m, A)[0]
alt = {}
for i, v in R.items():
    ps = [p for p in PLATFORMS if v['plat'][p]['score'] is not None and not (p == 'telegram' and v['plat'][p]['score'] == 0)]
    alt[i] = dict(total=sum(v['plat'][p]['score'] for p in ps) / len(ps) if len(ps) >= 3 else None)
cmp('dead TG excluded (renormalized)', alt)
# activity by posts count (log 4->60) instead of active days
