"""Frozen MAX daily endpoint analysis; descriptive cohort, no manipulation labels."""
from __future__ import annotations
import argparse, gzip, hashlib, json, platform
import scipy
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln, digamma
from scipy.stats import spearmanr

SEED=20260928
MSK=timezone(timedelta(hours=3))
CASES={'ee221562-2b7b-5cbf-a2f4-95d8ecbe6f31':'МГУ Ломоносова',
       'f532b5cb-8296-547b-b28c-877c3c059f8a':'МФТИ',
       'a30c7106-b853-5da2-879f-18b83b03fb05':'МГУ Куинджи',
       '7427f28c-ebc2-5f0f-acb3-b0bff15bf09a':'ЮЗГУ',
       'c915c6d2-2d2d-565c-85a4-57a733ad78a9':'КГУ Курск'}
DAYS=[f'2026-09-{d:02}' for d in range(14,28)]
BANDS=('1–2','2–4','4–7','7–14')

def dt(s):return datetime.fromisoformat(s)
def good(p):return bool(p and not p['uncertain'] and p['v'] is not None and p['r'] is not None and p['vq']=='exact' and p['rq']=='exact')
def ratio(a,b):return float(a/b) if b else None
def summary(values):
    a=np.asarray(values,dtype=float);a=a[np.isfinite(a)]
    return {'n':len(a),'median':float(np.median(a)),'p10':float(np.quantile(a,.1)),'p90':float(np.quantile(a,.9))} if len(a) else {'n':0}

def load(path):
    raw=gzip.decompress(path.read_bytes());posts=[json.loads(s) for s in raw.splitlines()]
    clocks=defaultdict(list)
    for p in posts:
        p['published']=dt(p['post']['published_at']);p['daily_by_day']={s['day']:s for s in p['daily'] or []}
        clocks[p['post']['primary_account_id']].append(p['published'])
    return posts,clocks,hashlib.sha256(raw).hexdigest()

def intervals(posts,clocks,stale=3,reposts=False):
    rows=[];audit=Counter();opportunities=Counter();account_audit=defaultdict(Counter)
    for p in posts:
        meta=p['post'];aid=meta['primary_account_id']
        if meta['is_repost'] and not reposts:continue
        for day in DAYS:
            boundary=dt(day).replace(tzinfo=MSK)
            planned_age=(boundary-p['published']).total_seconds()/86400
            if not 1<=planned_age<=13:continue
            band=BANDS[np.searchsorted([2,4,7],planned_age,side='right')]
            opportunities[(aid,day,band)]+=1;audit['opportunities']+=1
            before=p['daily_by_day'].get((boundary-timedelta(days=1)).date().isoformat())
            after=p['daily_by_day'].get(day)
            reason=None
            if not before or not after:reason='missing_endpoint'
            elif not good(before) or not good(after):reason='not_exact_or_uncertain'
            else:
                t0,t1=dt(before['observed_at']),dt(after['observed_at'])
                stale0=(boundary-t0).total_seconds()/3600
                stale1=(boundary+timedelta(days=1)-t1).total_seconds()/3600
                duration=(t1-t0).total_seconds()/3600
                if not (0<=stale0<=stale and 0<=stale1<=stale):reason='stale_endpoint'
                elif not 18<=duration<=30:reason='interval_duration'
                elif after['v']<before['v'] or after['r']<before['r']:reason='negative_net_change'
            if reason:
                audit[reason]+=1;account_audit[aid][reason]+=1;continue
            a0=(t0-p['published']).total_seconds()/86400
            a1=(t1-p['published']).total_seconds()/86400
            # A stale boundary must not smuggle a <24h period into the reference.
            if a0<1 or a1>14:
                audit['actual_age_boundary']+=1;account_audit[aid]['actual_age_boundary']+=1;continue
            band=BANDS[np.searchsorted([2,4,7],planned_age,side='right')]
            early=p['early24'];early_valid=good(early) and dt(early['observed_at'])<=t0
            row={'id':meta['id'],'account':aid,'day':day,'band':band,'age':(a0+a1)/2,
                 'planned_start_age':planned_age,'actual_start_age':a0,'hours':duration,
                 'dr':after['r']-before['r'],'dv':after['v']-before['v'],
                 'r0':before['r'],'v0':before['v'],'stale0':stale0,'stale1':stale1,
                 'q24':(early['r']+.5)/(early['v']+1) if early_valid else None,
                 'v24':early['v'] if early_valid else None,'r24':early['r'] if early_valid else None,
                 'new_posts':sum(boundary<=t<boundary+timedelta(days=1) for t in clocks[aid]),
                 'depth':sum(p['published']<t<boundary for t in clocks[aid]),
                 'type':meta['publication_type'],'is_repost':meta['is_repost']}
            rows.append(row);audit['eligible']+=1;account_audit[aid]['eligible']+=1
    return rows,opportunities,dict(audit),{k:dict(v) for k,v in account_audit.items()}

def aggregate(rows):
    eligible=[r for r in rows if r['q24'] is not None]
    exposure=sum(r['dv']*r['q24'] for r in eligible)
    return {'n':len(rows),'positive':sum(r['dr']>0 for r in rows),
            'positive_fraction':ratio(sum(r['dr']>0 for r in rows),len(rows)),
            'dr':sum(r['dr'] for r in rows),'dv':sum(r['dv'] for r in rows),
            'reaction_per_1000_views':ratio(1000*sum(r['dr'] for r in rows),sum(r['dv'] for r in rows)),
            'positive_r_without_v':sum(r['dr']>0 and r['dv']==0 for r in rows),
            'early_adjusted_n':len(eligible),'early_ratio_retention':ratio(sum(r['dr'] for r in eligible),exposure),
            'per_post_dr':summary([r['dr'] for r in rows]),'per_post_dv':summary([r['dv'] for r in rows])}

def descriptive(rows,opp,cohort):
    by=defaultdict(list)
    for r in rows:by[r['account']].append(r)
    out={}
    for account in cohort:
        aid=account['id'];rs=by[aid];late=[r for r in rs if r['actual_start_age']>=4]
        days=[]
        for day in DAYS:
            selected=[r for r in late if r['day']==day]
            possible=sum(n for (a,d,b),n in opp.items() if a==aid and d==day and b in BANDS[2:])
            days.append({'day':day,'opportunities':possible,'coverage':ratio(len(selected),possible),**aggregate(selected)})
        reliable=[d for d in days if d['n']>=10 and d['coverage']>=.5]
        positive=[d['positive_fraction'] for d in reliable]
        run=longest=0
        for d in days:
            run=run+1 if d in reliable and d['positive_fraction']>=.5 else 0;longest=max(run,longest)
        # Same post can occur on several days; this is a descriptive profile.
        per_band={b:aggregate([r for r in rs if r['band']==b]) for b in BANDS}
        pool=aggregate(late)
        pool.update({'days_with_10_posts_and_half_coverage':len(reliable),
                     'days_at_least_half_old_posts_respond':sum(v>=.5 for v in positive),
                     'longest_run_half_respond':longest,'daily_breadth':summary(positive),
                     'share_of_dr_ages_1_to_14':ratio(pool['dr'],sum(r['dr'] for r in rs)),
                     'median_early_q24':summary([r['q24'] for r in late if r['q24'] is not None])})
        day_sums=defaultdict(list)
        for r in rs:day_sums[r['day']].append(r)
        freq=[];tail=[]
        for d in reliable:
            if day_sums[d['day']]:freq.append(day_sums[d['day']][0]['new_posts']);tail.append(d['positive_fraction'])
        corr=spearmanr(freq,tail) if len(set(freq))>1 and len(set(tail))>1 else None
        out[aid]={'name':account['short_name'] or account['title'],'case_name':CASES.get(aid),
                  'observed':aggregate(rs),'late':pool,'bands':per_band,'days':days,
                  'posting_rate_vs_breadth_spearman':float(corr.statistic) if corr else None}
    candidates=[(a,r['late']['positive_fraction']) for a,r in out.items() if r['late']['n']>=50]
    for aid,r in out.items():
        x=r['late']['positive_fraction'];others=[v for a,v in candidates if a!=aid]
        r['cohort_upper_rank_breadth']={'eligible_other_accounts':len(others),'at_least_as_large':sum(v>=x for v in others) if x is not None else None}
    return out

def matrix(rows,train,mode):
    age=np.log([r['age'] for r in rows]);cols=[np.ones(len(rows)),age,age**2]
    offset=np.log1p([r['dv'] for r in rows])
    if mode!='views_age':offset+=np.log([r['q24'] for r in rows])
    if mode in ('context','account_age'):
        cols.extend([np.log1p([r['v24'] for r in rows]),np.log1p([r['new_posts'] for r in rows]),np.log1p([r['depth'] for r in rows]),
                     np.array([dt(r['day']).weekday()>=5 for r in rows],float)])
        for kind in sorted({rows[i]['type'] for i in train})[1:]:cols.append(np.array([r['type']==kind for r in rows],float))
    if mode=='account_age':
        for account in sorted({rows[i]['account'] for i in train}):
            v=np.array([r['account']==account for r in rows],float);cols.extend([v,v*age])
    x=np.column_stack(cols)
    for j in range(1,x.shape[1]):
        if len(np.unique(x[train,j]))>2:
            mu,sd=x[train,j].mean(),x[train,j].std();x[:,j]=(x[:,j]-mu)/max(sd,1e-8)
    return x,offset

def nbfit(x,y,offset):
    penalty=np.ones(x.shape[1])*10;penalty[0]=0
    def fg(params):
        beta=params[:-1];k=np.exp(-params[-1]);eta=offset+x@beta
        mu=np.exp(np.clip(eta,-25,25));alpha=1/k
        ll=gammaln(y+k)-gammaln(k)-gammaln(y+1)+k*(np.log(k)-np.log(k+mu))+y*(np.log(mu)-np.log(k+mu))
        f=-ll.sum()+.5*np.sum(penalty*beta**2)
        g=x.T@((mu-y)/(1+alpha*mu))+penalty*beta
        d=digamma(y+k)-digamma(k)+np.log(k)+1-np.log(k+mu)-(k+y)/(k+mu)
        return f,np.r_[g,k*d.sum()]
    init=np.zeros(x.shape[1]+1);init[0]=np.log((y.sum()+.5)/(np.exp(offset).sum()+.5));init[-1]=0
    fit=minimize(fg,init,jac=True,method='L-BFGS-B',bounds=[(None,None)]*x.shape[1]+[(-9,5)],options={'maxiter':700,'ftol':1e-10})
    return fit.x[:-1],float(np.exp(fit.x[-1])),{'success':bool(fit.success),'message':str(fit.message),'iterations':int(fit.nit)}

def predictive(rows):
    rows=[r for r in rows if r['q24'] is not None]
    train=np.array([i for i,r in enumerate(rows) if r['day']<='2026-09-20']);test=np.array([i for i,r in enumerate(rows) if r['day']>'2026-09-20'])
    y=np.array([r['dr'] for r in rows]);result={'train_intervals':len(train),'test_intervals':len(test),'models':{}}
    if min(len(train),len(test))<100:return result,{}
    predicted={}
    for mode in ('views_age','early_ratio_age','context','account_age','peer_early_ratio_age'):
        fitrows=train if mode!='peer_early_ratio_age' else np.array([i for i in train if rows[i]['account'] not in CASES])
        x,offset=matrix(rows,fitrows,'early_ratio_age' if mode=='peer_early_ratio_age' else mode)
        beta,alpha,status=nbfit(x[fitrows],y[fitrows],offset[fitrows]);mu=np.exp(np.clip(offset+x@beta,-25,25));k=1/alpha
        nll=-(gammaln(y[test]+k)-gammaln(k)-gammaln(y[test]+1)+k*(np.log(k)-np.log(k+mu[test]))+y[test]*(np.log(mu[test])-np.log(k+mu[test])))
        report={'alpha':alpha,'optimizer':status,'train_intervals':len(fitrows),'test_mae':float(np.abs(y[test]-mu[test]).mean()),'test_mean_nll':float(nll.mean()),'accounts':{}}
        for aid in sorted({r['account'] for r in rows}):
            ix=np.array([i for i in test if rows[i]['account']==aid and rows[i]['actual_start_age']>=4])
            if not len(ix):continue
            prob=1-(1+alpha*mu[ix])**(-1/alpha)
            report['accounts'][aid]={'n':len(ix),'observed':int(y[ix].sum()),'expected':float(mu[ix].sum()),
                'observed_expected':ratio(y[ix].sum(),mu[ix].sum()),'active_observed':int((y[ix]>0).sum()),'active_expected':float(prob.sum()),
                'daily':[{'day':d,'n':int(sum(rows[i]['day']==d for i in ix)),
                          'observed':int(sum(y[i] for i in ix if rows[i]['day']==d)),
                          'expected':float(sum(mu[i] for i in ix if rows[i]['day']==d))} for d in DAYS[7:]]}
        result['models'][mode]=report
        predicted[mode]=[(r['account'],r['day'],r['actual_start_age'],float(m),int(v)) for r,m,v in zip(rows,mu,y)]
    return result,predicted

def allocation_audit(predicted):
    """Exploratory conditional occupancy; shared human sessions violate this null."""
    grouped=defaultdict(list)
    for aid,day,age,mu,y in predicted:
        if aid in CASES and day>'2026-09-20' and age>=4:grouped[aid,day].append((mu,y))
    rng=np.random.default_rng(SEED+22);result=[]
    for (aid,day),values in sorted(grouped.items()):
        mu,y=np.array(values).T;total=int(y.sum());active=int((y>0).sum());n=len(y)
        if n<10 or total<10:continue
        weights=mu/mu.sum()
        active_null=(rng.multinomial(total,weights,size=10000)>0).sum(axis=1)
        result.append({'case':CASES[aid],'day':day,'posts':n,'total_reactions':total,'active_posts':active,
            'expected_active_given_total':float(np.sum(1-(1-weights)**total)),
            'simulation_upper_rank':float((1+(active_null>=active).sum())/10001),
            'scope':'independent reaction allocation conditional on total; not a calibrated anomaly or fraud p-value'})
    return {'design':'post-hoc mechanism check after inspecting daily breadth; not preregistered',
            'checks':result,'session_counterexample':{'posts':40,'new_independent_visitors':1,
            'actions':'one engaged newcomer can react once to each of 40 old posts',
            'active_posts':40,'total_reactions':40,'expected_active_independent_uniform':40*(1-(39/40)**40),
            'interpretation':'real within-person dependence can also produce an exceptionally broad and even response'}}

def simulations():
    rng=np.random.default_rng(SEED);days=30;posts_per_day=5;ages=np.arange(4,15)
    result={}
    for name,q in [('low_propensity',.008),('high_propensity',.12)]:
        # Exogenous ordinary visits decay smoothly; independent Poisson count response.
        dv=rng.poisson(100/(1+ages/3),size=(1000,days,posts_per_day,len(ages)))
        reactions=rng.poisson(q*dv)
        breadth=(reactions>0).mean(axis=(2,3));late_daily=reactions.sum(axis=(2,3))
        result[name]={'q':q,'median_daily_positive_fraction':float(np.median(breadth)),
            'fraction_days_half_posts_respond':float((breadth>=.5).mean()),
            'median_daily_late_reactions':float(np.median(late_daily)),
            'age_mean_reactions':list(map(float,reactions.mean(axis=(0,1,2))))}
    return {'scope':'constructed ordinary exposure and count response, not fitted to named universities','cases':result}

def main():
    p=argparse.ArgumentParser();p.add_argument('--panel',type=Path,required=True);p.add_argument('--cohort',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    posts,clocks,sha=load(a.panel);cohort=json.loads(a.cohort.read_text())
    rows,opp,audit,account_audit=intervals(posts,clocks)
    desc=descriptive(rows,opp,cohort);models,predicted=predictive(rows)
    sensitivities={}
    for label,stale,reposts in [('strict_1h',1,False),('loose_6h',6,False),('include_reposts_3h',3,True)]:
        rs,op,au,aa=intervals(posts,clocks,stale,reposts);d=descriptive(rs,op,cohort)
        sensitivities[label]={'audit':au,'cases':{k:d[k] for k in CASES}}
    result={'runtime':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__},'seed':SEED,'panel_sha256':sha,'posts':len(posts),'accounts':len(cohort),'audit':audit,'account_audit':account_audit,
            'description':'retrospective MAX daily endpoints; no fraud/organic labels; existing case selection is not a validation set',
            'cohort':desc,'predictive':models,'sensitivities':sensitivities,'simulations':simulations(),
            'allocation_audit':allocation_audit(predicted.get('peer_early_ratio_age',[]))}
    a.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n')
    print(json.dumps({'accounts':len(cohort),'posts':len(posts),'audit':audit,'models':{k:{f:v[f] for f in ('alpha','optimizer','test_mae','test_mean_nll')} for k,v in models['models'].items()}},ensure_ascii=False))

if __name__=='__main__':main()
