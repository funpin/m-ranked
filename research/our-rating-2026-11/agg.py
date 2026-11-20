from load import *
def pack_r(r):
    """Reaction pack on a post: L3, one largest episode, capped by interactions."""
    i = (r['r'] or 0)+(r['c'] or 0)+(r['s'] or 0)
    if r['lvl'] < 3 or r['r_ep'] is None: return 0.0
    return min(max(r['r_ep'], 0.0), i)
def pack_v(r):
    if r['v'] is None: return 0.0
    if r['dv'] is not None: return min(r['dv'], r['v'])
    if r['lvl'] < 3 or r['v_ep'] is None: return 0.0
    return min(max(r['v_ep'], 0.0), r['v'])
def aggregate(m):
    out = {}
    for a in accounts.values():
        key = (a['institution_id'], a['platform'])
        d = out.setdefault(key, dict(posts=0, vposts=0, views=0, inter=0, react=0, comm=0, shares=0, upl=0,
                                     packv=0, packr=0, l3=0, l3inter=0, cov=1.0, days=0, accounts=[]))
        c, days = cover_days(a, m)
        d['cov'] = min(d['cov'], c/days); d['days'] = days; d['accounts'].append(a['id'])
    for r in posts:
        d = out[(r['institution_id'], r['platform'])]
        if r['platform']=='rutube' and month(r['upl'] or r['pub'])==m: d['upl'] += 1
        if month(r['pub']) != m: continue
        d['posts'] += 1
        if r['v'] is None: continue
        i = (r['r'] or 0)+(r['c'] or 0)+(r['s'] or 0)
        d['vposts'] += 1; d['views'] += r['v']; d['inter'] += i
        d['react'] += r['r'] or 0; d['comm'] += r['c'] or 0; d['shares'] += r['s'] or 0
        d['packv'] += pack_v(r); d['packr'] += pack_r(r)
        if r['lvl']==3: d['l3'] += 1; d['l3inter'] += i
    return out
