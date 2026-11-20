from agg import *
import calendar
PLATFORMS = ('telegram', 'vk', 'max', 'rutube')
# КамГУ: 656 в файле контингента ошибочен, верное 1 667 (PR #114).
for k, v in list(students.items()):
    if v == 656: students[k] = 1667
def active_days(m):
    days = defaultdict(set)
    for r in posts:
        t = (r['upl'] or r['pub']) if r['platform'] == 'rutube' else r['pub']
        if month(t) == m: days[(r['institution_id'], r['platform'])].add(t.astimezone(MSK).date())
    return days
def metrics(m, clean=True, floor=0, stat='mean'):
    A = aggregate(m); D = active_days(m); out = {}
    for (i, p), d in A.items():
        if i not in inst: continue
        cov = d['cov']; ndays = d['days']
        V = d['views'] - (d['packv'] if clean else 0); I = d['inter'] - (d['packr'] if clean else 0)
        st_ = students.get(i)
        reach = V / d['vposts'] / max(st_, floor) if d['vposts'] and st_ else None
        out[(i, p)] = dict(cov=cov, active=min(ndays, len(D[(i, p)]) / max(cov * ndays, 1e-9) * ndays) if cov > 0 else None,
                           posts=d['posts'], upl=d['upl'], reach=reach, erv=(I / V if V > 0 else None),
                           raw_erv=(d['inter'] / d['views'] if d['views'] else None),
                           packr=d['packr'] / d['inter'] if d['inter'] else 0, packv=d['packv'] / d['views'] if d['views'] else 0)
    return out
def pct(xs, p):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]
def logsub(x, lo, hi):
    if x is None or x <= 0: return 0.0
    return max(0.0, min(100.0, 100 * math.log(x / lo) / math.log(hi / lo)))
def linsub(x, lo, hi):
    if x is None: return 0.0
    return max(0.0, min(100.0, 100 * (x - lo) / (hi - lo)))
def anchors(Ms, lo=10, hi=90):
    A = {}
    for p in PLATFORMS:
        full = [v for M in Ms for (i, q), v in M.items() if q == p and v['cov'] >= 0.9 and v['posts'] > 0]
        A[p] = dict(reach=(pct([v['reach'] for v in full if v['reach']], lo), pct([v['reach'] for v in full if v['reach']], hi)),
                    erv=(pct([v['erv'] for v in full if v['erv']], lo), pct([v['erv'] for v in full if v['erv']], hi)))
    return A
MIN_POSTS = {'telegram': 8, 'vk': 8, 'max': 8, 'rutube': 4}
ACTIVE_HIGH = {'telegram': 24, 'vk': 24, 'max': 24, 'rutube': 8}  # days of 30
def score(M, A, m, smart=None, min_cov=14/31):
    ndays = calendar.monthrange(*map(int, m.split('-')))[1]
    res = {}
    for i in inst:
        plat = {}
        for p in PLATFORMS:
            v = M.get((i, p))
            if v is None: plat[p] = dict(score=0.0, source='no_account'); continue
            if v['cov'] < min_cov: plat[p] = dict(score=None, source='no_data'); continue
            act = linsub(v['active'], 0, ACTIVE_HIGH[p] * ndays / 30)
            reach = logsub(v['reach'], *A[p]['reach'])
            erv_v = v['erv']
            if smart and (i, p) in smart and erv_v is not None:
                erv_v = min(erv_v, smart[(i, p)])
            eng = logsub(erv_v, *A[p]['erv'])
            if v['posts'] == 0: act = reach = eng = 0.0
            k = min(1.0, v['posts'] / MIN_POSTS[p]); reach *= k; eng *= k
            plat[p] = dict(score=(act + reach + eng) / 3, act=act, reach=reach, eng=eng, source='partial' if v['cov'] < 0.9 else 'formula', m=v)
        have = [p for p in PLATFORMS if plat[p]['score'] is not None]
        total = sum(plat[p]['score'] for p in have) / len(have) if len(have) >= 3 else None
        res[i] = dict(total=total, plat=plat, partial=len(have) < 4 or any(plat[p]['source'] == 'partial' for p in have))
    return res
def ranks(scores):
    order = sorted([k for k, v in scores.items() if v is not None], key=lambda k: -scores[k])
    return {k: n for n, k in enumerate(order, 1)}
def spearman(a, b):
    ks = [k for k in a if k in b]; n = len(ks)
    ra = ranks({k: a[k] for k in ks}); rb = ranks({k: b[k] for k in ks})
    return 1 - 6 * sum((ra[k] - rb[k]) ** 2 for k in ks) / (n * (n * n - 1)), n
PERIOD = {'2026-09': 'Сентябрь 2026', '2026-10': 'Октябрь 2026'}
def official_social(m):
    o = official[PERIOD[m]]
    return {i: float(o[inst[i]['code']]['social_score']) for i in inst if inst[i]['code'] in o and o[inst[i]['code']]['social_score'] not in ('', None)}
def official_place(m):
    o = official[PERIOD[m]]
    pool = {c: float(r['social_score']) for c, r in o.items() if r['social_score']}
    order = sorted(pool, key=lambda c: -pool[c]); place = {c: n for n, c in enumerate(order, 1)}
    return {i: place.get(inst[i]['code']) for i in inst if inst[i]['code']}
nm = lambda i: (inst[i]['short_name'] or inst[i]['canonical_name'])[:30]
