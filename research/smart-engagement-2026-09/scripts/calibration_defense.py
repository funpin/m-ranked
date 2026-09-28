"""H32-H35: robust fit, calibration defenses, and ordinary alternatives.

Research-only, reuses unlabeled archival periods. No production access.
The iid score experiment has an explicitly known null; the archive does not.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import numpy as np
import scipy
from scipy.stats import norm

SEED=20265228
spec=importlib.util.spec_from_file_location('platform_validation',Path(__file__).with_name('platform_validation.py'))
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
CALIBRATORS=('pooled','account_balanced','trim_top_10pct')


def solve(x,y,penalty,weight=None):
    weight=np.ones(len(y)) if weight is None else weight
    return np.linalg.solve(x.T@(weight[:,None]*x)+penalty,x.T@(weight*y))


class References(P.FourReferences):
    def __init__(self,rows,fit,early,late,robust=False):
        self.accounts=sorted({rows[i]['primary_account_id'] for i in fit})
        self.beta=[];self.center=[];self.sd=[];self.scales=[];self.optimization=[]
        for k in range(4):
            metric=k%2;col=np.log1p(early[:,metric])
            self.center.append(col[fit].mean());self.sd.append(max(col[fit].std(),1e-8))
            xx=self.design(rows,early,k)[fit];yy=np.log1p(late[fit,metric])
            penalty=10*np.eye(xx.shape[1]);penalty[0,0]=0
            beta=solve(xx,yy,penalty);initial=yy-xx@beta
            sigma=max(1.4826*float(np.median(np.abs(initial-np.median(initial)))),.05)
            converged=not robust;iterations=0
            if robust:
                for iterations in range(1,101):
                    residual=yy-xx@beta
                    weights=np.minimum(1,1.345*sigma/np.maximum(np.abs(residual),1e-12))
                    new=solve(xx,yy,penalty,weights)
                    difference=np.max(np.abs(new-beta));beta=new
                    if difference<1e-8:converged=True;break
            self.beta.append(beta);e=yy-xx@beta
            self.scales.append(max(float(np.quantile(e,.75)-np.quantile(e,.25)),.05))
            self.optimization.append({'converged':converged,'iterations':iterations,'huber_scale':sigma})


def calibrate(score,cal,accounts,kind):
    score=np.asarray(score);cal=np.asarray(cal);accounts=np.asarray(accounts)
    if kind=='pooled':return P.ranks(score,cal)
    if kind=='trim_top_10pct':
        keep=len(cal)-int(np.floor(.1*len(cal)))
        return P.ranks(score,np.sort(cal)[:keep])
    if kind=='account_balanced':
        groups=sorted(set(accounts))
        return (1+sum((cal[accounts==g,None]>=score).mean(axis=0) for g in groups))/(len(groups)+1)
    raise ValueError(kind)


def selected_history(rows,indices,target,fraction):
    selected=[]
    for account in sorted(target):
        ii=[i for i in indices if rows[i]['primary_account_id']==account]
        ii.sort(key=lambda i:hashlib.sha256(rows[i]['id'].encode()).hexdigest())
        selected.extend(ii[:int(np.ceil(len(ii)*fraction))])
    return np.array(selected,int)


def rates(flags,keep,groups):
    return P.rate(np.asarray(flags)[keep],groups[keep])


def empirical(rows):
    ix=P.fold(rows);early,late=P.counts(rows);fit,cal,test=(ix[s] for s in ('fit','cal','test'))
    accounts=np.array([r['primary_account_id'] for r in rows]);groups=accounts[test]
    chosen=set(sorted(set(accounts),key=lambda a:hashlib.sha256(a.encode()).hexdigest())[:len(set(accounts))//3])
    target=np.array([a in chosen for a in groups]);original_models={};baseline={};original_scores={}
    for name,robust in (('ridge',False),('huber',True)):
        model=References(rows,fit,early,late,robust);original_models[name]=model
        z=model.residuals(rows,early,late);score=z.max(axis=1);original_scores[name]=score
        for kind in CALIBRATORS:
            key=f'{name}:{kind}'
            rank=calibrate(score[test],score[cal],accounts[cal],kind)
            baseline[key]={'ranks':rank,'alerts':P.rate(rank<=.05,groups)}
    clear=np.logical_and.reduce([b['ranks']>.05 for b in baseline.values()])
    out={'counts':{s:len(v) for s,v in ix.items()},'test_accounts':len(set(groups)),
         'cal_accounts':len(set(accounts[cal])),'account_rank_floor':1/(len(set(accounts[cal]))+1),
         'target_accounts':len(chosen),'test_target_posts':int(target.sum()),'common_clear_target_posts':int((clear&target).sum()),
         'baseline':{key:value['alerts'] for key,value in baseline.items()},'fits':{},'scenarios':{},'ordinary_alternatives':{}}
    for name,model in original_models.items():
        z=model.residuals(rows,early,late);errors=np.abs(z[test]*np.array(model.scales))
        other=original_models['ridge'];othererr=np.abs(other.residuals(rows,early,late)[test]*np.array(other.scales))
        out['fits'][name]={'mae_by_component':errors.mean(axis=0).tolist(),
            'paired_mean_mae_delta_vs_ridge':P.OLD.cluster_delta((errors-othererr).mean(axis=1),groups,np.random.default_rng(SEED)),
            'optimization':model.optimization}
    for fraction in (1/3,1.):
        for dose in (.1,.3,1.):
            for phase in ('none','fit','cal','fit_and_cal'):
                modified=[]
                if phase in ('fit','fit_and_cal'):modified.extend(selected_history(rows,fit,chosen,fraction))
                if phase in ('cal','fit_and_cal'):modified.extend(selected_history(rows,cal,chosen,fraction))
                a,b=P.inject(early,late,np.array(modified,int),dose,'early')
                report={'fit_modified_posts':sum(i in set(fit) for i in modified),
                        'cal_modified_posts':sum(i in set(cal) for i in modified),'methods':{},'optimization':{}}
                for name,robust in (('ridge',False),('huber',True)):
                    model=References(rows,fit,a,b,robust)
                    cc=model.residuals(rows,a,b).max(axis=1)[cal]
                    aa,bb=P.inject(a,b,test[target],dose,'early')
                    scores=model.residuals(rows,aa,bb).max(axis=1)[test]
                    report['optimization'][name]=model.optimization
                    for kind in CALIBRATORS:
                        flags=calibrate(scores,cc,accounts[cal],kind)<=.05
                        report['methods'][f'{name}:{kind}']={
                            'new_on_common_clear_target':rates(flags,clear&target,groups),
                            'all_target':rates(flags,target,groups),
                            'unchanged_other_accounts':rates(flags,~target,groups)}
                out['scenarios'][f'history={fraction}:dose={dose}:phase={phase}']=report
    for scenario in ('audience_growth_30pct','late_exposure_wave'):
        a,b=early.copy(),late.copy()
        if scenario=='audience_growth_30pct':a,b=P.inject(a,b,test[target],.3,'early')
        else:
            b[test[target],0]+=np.rint(b[test[target],0])
            b[test[target],1]+=np.rint(.3*b[test[target],1])
        report={}
        for name,model in original_models.items():
            score=model.residuals(rows,a,b).max(axis=1)[test]
            if scenario=='audience_growth_30pct':
                aa,bb=P.inject(early,late,test[target],.3,'early')
                assert np.array_equal(score,model.residuals(rows,aa,bb).max(axis=1)[test])
            for kind in CALIBRATORS:
                flags=calibrate(score,original_scores[name][cal],accounts[cal],kind)<=.05
                report[f'{name}:{kind}']={'all_target':rates(flags,target,groups),'new_on_common_clear_target':rates(flags,clear&target,groups)}
        out['ordinary_alternatives'][scenario]=report
    out['identical_counterfactual_scores_verified']=True
    return out


def safe_quantile_bounds(cal,m,alpha=.05):
    """Exactly m unknown contamination identities; n-m iid inliers assumed.

    This is an order-statistic identification bound, not a method to estimate m.
    If the clean quantile cannot be finite, both ends are infinite.
    """
    values=np.sort(np.asarray(cal));n=len(values)
    if not 0<=m<n or not 0<alpha<1:raise ValueError('invalid count or alpha')
    k=int(np.ceil((n-m+1)*(1-alpha)))
    lower=float(values[k-1]) if k<=n-m else np.inf
    upper=float(values[k+m-1]) if k+m<=n else np.inf
    return lower,upper


def known_null():
    rng=np.random.default_rng(SEED);out={}
    for fraction in (0.,.2):
        n=200;m=int(n*fraction);items={k:[] for k in ('standard','trim_top_10pct','safe_upper')};power={k:[] for k in items}
        for _ in range(500):
            clean=rng.normal(size=n-m)+4*(rng.random(n-m)<.05)
            cal=np.r_[clean,rng.normal(6,1,m)]
            standard=safe_quantile_bounds(cal,0)[1]
            trimmed=safe_quantile_bounds(np.sort(cal)[:n-int(.1*n)],0)[1]
            safe=safe_quantile_bounds(cal,m)[1]
            for name,t in zip(items,(standard,trimmed,safe)):
                items[name].append(float(.95*norm.sf(t)+.05*norm.sf(t-4)))
                power[name].append(float(norm.sf(t-6)))
        out[str(fraction)]={'calibration_sets':500,'calibration_size':n,'known_contaminants':m,'methods':{}}
        for name,a in items.items():
            out[str(fraction)]['methods'][name]={'mean_known_null_risk':float(np.mean(a)),
                'risk_mean_monte_carlo_se':float(np.std(a,ddof=1)/np.sqrt(len(a))),
                'conditional_risk_p05_p50_p95':list(map(float,np.quantile(a,[.05,.5,.95]))),
                'mean_power_against_N6':float(np.mean(power[name]))}
    return out


def measurement_audit(posts):
    """Descriptive impact of exact-only preparation, not detection accuracy.

    Count archived main-stream readings only. Refreshed horizon overrides used
    by the prediction experiments are separate and not a second stream here.
    """
    out={}
    for plat in P.OLD.PLATFORMS:
        ps=[p for p in posts if p['platform']==plat]
        points=[q for p in ps for q in p['points']]
        result={'posts':len(ps),'main_snapshots':len(points),'metrics':{}}
        for metric in ('v','r'):
            old=lambda q:q[metric] is not None and q[metric+'q'] not in ('invalid','suspected_reset')
            exact=lambda q:P.OLD.valid(q,metric,True)
            result['metrics'][metric]={
                'old_loader_accepted':sum(old(q) for q in points),
                'exact_certain':sum(exact(q) for q in points),
                'formerly_accepted_excluded':sum(old(q) and not exact(q) for q in points),
                'quality_counts':dict(sorted(Counter(q[metric+'q'] for q in points).items())),
                'posts_with_two_exact_certain_readings':sum(sum(exact(q) for q in p['points'])>=2 for p in ps)}
        out[plat]=result
    return out


def run(panel):
    posts,sha=P.OLD.load_panel(panel)
    return {'seed':SEED,'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,
        'panel_sha256':sha,'status':'research_only_unlabeled_reused_period; known_null has a separately specified iid data generator',
        'measurement_audit':measurement_audit(posts),
        'empirical':{plat:empirical(P.select_rows(posts,plat,True)) for plat in ('max','vk')},'known_null':known_null()}


def plot(r,path):
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(1,3,figsize=(14,4.7),layout='constrained')
    names=['ridge:pooled','huber:pooled','ridge:account_balanced','huber:account_balanced','ridge:trim_top_10pct','huber:trim_top_10pct']
    labels=['Ridge','Huber','Ridge\nbalanced','Huber\nbalanced','Ridge\ntrim10','Huber\ntrim10']
    for j,plat in enumerate(('max','vk')):
        p=r['empirical'][plat];scenario=p['scenarios']['history=1.0:dose=1.0:phase=fit_and_cal']
        vals=[100*scenario['methods'][n]['new_on_common_clear_target']['rate'] for n in names]
        ax[0].bar(np.arange(6)+.35*j,vals,.32,label=plat.upper())
        ax[1].bar(np.arange(6)+.35*j,[100*p['baseline'][n]['rate'] for n in names],.32,label=plat.upper())
    for a in ax[:2]:a.set_xticks(np.arange(6)+.17,labels,fontsize=8);a.legend()
    ax[0].set_title('Doubled fit + calibration + test\nNew flags on common clear subset');ax[0].set_ylabel('% of modified target posts')
    ax[1].set_title('Unmodified archive\nOrigin unknown, not false positive rate');ax[1].set_ylabel('% of posts flagged')
    kn=r['known_null']['0.0']['methods'];ns=list(kn)
    ax[2].bar(range(3),[100*kn[n]['mean_known_null_risk'] for n in ns]);ax[2].axhline(5,color='black',linestyle='--');ax[2].set_xticks(range(3),['Standard','Trim top 10%','Safe upper']);ax[2].set_ylabel('Mean false alert probability, %');ax[2].set_title('Known benign iid mixture\nNo contamination in calibration')
    fig.suptitle('H32-H35: robust fitting is not reliable calibration cleaning');fig.savefig(path,dpi=150);plt.close(fig)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--panel',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--plot-only',type=Path);ap.add_argument('--figure',type=Path);a=ap.parse_args()
    if a.plot_only:plot(json.loads(a.plot_only.read_text()),a.figure)
    else:a.output.write_text(json.dumps(run(a.panel),ensure_ascii=False,indent=2,allow_nan=False)+'\n')
