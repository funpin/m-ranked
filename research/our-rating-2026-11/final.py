from formula import *
import csv as _csv, json as _json
# account late-excess share per (institution, platform, month): status 2 on >= half of profile days
def tail_shares():
    by = defaultdict(list)
    for r in _csv.DictReader(open('tailhist.csv')):
        by[(r['account_id'], r['computed_for'][:7])].append(r)
    out = {}
    for (a, m), rs in by.items():
        if sum(r['status'] == '2' for r in rs) * 2 < len(rs) or len(rs) < 10: continue
        sh = []
        for r in rs:
            lr, lv, er, ev, med = (float(r[k] or 0) for k in ('lr', 'lv', 'er', 'ev', 'cmed'))
            if er > 0 and ev > 0: sh.append(max(0.0, lr - lv * er / ev * med) / (lr + er))
        if sh: out[(accounts[a]['institution_id'], accounts[a]['platform'], m)] = sum(sh) / len(sh)
    return out
TAIL = tail_shares()
# "smart": regular_reactions status 2 + long tail (status 2 majority) -> ERV capped at platform median
REG = {(r['institution_id'], r['platform']) for r in _csv.DictReader(open('findings.csv')) if r['kind'] == 'regular_reactions' and r['status'] == '2'}
def metrics2(m, clean=True, floor=2000, account=True):
    M = metrics(m, clean=clean, floor=floor)
    if not (clean and account): return M, set()
    A = aggregate(m); smart = set()
    for (i, p), v in M.items():
        sh = TAIL.get((i, p, m))
        if sh is None: continue
        d = A[(i, p)]
        V = d['views'] - d['packv']; rem = max(d['packr'], sh * d['inter'])
        v['erv'] = (d['inter'] - rem) / V if V > 0 else None; v['tail_share'] = sh
        if (i, p) in REG and m == '2026-10': smart.add((i, p))
    return M, smart
def run(m, A, clean=True, account=True, floor=2000):
    M, smart = metrics2(m, clean, floor, account)
    cap = {}
    for p in PLATFORMS:
        med = pct([v['erv'] for (i, q), v in M.items() if q == p and v['cov'] >= 0.9 and v['erv']], 50)
        for (i, q) in smart:
            if q == p: cap[(i, q)] = med
    return score(M, A, m, smart=cap), smart
if __name__ == '__main__':
    base = {m: metrics(m) for m in ('2026-09', '2026-10')}
    A = anchors(base.values())
    print('TAIL Oct:', sorted((nm(i), p, round(s, 2)) for (i, p, m), s in TAIL.items() if m == '2026-10'))
    out = {}
    for m in ('2026-09', '2026-10'):
        Rc, smart = run(m, A); Rr, _ = run(m, A, clean=False)
        print(m, 'smart caps:', [(nm(i), p) for i, p in smart])
        tc = {i: v['total'] for i, v in Rc.items() if v['total'] is not None}; tr = {i: v['total'] for i, v in Rr.items() if v['total'] is not None}
        rc, rr = ranks(tc), ranks(tr)
        off = official_social(m); place = official_place(m)
        pool_off = ranks({i: off[i] for i in tc if i in off})
        rows = []
        for i in tc:
            rows.append(dict(id=i, name=nm(i), full=inst[i]['canonical_name'], our=rc[i], raw=rr[i], score=round(tc[i], 1), raw_score=round(tr[i], 1),
                             mr_pool=pool_off.get(i), mr_place=place.get(i), mr_score=off.get(i), partial=Rc[i]['partial'],
                             plat={p: {k: (round(x, 1) if isinstance(x, float) else x) for k, x in Rc[i]['plat'][p].items() if k != 'm'} for p in PLATFORMS},
                             metr={p: {k: (round(x, 5) if isinstance(x, float) else x) for k, x in (Rc[i]['plat'][p].get('m') or {}).items()} for p in PLATFORMS}))
        out[m] = sorted(rows, key=lambda r: r['our'])
        print(m, 'n', len(tc), 'rho vs M-Rating pool %.3f' % spearman(tc, off)[0], ' raw-vs-clean rho %.3f' % spearman(tc, tr)[0])
    _json.dump(out, open('final.json', 'w'), ensure_ascii=False, indent=1)
    a = {r['id']: r['score'] for r in out['2026-09']}; b = {r['id']: r['score'] for r in out['2026-10']}
    print('stability Sep->Oct %.3f n=%d' % spearman(a, b))
