import json, sys, bisect
from datetime import datetime, timezone, timedelta
d=json.load(open(sys.argv[1]))[sys.argv[2]]; pts=sorted(d['points'],key=lambda p:p['observedAt'])
lo,hi,step=float(sys.argv[3]),float(sys.argv[4]),float(sys.argv[5]) if len(sys.argv)>5 else 1
msk=timezone(timedelta(hours=3)); pub=datetime.fromisoformat(d['meta']['publishedAt'])
ages=[p['ageHours'] for p in pts]
def val(a,m):
    i=bisect.bisect_right(ages,a)-1
    while i>=0 and (pts[i][m] or {}).get('value') is None: i-=1
    return (pts[i][m] or {}).get('value') if i>=0 else 0
def npts(a,b): return bisect.bisect_right(ages,b)-bisect.bisect_right(ages,a)
prev=None; h=lo
while h<=hi:
    v,r,c,s=[val(h,m) or 0 for m in ('views','reactions','comments','shares')]
    t=(pub+timedelta(hours=h)).astimezone(msk).strftime('%d.%m %H:%M')
    if prev: print(f"{h:6.1f}h {t} V={v:6d} +{v-prev[0]:5d}  R={r:4d} +{r-prev[1]:4d}  C={c} S={s} pts={npts(h-step,h)}")
    prev=(v,r); h+=step
