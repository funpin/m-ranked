"""Frozen-protocol H26-H29. Local archive only, never production scores.

Telegram calculations are diagnostics of displayed values, not exact counts:
historical display precision is absent. Empirical ranks are not fraud odds.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import numpy as np
import scipy

SEED = 20264228
spec = importlib.util.spec_from_file_location('observable_validation', Path(__file__).with_name('observable_validation.py'))
OLD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(OLD)


def ranks(score, calibration):
    score, calibration = np.asarray(score), np.asarray(calibration)
    return (1 + (calibration[:, None] >= score).sum(axis=0)) / (len(calibration) + 1)


def rate(flags, accounts):
    flags=np.asarray(flags)
    result=OLD.observed_rate(flags, np.asarray(accounts), np.random.default_rng(SEED))
    if len(flags) and np.all(flags==flags[0]):
        # A degenerate empirical bootstrap is not an upper risk bound.
        result['account_bootstrap']['ci95']=None
        result['account_bootstrap']['status']='degenerate_observed_outcomes_not_a_risk_bound'
    return result


def fold(rows):
    ix = {s: np.array([i for i,p in enumerate(rows) if OLD.split(p)==s],int) for s in ('fit','cal','test')}
    for a,b in (('fit','cal'),('cal','test')):
        if len(ix[a]) and len(ix[b]):
            assert max(rows[i]['published']+timedelta(hours=72) for i in ix[a]) < min(rows[i]['published'] for i in ix[b])
    return ix


def select_rows(posts, plat, reactions=False):
    return [p for p in posts if p['platform']==plat and OLD.split(p)!='embargo'
            and all(OLD.valid(p['endpoints'][h],m,plat!='telegram') for h in (24,72) for m in (('v','r') if reactions else ('v',)))
            and all(p['endpoints'][72][m]>=p['endpoints'][24][m] for m in (('v','r') if reactions else ('v',)))]


def counts(rows):
    return np.array([[p['endpoints'][24][m] for m in ('v','r')] for p in rows],float), np.array([[p['endpoints'][72][m] for m in ('v','r')] for p in rows],float)


def linear_fit(x, y):
    mean, sd = x.mean(), max(x.std(),1e-8)
    design = np.column_stack([np.ones(len(x)),(x-mean)/sd])
    beta = np.linalg.solve(design.T@design+np.diag([0.,10.]), design.T@y)
    return np.array([beta[0]-beta[1]*mean/sd,beta[1]/sd])


def transfer(posts):
    rows={p:select_rows(posts,p) for p in OLD.PLATFORMS}
    folds={p:fold(r) for p,r in rows.items()}
    x={p:np.log1p([r['endpoints'][24]['v'] for r in rr]) for p,rr in rows.items()}
    y={p:np.log1p([r['endpoints'][72]['v'] for r in rr]) for p,rr in rows.items()}
    beta={p:linear_fit(x[p][folds[p]['fit']],y[p][folds[p]['fit']]) for p in rows if len(folds[p]['fit'])>=3}
    out={}
    pooled=linear_fit(np.concatenate([x[p][folds[p]['fit']] for p in ('max','telegram')]), np.concatenate([y[p][folds[p]['fit']] for p in ('max','telegram')]))
    for plat,rr in rows.items():
        ix=folds[plat]; fit,cal,test=(ix[s] for s in ('fit','cal','test'))
        r={'counts':{s:len(v) for s,v in ix.items()},'strict_exact_usable':plat!='telegram',
           'minimum_rank':1/(len(cal)+1),'models':{}}
        out[plat]=r
        if plat not in beta or not len(cal) or not len(test):continue
        models={'own_platform':beta[plat]}
        if plat in ('max','telegram'):
            other='telegram' if plat=='max' else 'max'
            adapted=beta[other].copy()
            adapted[0]+=np.mean(y[plat][fit]-adapted[0]-adapted[1]*x[plat][fit])
            models.update(source_only=beta[other],source_slope_target_level=adapted,messenger_pool=pooled)
        errors={}
        groups=np.array([rr[i]['primary_account_id'] for i in test])
        for name,b in models.items():
            e=y[plat]-(b[0]+b[1]*x[plat]); errors[name]=np.abs(e[test])
            ranks_own=ranks(e[test],e[cal])
            item={'intercept':float(b[0]),'slope':float(b[1]),'mae_log1p':float(errors[name].mean()),
                  'median_log_growth_24_72':float(np.median(y[plat][test]-x[plat][test])),
                  'target_calibrated_rank_le_05':rate(ranks_own<=.05,groups),
                  'paired_mae_delta_vs_own':OLD.cluster_delta(errors[name]-errors['own_platform'],groups,np.random.default_rng(SEED+1))}
            if name=='source_only':
                c=folds[other]['cal'];foreign=y[other][c]-(b[0]+b[1]*x[other][c])
                item['foreign_calibration_rank_le_05']=rate(ranks(e[test],foreign)<=.05,groups)
            r['models'][name]=item
    return out


def forward_endpoint(points, hour):
    candidates=[p for p in points if hour*3600<=p['age_seconds']<=(hour+3)*3600]
    return min(candidates,key=lambda p:p['age_seconds']) if candidates else None


def wave(points):
    ep=[forward_endpoint(points,h) for h in (72,96,120)]
    if any(p is None for p in ep):return 'missing_window',None
    if not all(OLD.valid(p,'v',True) for p in ep):return 'nonexact_or_uncertain',None
    middle=[p for p in points if ep[0]['age_seconds']<=p['age_seconds']<=ep[2]['age_seconds']]
    if not all(OLD.valid(p,'v',True) for p in middle):return 'internal_unknown_or_uncertain',None
    if any(b['v']<a['v'] for a,b in zip(middle,middle[1:])):return 'negative_correction',None
    dt=np.diff([p['age_seconds']/3600 for p in ep]);dv=np.diff([p['v'] for p in ep]);speed=dv/dt
    flag=bool(speed[1]>2*speed[0] and dv[1]>=max(10,.1*ep[1]['v']))
    metrics={}
    for m in ('r','c','s'):
        usable=(all(OLD.valid(p,'r',True) for p in middle) if m=='r' else all(p[m] is not None for p in middle))
        if usable and not any(b[m]<a[m] for a,b in zip(middle,middle[1:])):
            metrics[m]=int(ep[2][m]-ep[1][m])
    return 'eligible',{'wave':flag,'age_start':ep[1]['age_seconds']/3600,'dv_late':int(dv[1]),'speed_ratio':float(speed[1]/speed[0]) if speed[0] else None,'late_fraction':float(dv[1]/max(1,ep[1]['v'])),'metric_deltas':metrics}


def waves(posts):
    out={}
    for plat in OLD.PLATFORMS:
        ps=[p for p in posts if p['platform']==plat]
        reasons=Counter(); good=[]; ids=[];examples=[]
        for p in ps:
            reason,result=wave(p['points']);reasons[reason]+=1
            if result:
                good.append(result);ids.append(p['primary_account_id'])
                if result['wave']:examples.append({'publication_id':p['id'],'account_id':p['primary_account_id'],'published_at':p['published_at'],**result})
        flags=np.array([r['wave'] for r in good]);diag={}
        for m in ('r','c','s'):
            selected=[r['metric_deltas'][m] for r in good if r['wave'] and m in r['metric_deltas']]
            diag[m]={'observed_wave_posts':len(selected),'positive':sum(v>0 for v in selected)}
        out[plat]={'catalog_posts':len(ps),'accounts':len({p['primary_account_id'] for p in ps}),
                   'exclusions':dict(reasons),'waves':rate(flags,ids),'late_fraction':OLD.describe([r['late_fraction'] for r in good]),
                   'co_growth':diag,'all_wave_examples':examples}
    return out


class FourReferences:
    """Unconditional history plus conditional development; no clean-input claim."""
    def __init__(self,rows,fit,early,late):
        self.accounts=sorted({rows[i]['primary_account_id'] for i in fit})
        self.beta=[];self.center=[];self.sd=[];self.scales=[]
        for k in range(4):
            metric=k%2;conditional=k<2
            col=np.log1p(early[:,metric]);mu=col[fit].mean();sd=max(col[fit].std(),1e-8)
            self.center.append(mu);self.sd.append(sd)
            xx=self.design(rows,early,k)
            yy=np.log1p(late[:,metric]);penalty=10*np.eye(xx.shape[1]);penalty[0,0]=0
            b=np.linalg.solve(xx[fit].T@xx[fit]+penalty,xx[fit].T@yy[fit]);self.beta.append(b)
            e=yy[fit]-xx[fit]@b
            self.scales.append(max(float(np.quantile(e,.75)-np.quantile(e,.25)),.05))

    def design(self,rows,early,k):
        cols=[np.ones(len(rows))]
        if k<2:cols.append((np.log1p(early[:,k%2])-self.center[k])/self.sd[k])
        cols.extend(np.array([p['primary_account_id']==a for p in rows],float) for a in self.accounts)
        return np.column_stack(cols)

    def residuals(self,rows,early,late):
        return np.column_stack([(np.log1p(late[:,k%2])-self.design(rows,early,k)@self.beta[k])/self.scales[k] for k in range(4)])


def blocks(rows,indices,distinct_days=False):
    out=[];groups=[]
    for a in sorted({rows[i]['primary_account_id'] for i in indices}):
        ii=sorted([i for i in indices if rows[i]['primary_account_id']==a],key=lambda i:(rows[i]['published_at'],rows[i]['id']))
        if distinct_days:
            by_day={}
            for i in ii:by_day.setdefault((rows[i]['published']+timedelta(hours=3)).date(),i)
            ii=list(by_day.values())
        if len(ii)>=3:out.append(ii[:3]);groups.append(a)
    return np.array(out,dtype=int).reshape(-1,3),np.array(groups)


def block_scores(residuals,indices):
    z=residuals[indices]
    return {'mean_components':z.mean(axis=1).max(axis=1),'maximum_post':z.max(axis=(1,2))}


def inject(early,late,indices,fraction,kind):
    a,b=early.copy(),late.copy()
    b[indices]+=np.rint(b[indices]*fraction)
    if kind=='early':a[indices]+=np.rint(a[indices]*fraction)
    elif kind!='late':raise ValueError(kind)
    return a,b


def repeated(rows,distinct_days=False):
    ix=fold(rows);early,late=counts(rows);model=FourReferences(rows,ix['fit'],early,late)
    z=model.residuals(rows,early,late)
    bc,gc=blocks(rows,ix['cal'],distinct_days);bt,gt=blocks(rows,ix['test'],distinct_days)
    cs,ts=block_scores(z,bc),block_scores(z,bt)
    base={name:ranks(ts[name],cs[name]) for name in ts}
    clear=np.logical_and.reduce([v>.05 for v in base.values()])
    out={'posts':{s:len(ii) for s,ii in ix.items()},'fit_scales':model.scales,'cal_blocks':len(bc),'test_blocks':len(bt),
         'minimum_block_rank':1/(len(bc)+1),'status':'rank_resolution_insufficient' if len(bc)<19 else 'exploratory_unlabeled',
         'common_clear_blocks':int(clear.sum()),'baseline':{name:rate(v<=.05,gt) for name,v in base.items()},'injections':{}}
    out['block_coverage']={s:{
        'span_hours':OLD.describe([(rows[b[-1]]['published']-rows[b[0]]['published']).total_seconds()/3600 for b in bs]),
        'distinct_moscow_publication_days':dict(Counter(str(len({(rows[i]['published']+timedelta(hours=3)).date() for i in b})) for b in bs))}
        for s,bs in (('cal',bc),('test',bt))}
    if len(bc)<19:
        out['baseline']={name:{'status':'abstain_insufficient_calibration_resolution','test_blocks':len(bt)} for name in ts}
        out['common_clear_blocks']=None
        return out
    for kind in ('late','early'):
        for amount in (.1,.3,1.):
            for breadth in ('all_three','one_post'):
                affected=bt.ravel() if breadth=='all_three' else bt[:,0]
                a,b=inject(early,late,affected,amount,kind)
                changed=block_scores(model.residuals(rows,a,b),bt)
                out['injections'][f'{kind}:{amount}:{breadth}']={name:{'all':rate(ranks(changed[name],cs[name])<=.05,gt),
                    'new_on_common_clear':rate((ranks(changed[name],cs[name])<=.05)[clear],gt[clear])} for name in cs}
    return out


def contamination(rows):
    ix=fold(rows);early,late=counts(rows);groups=np.array([p['primary_account_id'] for p in rows])
    ordered=sorted(set(groups),key=lambda a:hashlib.sha256(a.encode()).hexdigest())
    chosen=set(ordered[:len(ordered)//3]);target=np.array([a in chosen for a in groups]);test=ix['test'];cal=ix['cal']
    original=FourReferences(rows,ix['fit'],early,late);z=original.residuals(rows,early,late).max(axis=1)
    clear=ranks(z[test],z[cal])>.05
    out={'target_accounts':len(chosen),'test_target_posts':int(target[test].sum()),'clear_target_posts':int((clear&target[test]).sum()),'scenarios':{}}
    for amount in (.1,.3,1.):
        for phase in ('none','fit','cal','fit_and_cal'):
            changed=[]
            if phase in ('fit','fit_and_cal'):changed.extend(i for i in ix['fit'] if target[i])
            if phase in ('cal','fit_and_cal'):changed.extend(i for i in cal if target[i])
            a,b=inject(early,late,np.array(changed,int),amount,'early')
            model=FourReferences(rows,ix['fit'],a,b)
            cc=model.residuals(rows,a,b).max(axis=1)[cal]
            aa,bb=inject(a,b,test[target[test]],amount,'early')
            score=model.residuals(rows,aa,bb).max(axis=1)[test]
            flags=ranks(score,cc)<=.05;keep=clear&target[test]
            out['scenarios'][f'{amount}:{phase}']={'new_on_original_clear_target':rate(flags[keep],groups[test][keep]),
                'all_target':rate(flags[target[test]],groups[test][target[test]]),
                'unchanged_other_accounts':rate(flags[~target[test]],groups[test][~target[test]]),
                'cal_score_q95':float(np.quantile(cc,.95)),'fit_scales':model.scales}
    return out


def stability(rows):
    """H30: post-hoc diagnostic specified before its own outcomes; no tuning."""
    ix=fold(rows);early,late=counts(rows);model=FourReferences(rows,ix['fit'],early,late)
    z=model.residuals(rows,early,late)
    bc,gc=blocks(rows,ix['cal']);bt,gt=blocks(rows,ix['test'])
    cs=block_scores(z,bc)['mean_components'];ts=block_scores(z,bt)['mean_components']
    base=ranks(ts,cs)>.05
    modified={}
    for kind in ('late','early'):
        for f in (.1,.3,1.):
            a,b=inject(early,late,bt.ravel(),f,kind)
            modified[f'{kind}:{f}']=block_scores(model.residuals(rows,a,b),bt)['mean_components']
    maxima=z[bc].mean(axis=1)
    out={'cal_blocks':len(bc),'test_blocks':len(bt),'clear_mean_blocks':int(base.sum()),
         'top_calibration_scores':sorted(cs.tolist(),reverse=True)[:3],
         'largest_score_component':int(np.argmax(maxima[np.argmax(cs)])),
         'leave_one_calibration_account_out':[]}
    for i,account in enumerate(gc):
        cc=np.delete(cs,i)
        out['leave_one_calibration_account_out'].append({'removed_account_id':account,
            'cal_blocks':len(cc),'base_flags':int((ranks(ts,cc)<=.05).sum()),
            'injected_new':{name:int((ranks(s,cc)[base]<=.05).sum()) for name,s in modified.items()}})
    out['block_size_sensitivity']={}
    for size in (2,5):
        def choose(indices):
            b=[]
            for account in sorted({rows[i]['primary_account_id'] for i in indices}):
                ii=sorted([i for i in indices if rows[i]['primary_account_id']==account],key=lambda i:(rows[i]['published_at'],rows[i]['id']))
                if len(ii)>=size:b.append(ii[:size])
            return np.array(b,int).reshape(-1,size)
        cb,tb=choose(ix['cal']),choose(ix['test'])
        c=z[cb].mean(axis=1).max(axis=1);t=z[tb].mean(axis=1).max(axis=1)
        out['block_size_sensitivity'][str(size)]={'cal_blocks':len(cb),'test_blocks':len(tb),'minimum_rank':1/(len(cb)+1),'base_flags':int((ranks(t,c)<=.05).sum()),'status':'rank_resolution_insufficient' if len(cb)<19 else 'exploratory'}
    return out


def wider_tail_coverage(path):
    """Coverage-only follow-up: can existing 81-account MAX panel rescue H31?"""
    spec=importlib.util.spec_from_file_location('analyze_max_tail',Path(__file__).with_name('analyze_max_tail.py'))
    tail=importlib.util.module_from_spec(spec);spec.loader.exec_module(tail)
    posts,clocks,sha=tail.load(path)
    rows,opp,audit,_=tail.intervals(posts,clocks)
    available=Counter((r['account'],r['day']) for r in rows if r['actual_start_age']>=4 and r['q24'] is not None)
    possible=Counter()
    for (aid,day,band),n in opp.items():
        if band in tail.BANDS[2:]:possible[aid,day]+=n
    accounts=sorted({p['post']['primary_account_id'] for p in posts})
    out={'panel_sha256':sha,'accounts':len(accounts),'interval_audit':audit,'regimes':{},
         'status':'coverage_only_not_an_outcome_test',
         'rule':'three specified consecutive reaction days; actual post age >=4 days; exact V/R, valid early24; >=5 eligible posts/day and >=50% catalog opportunity coverage'}
    for name,days in [('cal',['2026-09-19','2026-09-20','2026-09-21']),('test',['2026-09-24','2026-09-25','2026-09-26'])]:
        counts=Counter(sum(available[aid,day]>=5 and available[aid,day]/max(1,possible[aid,day])>=.5 for day in days) for aid in accounts)
        out['regimes'][name]={'days':days,'accounts_by_usable_days':{str(k):v for k,v in sorted(counts.items())},'complete_blocks':counts[3]}
    return out


def run(panel,tail_panel=None):
    posts,sha=OLD.load_panel(panel)
    exact={p:select_rows(posts,p,True) for p in ('max','vk')}
    audit={p:{s:sum(q['platform']==p and OLD.split(q)==s for q in posts) for s in ('fit','cal','test')} for p in OLD.PLATFORMS}
    result={'seed':SEED,'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,
            'panel_sha256':sha,'protocol':'PLATFORMS.md H26-H29, archived period reused',
            'catalog_temporal_folds':audit,
            'h26_transfer':transfer(posts),'h27_late_waves':waves(posts),
            'h28_repeated':{p:repeated(r) for p,r in exact.items()},
            'h29_contamination':{p:contamination(r) for p,r in exact.items()},
            'h30_stability':{p:stability(r) for p,r in exact.items()},
            'h31_distinct_days':{p:repeated(r,True) for p,r in exact.items()}}
    if tail_panel:result['wider_max_tail_coverage']=wider_tail_coverage(tail_panel)
    return result


def plot(result,path):
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(1,3,figsize=(14,4.8),layout='constrained')
    colors=['#238b8d','#d27a20','#8e64a9','#607d8b']
    for j,plat in enumerate(('max','telegram')):
        ms=result['h26_transfer'][plat]['models'];names=list(ms)
        ax[0].bar(np.arange(len(names))+.35*j,[ms[n]['mae_log1p'] for n in names],.32,label=plat.upper(),color=colors[j])
    ax[0].set_xticks(np.arange(4)+.17,['Own','Foreign','Foreign +\nlocal level','Pooled']);ax[0].set_ylabel('Mean |log-count error|');ax[0].set_title('24 to 72 h views\nTG: displayed values only');ax[0].legend()
    labels=[]; vals=[]
    for plat in ('max','vk'):
        w=result['h27_late_waves'][plat]['waves'];labels.append(f'{plat.upper()}\n{w["hits"]}/{w["n"]}');vals.append(100*w['rate'])
    ax[1].bar(labels,vals,color=colors[:2]);ax[1].set_ylabel('% of eligible posts');ax[1].set_title('Descriptive wave after day 4\nNot an anomaly label')
    for j,plat in enumerate(('max','vk')):
        rr=result['h28_repeated'][plat]
        for kind,style in (('late','-'),('early','--')):
            ax[2].plot([10,30,100],[100*rr['injections'][f'{kind}:{f}:all_three']['mean_components']['new_on_common_clear']['rate'] for f in (.1,.3,1.)],marker='o',linestyle=style,label=f'{plat.upper()} {kind} ({rr["common_clear_blocks"]})',color=colors[j])
    ax[2].set_xlabel('Added to counters, %');ax[2].set_ylabel('Newly flagged blocks, %');ax[2].set_title('Three-post additions\nLate: 72 h only; early: also 24 h');ax[2].legend()
    fig.suptitle('H26-H31: archival diagnostics, no labeled fraud outcomes',fontsize=14)
    fig.savefig(path,dpi=150);plt.close(fig)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--panel',type=Path);ap.add_argument('--tail-panel',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--plot-only',type=Path);ap.add_argument('--figure',type=Path);a=ap.parse_args()
    if a.plot_only:plot(json.loads(a.plot_only.read_text()),a.figure)
    else:
        data=run(a.panel,a.tail_panel);a.output.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
