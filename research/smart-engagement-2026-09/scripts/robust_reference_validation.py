"""Fixed-protocol local tests of independent references and benign alternatives.

No writes to production and no new data extraction. The empirical archive
is unlabeled; all trajectory risks refer only to specified synthetic families.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import platform

import numpy as np
import scipy
from scipy.stats import binom

SEED = 20263228
WORLDS = 2000
ALPHA = .05
DELTA = .05
FAMILIES = ('baseline', 'archive_sessions', 'exposure_event')
MODELS = ('conditional_v24', 'account_only', 'prepublication_context')


def helper(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OLD = helper('observable_validation')
MASK = helper('masked_engagement_validation')


def design(rows, fit, mode, early):
    cols = [np.ones(len(rows))]
    accounts = sorted({rows[i]['primary_account_id'] for i in fit})
    if mode == 'conditional_v24':
        return np.column_stack(cols+[np.log1p(early)])
    cols += [np.array([p['primary_account_id']==a for p in rows], float) for a in accounts]
    if mode == 'prepublication_context':
        types = sorted({rows[i]['publication_type'] for i in fit})
        cols += [np.array([p['publication_type']==t for p in rows], float) for t in types[1:]]
        clocks = [p['published']+timedelta(hours=3) for p in rows]
        for period, values in ((24, [p.hour+p.minute/60 for p in clocks]), (7, [p.weekday() for p in clocks])):
            phase = 2*np.pi*np.array(values)/period
            cols += [np.sin(phase), np.cos(phase)]
    elif mode != 'account_only':
        raise ValueError(mode)
    x = np.column_stack(cols)
    # Parameters of this transform are learned only from the fitting split.
    for j in range(1, x.shape[1]):
        if len(np.unique(x[fit, j])) > 2:
            x[:, j] = (x[:, j]-x[fit, j].mean())/max(x[fit, j].std(), 1e-8)
    return x


def temporal_folds(rows, leave_account_out):
    base = {s:np.array([i for i,p in enumerate(rows) if OLD.split(p)==s], int)
            for s in ('fit','cal','test')}
    for left,right in (('fit','cal'),('cal','test')):
        assert max(rows[i]['published']+timedelta(hours=72) for i in base[left]) < min(rows[i]['published'] for i in base[right])
    if not leave_account_out:
        return [(None,base['fit'],base['cal'],base['test'])]
    accounts = sorted({rows[i]['primary_account_id'] for i in base['test']})
    folds=[]
    for account in accounts:
        fit=np.array([i for i in base['fit'] if rows[i]['primary_account_id']!=account],int)
        cal=np.array([i for i in base['cal'] if rows[i]['primary_account_id']!=account],int)
        test=np.array([i for i in base['test'] if rows[i]['primary_account_id']==account],int)
        assert account not in {rows[i]['primary_account_id'] for i in np.r_[fit,cal]}
        folds.append((account,fit,cal,test))
    return folds


def empirical_upper(scores, calibration):
    return (1+(calibration[:,None]>=scores).sum(axis=0))/(len(calibration)+1)


def endpoint_references(path):
    posts,sha=OLD.load_panel(path)
    rows=[p for p in posts if p['platform']=='max' and OLD.split(p)!='embargo'
          and OLD.valid(p['endpoints'][24],'v',True) and OLD.valid(p['endpoints'][72],'v',True)
          and p['endpoints'][72]['v']>=p['endpoints'][24]['v']]
    early=np.array([p['endpoints'][24]['v'] for p in rows])
    late=np.array([p['endpoints'][72]['v'] for p in rows])
    y=np.log1p(late)
    out={'panel_sha256':sha,'counts':{s:sum(OLD.split(p)==s for p in rows) for s in ('fit','cal','test')},'regimes':{}}
    for leaveout in (False,True):
        folds=temporal_folds(rows,leaveout)
        # Collect the same test rows in the same order for every model.
        ids=np.concatenate([f[3] for f in folds])
        accounts=np.array([rows[i]['primary_account_id'] for i in ids])
        ranks={mode:{} for mode in MODELS}
        errors={mode:[] for mode in MODELS}
        for mode in MODELS:
            store={key:[] for key in ['base']+[f'{kind}:{f}' for kind in ('late','early') for f in (.1,.3,1.)]}
            for _,fit,cal,test in folds:
                x=design(rows,fit,mode,early)
                penalty=10*np.eye(x.shape[1]);penalty[0,0]=0
                beta=np.linalg.solve(x[fit].T@x[fit]+penalty,x[fit].T@y[fit])
                prediction=x@beta
                residual=y[cal]-prediction[cal]
                errors[mode].extend(np.abs(y[test]-prediction[test]))
                store['base'].append(empirical_upper(y[test]-prediction[test],residual))
                for f in (.1,.3,1.):
                    changed_late=late+np.rint(f*late).astype(int)
                    for kind in ('late','early'):
                        changed_early=early if kind=='late' else early+np.rint(f*early).astype(int)
                        # The conditional model has no fitted normalization, and the
                        # prepublication models do not depend on these counters.
                        changed_x=design(rows,fit,mode,changed_early)
                        score=np.log1p(changed_late[test])-(changed_x@beta)[test]
                        store[f'{kind}:{f}'].append(empirical_upper(score,residual))
            ranks[mode]={k:np.concatenate(v) for k,v in store.items()}
        ranks['combined_bonferroni']={k:np.minimum(1,2*np.minimum(ranks['conditional_v24'][k],ranks['prepublication_context'][k])) for k in ranks['conditional_v24']}
        common_clear=np.logical_and.reduce([r['base']>ALPHA for r in ranks.values()])
        report={'test_posts':len(ids),'test_accounts':len(set(accounts)),
                'folds':len(folds),'common_base_clear':int(common_clear.sum()),'models':{}}
        for mode,rs in ranks.items():
            def observed(flags,keep=None):
                keep=np.ones(len(ids),bool) if keep is None else keep
                return OLD.observed_rate(flags[keep],accounts[keep],np.random.default_rng(SEED+23))
            item={'base_alerts_unlabeled':observed(rs['base']<=ALPHA),'injections':{}}
            if mode in errors:
                item['mae_log1p']=float(np.mean(errors[mode]))
                item['paired_mae_delta_vs_account_only']=OLD.cluster_delta(np.array(errors[mode])-np.array(errors['account_only']),accounts,np.random.default_rng(SEED+24))
            for kind in ('late','early'):
                item['injections'][kind]={str(f):{'all':observed(rs[f'{kind}:{f}']<=ALPHA),
                    'new_on_common_clear':observed(rs[f'{kind}:{f}']<=ALPHA,common_clear)} for f in (.1,.3,1.)}
            report['models'][mode]=item
        report['scope']='same historical period reused, not a new untouched holdout; false positives unknown without labels'
        out['regimes']['account_excluded' if leaveout else 'known_account']=report
    return out


def simulate_n(designs,seed,n=WORLDS):
    original=MASK.N
    try:
        MASK.N=n
        return MASK.simulate(designs,seed)
    finally:
        MASK.N=original


def add_archive_sessions(sample,seed,mean_sessions=2.,reaction_probability=.7,broad_count=None):
    """Each simulated visitor visits a distinct subset of actually observed posts."""
    views,reactions,mask,mu,q=sample
    views,reactions=views.copy(),reactions.copy()
    rng=np.random.default_rng(seed)
    for i in range(len(views)):
        days=np.flatnonzero(mask[i].any(axis=0))
        if not len(days):continue
        count=int(rng.poisson(mean_sessions)) if broad_count is None else broad_count
        for _ in range(count):
            day=int(rng.choice(days))
            posts=np.flatnonzero(mask[i,:,day])
            depth=min(len(posts),int(rng.geometric(.35))) if broad_count is None else len(posts)
            selected=rng.choice(posts,size=depth,replace=False)
            views[i,selected,day]+=1
            reactions[i,selected,day]+=rng.binomial(1,reaction_probability,size=depth)
    return views,reactions,mask,mu,q


def add_exposure_event(sample,seed,fixed_fraction=None):
    views,reactions,mask,mu,q=sample
    views,reactions=views.copy(),reactions.copy()
    rng=np.random.default_rng(seed)
    pulse=np.zeros(mask.shape,bool)
    fraction=rng.uniform(.15,.6,(len(mask),1,1)) if fixed_fraction is None else fixed_fraction
    for i in range(len(mask)):
        days=np.flatnonzero(mask[i].any(axis=0))
        chosen=rng.choice(days,size=min(2,len(days)),replace=False)
        pulse[i,:,chosen]=mask[i,:,chosen]
    weights=pulse*mu
    allocation=weights/np.maximum(weights.sum(axis=2,keepdims=True),1e-12)
    extra=rng.poisson(fraction*mu.sum(axis=2,keepdims=True)*allocation)*mask
    views+=extra
    reactions+=MASK.nb(rng,q*extra)*mask
    return views,reactions,mask,mu,q


def family(sample,name,seed):
    if name=='baseline':return sample
    if name=='archive_sessions':return add_archive_sessions(sample,seed)
    if name=='exposure_event':return add_exposure_event(sample,seed)
    raise ValueError(name)


def mixture(designs,seed,n):
    base=simulate_n(designs,seed,n)
    modified=[family(base,name,seed+10+j) for j,name in enumerate(FAMILIES)]
    labels=np.random.default_rng(seed+20).integers(len(FAMILIES),size=n)
    indices=np.arange(n)
    return tuple(np.stack([s[k] for s in modified])[labels,indices] for k in range(5))


def score_scale(features):
    center=np.median(features,axis=0)
    scale=np.maximum(np.quantile(features,.75,axis=0)-np.quantile(features,.25,axis=0),1e-6)
    return center,scale


def joint_score(sample,center,scale):
    return ((MASK.features(*sample)-center)/scale).max(axis=1)


def tolerance_threshold(scores,delta=DELTA,alpha=ALPHA):
    n=len(scores)
    order=int(binom.ppf(1-delta,n,1-alpha))+1
    return (float(np.sort(scores)[order-1]) if order<=n else float('inf')),order


def benign_calibration(panel):
    designs,info=MASK.templates(panel)
    center,scale=score_scale(MASK.features(*simulate_n(designs,SEED+100)))
    calibrations={name:joint_score(family(simulate_n(designs,SEED+200+j),name,SEED+300+j),center,scale) for j,name in enumerate(FAMILIES)}
    baseline,base_order=tolerance_threshold(calibrations['baseline'])
    mix,mix_order=tolerance_threshold(joint_score(mixture(designs,SEED+400,WORLDS*3),center,scale))
    family_thresholds={name:tolerance_threshold(scores,DELTA/len(FAMILIES)) for name,scores in calibrations.items()}
    thresholds={'baseline_only':baseline,'equal_mixture':mix,'family_envelope':max(v[0] for v in family_thresholds.values())}
    def rates(sample):
        s=joint_score(sample,center,scale)
        return {method:MASK.rate(s>cut) for method,cut in thresholds.items()}
    reference={name:rates(family(simulate_n(designs,SEED+500+j),name,SEED+600+j)) for j,name in enumerate(FAMILIES)}
    heldbase=simulate_n(designs,SEED+700)
    broad=add_archive_sessions(heldbase,SEED+701,broad_count=1,reaction_probability=1.)
    held={
        'single_broad_reader':rates(broad),
        'three_broad_sessions':rates(add_archive_sessions(heldbase,SEED+702,broad_count=3,reaction_probability=1.)),
        'larger_exposure_event':rates(add_exposure_event(heldbase,SEED+703,fixed_fraction=1.)),
        'ordinary_joint_growth_30':rates(MASK.perturb(heldbase,'smooth_joint',.3,SEED+704)),
    }
    backgrounds={'baseline':simulate_n(designs,SEED+800),'equal_mixture':mixture(designs,SEED+900,WORLDS)}
    tests={}
    for background,base in backgrounds.items():
        base_score=joint_score(base,center,scale)
        common_clear=np.logical_and.reduce([base_score<=cut for cut in thresholds.values()])
        cases={}
        for j,name in enumerate(('smooth_joint','proportional_path','diffuse_reactions','shared_reaction_pulses','independent_reaction_pulses')):
            cases[name]={}
            for k,f in enumerate((.1,.3,1.)):
                changed=MASK.perturb(base,name,f,SEED+1000+100*j+k)
                scores=joint_score(changed,center,scale)
                cases[name][str(f)]={'actual_added_views_fraction':float((changed[0].sum()-base[0].sum())/base[0].sum()),
                    'actual_added_reactions_fraction':float((changed[1].sum()-base[1].sum())/max(base[1].sum(),1)),
                    'methods':{method:{'all':MASK.rate(scores>cut),'new_on_common_clear':MASK.rate((scores>cut)[common_clear])} for method,cut in thresholds.items()}}
        tests[background]={'common_base_clear':int(common_clear.sum()),'base_alerts':rates(base),'cases':cases}
    # One set of observations with two possible mechanisms has one numerical result.
    same_growth=MASK.perturb(heldbase,'smooth_joint',.3,SEED+704)
    equality=np.array_equal(joint_score(same_growth,center,scale),joint_score(tuple(x.copy() for x in same_growth),center,scale))
    return {'templates':info,'worlds':WORLDS,'scale_center':center.tolist(),'scale_iqr':scale.tolist(),
        'thresholds':thresholds,'orders':{'baseline':base_order,'mixture':mix_order,'family':{k:v[1] for k,v in family_thresholds.items()}},
        'family_thresholds':{k:v[0] for k,v in family_thresholds.items()},
        'reference_family_test':reference,'heldout_alternatives':held,'sensitivity':tests,
        'same_growth_observables_equal':bool(equality),
        'scope':'known-reference synthetic families on fixed masks; no real-world manipulation accuracy or organic label inference'}


def component_calibration(panel,primary):
    """Post-primary hypothesis; new calibration and test streams, no tuning."""
    designs,info=MASK.templates(panel)
    center=np.array(primary['scale_center']);scale=np.array(primary['scale_iqr'])
    calibration={name:MASK.features(*family(simulate_n(designs,SEED+2000+j),name,SEED+2100+j)) for j,name in enumerate(FAMILIES)}
    k=len(MASK.COMPONENTS)
    per_family={name:[tolerance_threshold(fs[:,j],DELTA/(len(FAMILIES)*k),ALPHA/k)[0] for j in range(k)] for name,fs in calibration.items()}
    vector=np.max(list(per_family.values()),axis=0)
    scalar=max(tolerance_threshold(((fs-center)/scale).max(axis=1),DELTA/len(FAMILIES))[0] for fs in calibration.values())
    def flags(sample):
        fs=MASK.features(*sample)
        return {'joint_family':((fs-center)/scale).max(axis=1)>scalar,
                'component_family':(fs>vector).any(axis=1)}
    def rates(sample):return {m:MASK.rate(f) for m,f in flags(sample).items()}
    reference={name:rates(family(simulate_n(designs,SEED+2200+j),name,SEED+2210+j)) for j,name in enumerate(FAMILIES)}
    heldbase=simulate_n(designs,SEED+2300)
    held={
        'single_broad_reader':rates(add_archive_sessions(heldbase,SEED+2301,broad_count=1,reaction_probability=1.)),
        'three_broad_sessions':rates(add_archive_sessions(heldbase,SEED+2302,broad_count=3,reaction_probability=1.)),
        'larger_exposure_event':rates(add_exposure_event(heldbase,SEED+2303,fixed_fraction=1.)),
        'ordinary_joint_growth_30':rates(MASK.perturb(heldbase,'smooth_joint',.3,SEED+2304)),
    }
    backgrounds={'baseline':simulate_n(designs,SEED+2400),'equal_mixture':mixture(designs,SEED+2500,WORLDS)}
    tests={}
    for background,base in backgrounds.items():
        base_flags=flags(base)
        clear=~np.logical_or.reduce(list(base_flags.values()))
        cases={}
        for j,name in enumerate(('smooth_joint','proportional_path','diffuse_reactions','shared_reaction_pulses','independent_reaction_pulses')):
            cases[name]={}
            for i,f in enumerate((.1,.3,1.)):
                changed=MASK.perturb(base,name,f,SEED+2600+j*100+i)
                ff=flags(changed)
                cases[name][str(f)]={'methods':{m:{'all':MASK.rate(v),'new_on_common_clear':MASK.rate(v[clear])} for m,v in ff.items()},
                    'actual_added_views_fraction':float((changed[0].sum()-base[0].sum())/base[0].sum()),
                    'actual_added_reactions_fraction':float((changed[1].sum()-base[1].sum())/max(base[1].sum(),1))}
        tests[background]={'common_base_clear':int(clear.sum()),'base_alerts':{m:MASK.rate(v) for m,v in base_flags.items()},'cases':cases}
    return {'post_primary_hypothesis':True,'templates':info['accounts'],'worlds':WORLDS,
            'component_names':MASK.COMPONENTS,'component_alpha':ALPHA/k,'family_component_delta':DELTA/(len(FAMILIES)*k),
            'component_thresholds':vector.tolist(),'per_family_component_thresholds':per_family,'joint_threshold':scalar,
            'reference_family_test':reference,'heldout_alternatives':held,'sensitivity':tests,
            'scope':'new random worlds from same stated families and fixed masks; no stronger guarantee on real MAX'}


def plot_result(result,output):
    """Plot stored numbers only; optional dependencies never affect simulations."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,
                         'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,3,figsize=(16,7.5),gridspec_kw={'width_ratios':[1,1.2,1.25]})
    fig.subplots_adjust(left=.07,right=.98,bottom=.35,top=.78,wspace=.57)
    fig.suptitle('MAX: два ориентира нормы и отдельные пороги признаков',x=.07,y=.96,ha='left',fontsize=17,weight='bold')
    fig.text(.07,.89,'H23 — реальные немеченые счётчики; H25 — новые синтетические реализации на прежних 59 масках наблюдения.',color='#555555')
    blue,orange='#285f9e','#d45e26'
    ax=axes[0]
    models=result['endpoint_references']['regimes']['known_account']['models']
    for mode,label,color in [('conditional_v24','Прогноз с опорой на V24',blue),
                             ('combined_bonferroni','Два прогноза + поправка',orange)]:
        values=[100*models[mode]['injections']['early'][f]['new_on_common_clear']['rate'] for f in ('0.1','0.3','1.0')]
        ax.plot(range(3),values,'o-',color=color,label=label)
    ax.set_xticks(range(3),['10%','30%','100%']);ax.set_ylim(0,100)
    ax.set_xlabel('Добавка уже в первых сутках')
    ax.set_ylabel('Новые сигналы, % (общие 361 пост)')
    ax.set_title('A. Защита от ранней маскировки',loc='left',fontsize=11,pad=18)
    ax.legend(loc='upper left',bbox_to_anchor=(0,-.23),frameon=False,fontsize=9)
    component=result['component_calibration']
    ax=axes[1]
    cases=component['sensitivity']['baseline']['cases']
    labels=['Плавные V+R','Точные V×2 и R×2','Общие волны R']
    names=['smooth_joint','proportional_path','shared_reaction_pulses']
    positions=np.arange(len(names))
    for offset,method,label,color in [(-.18,'joint_family','Общий порог',blue),(.18,'component_family','Пороги по признакам',orange)]:
        values=[100*cases[n]['1.0']['methods'][method]['new_on_common_clear']['rate'] for n in names]
        bars=ax.barh(positions+offset,values,height=.34,color=color,label=label)
        for bar,v in zip(bars,values):ax.text(v+1,bar.get_y()+bar.get_height()/2,f'{v:.1f}',va='center',fontsize=9)
    ax.set_yticks(positions,labels,fontsize=9);ax.invert_yaxis();ax.set_xlim(0,100)
    ax.set_xlabel('Новые сигналы, % (общие 1984 окна)')
    ax.set_title('B. Крупные заданные добавки',loc='left',fontsize=11,pad=18)
    ax.legend(loc='upper left',bbox_to_anchor=(0,-.23),frameon=False,fontsize=9)
    ax=axes[2]
    names=['single_broad_reader','three_broad_sessions','larger_exposure_event']
    labels=['Один широкий\nчитатель','Три широкие\nсессии','Более крупный\nинфоповод']
    for offset,method,color in [(-.18,'joint_family',blue),(.18,'component_family',orange)]:
        values=[100*component['heldout_alternatives'][n][method]['rate'] for n in names]
        bars=ax.barh(positions+offset,values,height=.34,color=color)
        for bar,v in zip(bars,values):ax.text(v+1,bar.get_y()+bar.get_height()/2,f'{v:.1f}',va='center',fontsize=9)
    ax.set_yticks(positions,labels,fontsize=9);ax.invert_yaxis();ax.set_xlim(0,100)
    ax.set_xlabel('Все сигналы, % (по 2000 окон)')
    ax.set_title('C. Обычные альтернативы остаются',loc='left',fontsize=11,pad=18)
    for ax in axes:
        ax.grid(axis='y' if ax is axes[0] else 'x',color='#e6e6e6',linewidth=.7);ax.set_axisbelow(True)
    fig.text(.07,.11,'B: f=100%; фактическая доза общих волн меньше из-за пропусков. Плавные/пропорциональные V+R — около удвоения.',fontsize=10,color='#555555')
    fig.text(.07,.065,'C: контрольные альтернативы шире калибровочного семейства. Сигнал означает отклонение от заданной нормы, а не происхождение активности.',fontsize=10,color='#555555')
    fig.text(.07,.025,'H25 выбран после неудачи общего порога H24 и проверен на новых случайных реализациях. Это не оценка точности на реальной накрутке.',fontsize=10,color='#555555')
    fig.savefig(output,dpi=160,facecolor='white',metadata={'Software':'matplotlib; saved research aggregates'})
    plt.close(fig)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--endpoint-panel',type=Path)
    parser.add_argument('--tail-panel',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--plot-input',type=Path)
    parser.add_argument('--figure',type=Path)
    args=parser.parse_args()
    if args.plot_input:
        if not args.figure:parser.error('--plot-input requires --figure')
        if args.endpoint_panel or args.tail_panel or args.output:parser.error('plot-only mode cannot run numerical experiments')
        plot_result(json.loads(args.plot_input.read_text()),args.figure)
        return
    if not all((args.endpoint_panel,args.tail_panel,args.output)):
        parser.error('numerical mode requires --endpoint-panel, --tail-panel and --output')
    result={'seed':SEED,'runtime':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__},
            'endpoint_references':endpoint_references(args.endpoint_panel),
            'benign_calibration':benign_calibration(args.tail_panel)}
    result['component_calibration']=component_calibration(args.tail_panel,result['benign_calibration'])
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'output':str(args.output),'counts':result['endpoint_references']['counts'],
                      'thresholds':result['benign_calibration']['thresholds']}))


if __name__=='__main__':main()
