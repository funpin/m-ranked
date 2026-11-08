import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_columns',40); pd.set_option('display.max_rows',200)
pfa=pd.read_pickle('data/pfa_feat.pkl')
subs=pd.read_csv('data/subs.csv'); lastsub=subs.sort_values('d').groupby('aid').sc.last()
fnd=pd.read_csv('data/findings.csv'); fmap=fnd.groupby('account_id').apply(lambda d:' '.join(f"{k}:{s}" for k,s in zip(d.kind,d.status)))
P=pfa[(pfa.published_at>='2026-09-01')&(pfa.v72.notna())].copy()
P['subs']=P.account_id.map(lastsub)
P['v72s']=P.v72/P.subs
def q(x,p): return np.nanpercentile(x,p) if len(x) else np.nan
rows=[]
for acc,d in P.groupby('account_id'):
    if len(d)<15: continue
    rows.append(dict(acc=acc, uname=d.uname.iloc[0], inst=d.inst.iloc[0][:22], subs=d.subs.iloc[0], n=len(d),
        med_v72=d.v72.median(), v72s=d.v72s.median(), cv_v72=d.v72.std()/max(d.v72.mean(),1), med_r72=d.r72.median(), cv_r72=d.r72.std()/max(d.r72.mean(),1),
        erv72=d.erv72.median(), erv_p10=d.erv72.quantile(.1), erv_p90=d.erv72.quantile(.9),
        c72=d.c72.median(), cpv=d.cpv.median(), spv=d.spv.median(),
        early6=d.early6.median(), latestart=(d.early6<0.05).mean(), early1=d.early1.median(),
        late7=d.late7.median(), late14=d.late14.median(),
        top1=d.top1_share.median(), top1_p90=d.top1_share.quantile(.9), steps=(d.steps>=1).mean(),
        lin6=(d.lin_len>=6).mean(), lin_night=((d.lin_len>=6)&(d.lin_night==True)).mean(), lin_mean=d.loc[d.lin_len>=6,'lin_mean'].median(),
        night=d.night_ratio.median(), cliff=d.day_cliff.mean(),
        corr_rv=np.corrcoef(np.log1p(d.v72),np.log1p(d.r72))[0,1] if d.v72.std()>0 and d.r72.std()>0 else np.nan,
        l2=(d.lvl>=2).mean(), l3=(d.lvl==3).mean(), video=d.publication_type.isin(['video','clip']).mean(),
        findings=fmap.get(acc,'')))
A=pd.DataFrame(rows).set_index('uname')
A.to_csv('data/accounts.csv')
num=A.select_dtypes('number')
print('=== cohort percentiles (accounts, n>=15 posts since 01.09)')
print(num.quantile([.1,.25,.5,.75,.9]).T.round(3))
print('\n=== accounts ranked by sum reactions (top 45)')
cols=['inst','subs','n','med_v72','v72s','cv_v72','med_r72','erv72','c72','early6','latestart','late7','top1','steps','lin6','lin_night','night','cliff','corr_rv','l2','l3','video','findings']
S=P.groupby('uname').r72.sum().sort_values(ascending=False)
print(A.loc[[u for u in S.index if u in A.index][:45],cols].round(3).to_string())
print('\n=== z-score outliers per metric (robust, MAD), top 6 accounts each')
for m in ['v72s','erv72','cpv','spv','early6','latestart','late7','top1','steps','lin6','lin_night','night','cliff','corr_rv','cv_r72','cv_v72']:
    x=A[m].astype(float); med=x.median(); mad=(x-med).abs().median() or 1e-9; z=(x-med)/(1.4826*mad)
    top=z.abs().sort_values(ascending=False).head(6)
    print(f"{m:10s} med={med:.3f}  " + ", ".join(f"{u}={x[u]:.3f}(z{z[u]:+.1f})" for u in top.index))
