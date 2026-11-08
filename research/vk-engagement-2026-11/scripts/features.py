import pandas as pd, numpy as np, sys, json
D='data/'
pfa=pd.read_csv(D+'pfa.csv', parse_dates=['published_at'])
pha=pd.read_csv(D+'pha.csv')
subs=pd.read_csv(D+'subs.csv')
print('posts',len(pfa),'pha rows',len(pha))
pfa=pfa[pfa.v72.notna()].copy()
pfa['erv72']=pfa.r72/pfa.v72.clip(lower=1); pfa['erv24']=pfa.r24/pfa.v24.clip(lower=1)
pfa['late7']=(pfa.v168-pfa.v72)/pfa.v168.clip(lower=1)
pfa['late14']=(pfa.v336-pfa.v72)/pfa.v336.clip(lower=1)
pfa['early6']=pfa.v6/pfa.v72.clip(lower=1); pfa['early1']=pfa.v1/pfa.v72.clip(lower=1)
pfa['cpv']=pfa.c72/pfa.v72.clip(lower=1)*1000; pfa['spv']=pfa.s72/pfa.v72.clip(lower=1)*1000
pfa['rpc']=pfa.r72/pfa.c72.clip(lower=1)
# per-post hourly features
g=pha[(pha.ah<72)].sort_values(['pid','ah'])
feat={}
v72=pfa.set_index('id').v72.to_dict()
for pid,grp in g.groupby('pid', sort=False):
    V=v72.get(pid)
    if not V or V<200: continue
    ah=grp.ah.values; dv=grp.dv.values.astype(float); dr=grp.dr.values.astype(float); gap=grp.gap_s.values; mh=grp.msk_h.values
    known=(gap<=4200)
    f={}
    i=np.argmax(dv); f['top1_share']=dv[i]/V; f['top1_age']=int(ah[i]); f['top1_msk']=int(mh[i])
    f['top1_rpkv']= dr[i]/max(dv[i],1)*1000
    f['top3_share']=np.sort(dv)[-3:].sum()/V
    late=(ah>=2)
    f['steps']=int(((dv>=np.maximum(200,0.15*V))&late).sum())
    # linear run on known hours ages 1..71 with dv>=100
    best=(0,0,0,False); run=[]; 
    def flush(run):
        nonlocal_best=None
    runs=[]
    cur=[]
    for k in range(len(ah)):
        if ah[k]<1 or not known[k] or dv[k]<100: 
            if cur: runs.append(cur); cur=[]
            continue
        if cur and (ah[k]!=cur[-1][0]+1):
            runs.append(cur); cur=[]
        cur.append((ah[k],dv[k],mh[k]))
    if cur: runs.append(cur)
    # split runs by ±25% around running mean
    bestlen=0; bestmean=0; bestnight=False; beststart=-1
    for rr in runs:
        vals=[x[1] for x in rr]
        start=0
        while start<len(rr):
            end=start
            while end+1<len(rr):
                seg=vals[start:end+2]; m=np.mean(seg)
                if max(abs(x-m) for x in seg)<=0.25*m: end+=1
                else: break
            L=end-start+1
            if L>bestlen:
                bestlen=L; bestmean=float(np.mean(vals[start:end+1])); bestnight=any(1<=x[2]<=5 for x in rr[start:end+1]); beststart=int(rr[start][0])
            start=end+1
    f['lin_len']=bestlen; f['lin_mean']=bestmean; f['lin_night']=bestnight; f['lin_start']=beststart
    # night ratio ages 6..71
    sel=(ah>=6)&known
    nightv=dv[sel&((mh>=1)&(mh<=5))].sum(); dayv=dv[sel&((mh>=10)&(mh<=22))].sum()
    f['night_ratio']= nightv/dayv if dayv>0 else np.nan
    f['night_hours']=int((sel&((mh>=1)&(mh<=5))).sum()); 
    # daytime cliff: prev 3h mean >=300 and next 3h mean <= 1/5, hour msk 9..21
    cliff=False
    d={int(a):x for a,x in zip(ah,dv)}
    for a in range(4,70):
        if all(k in d for k in range(a-3,a+3)):
            prev=np.mean([d[k] for k in range(a-3,a)]); nxt=np.mean([d[k] for k in range(a,a+3)])
            if prev>=300 and nxt<=prev/5 and 9<=mh[list(ah).index(a)]<=21: cliff=True; break
    f['day_cliff']=cliff
    feat[pid]=f
F=pd.DataFrame.from_dict(feat, orient='index')
pfa=pfa.join(F, on='id')
pfa.to_pickle('data/pfa_feat.pkl')
print('features done', len(F))
