"""H62–H64: independent interval-window reference; research only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

import interval_evidence as I
G=I.G
P=I.P
T=I.T
SEED=20269428
PROTOCOL_SHA="0585798bbff9ab7f786c9e307693da965ec1c1a67b23010b91fed15cc1a9041f"
ORDINARY=("baseline","shallow_sessions","wide_sessions","high_engagement","audience_growth","campaign")
STRESS=("dense_walk","scheduled_campaign","delayed_reactors","vk_recommendation")
INJECTIONS=("persistent_r100","early_r100","preserve_er100","small_daily30","test_only_r100")
FAMILIES=ORDINARY+STRESS+INJECTIONS
MASKS=("full","independent","reaction_dependent","every_third")
REGIMES={"clean":(False,False),"fit30":(True,False),"cal30":(False,True),"both30":(True,True)}
MODES=("structural","conditional")
METHODS=("volume","joint")


def rng(*keys):return np.random.default_rng(np.random.SeedSequence([SEED,*keys]))


def provenance(root):
    doc=(root/'research/smart-engagement-2026-09/WINDOW_REFERENCE.md').read_text()
    part=doc.split('## Протокол H62–H64 до исходов\n',1)[1].split('## Результаты\n',1)[0]
    digest=hashlib.sha256(part.encode()).hexdigest()
    if digest!=PROTOCOL_SHA:raise ValueError('Registered protocol changed')
    return {'protocol_sha256':digest,'script_sha256':P.sha(__file__),
            'interval_sha256':P.sha(I.__file__),'generalization_sha256':P.sha(G.__file__),
            'parent_sha256':P.sha(P.__file__),'parser_sha256':P.sha(T.__file__),
            'test_sha256':P.sha(root/'tests/test_window_reference_research.py'),
            'seed':SEED,'production_changed':False,'storage_changed':False}


def source_contract(root):
    folder=root/'research/smart-engagement-2026-09'
    previous=json.loads((folder/'evidence/interval_evidence_2026-09-28.json').read_text())
    old=json.loads((folder/'evidence/max_tail_provenance_2026-09-28.json').read_text())
    actual=P.sha(folder/'sql/max_tail_endpoints.sql')
    if actual!=old['sha256']['sql/max_tail_endpoints.sql'] or actual!=previous['version_source_contracts']['panel_sql_sha256']:
        raise ValueError('Unverified latest-version source contract')
    return {'sql_sha256':actual,'H61_evidence_sha256':P.sha(folder/'evidence/interval_evidence_2026-09-28.json'),
        'snapshot_created_at_cutoff':'2026-09-28T00:00:00+00:00',
        'fit_values_available_before_test_verified':False,
        'reason':'Panel lacks per-row created_at; latest-at-extraction is not an as-of-fit replay'}


def extract(prepared,start,end,accounts=None,*,source_verified=False):
    """Use H61 adjacency/quality. Duration exclusions remain missing exposure."""
    if not source_verified:raise ValueError('Latest-version source must be verified before extraction')
    stats,edges=I.ledger(prepared,start,end,retain_edges=True,accounts=accounts,
        policy='latest_as_of_cutoff',latest_version_verified=True)
    meta={p['id']:p for p in prepared}
    points={p['id']:{v['at']:v['point'] for v in p['points']} for p in prepared}
    grouped=defaultdict(list)
    for e in edges:
        if e['hours']>72:continue
        p=meta[e['post']];left=points[e['post']][e['start']]
        grouped[e['account']].append(e|{'v0':left['v'],
            'age':(((e['start']+ (e['end']-e['start'])/2)-p['published']).total_seconds()/86400)})
    out={}
    for a,record in stats.items():
        rows=grouped[a];posts={r['post'] for r in rows};positive={r['post'] for r in rows if r['dr']>0}
        hours=sum(r['hours'] for r in rows);possible=record['possible_hours']
        coverage=hours/possible if possible else None
        span=(max(r['end'] for r in rows)-min(r['start'] for r in rows)).total_seconds()/3600 if rows else 0
        support=None
        if rows and coverage is not None and coverage>=.5:
            support=f"{'high' if coverage>=.75 else 'medium'}:{'short' if hours/len(rows)<=30 else 'long'}"
        eligible=bool(len(posts)>=10 and len(rows)>=20 and coverage is not None and coverage>=.5 and span>=72)
        out[a]={'rows':rows,'intervals':len(rows),'observed_posts':len(posts),'positive_posts':len(positive),
            'net_r':sum(r['dr'] for r in rows),'possible_posts':record['possible_posts'],'possible_hours':possible,
            'hours':hours,'coverage':coverage,'span_hours':span,'support':support,'eligible':eligible,
            'minimum_growth_days':I.minimum_days([(r['start'],r['end']) for r in rows if r['dr']>0]),
            'excluded':record['excluded']|{'over72h':record['intervals']-len(rows)}}
    return out


def design(rows,mode):
    if mode not in MODES:raise ValueError('Unknown model')
    days=np.array([r['hours']/24 for r in rows])
    if np.any(days<=0):raise ValueError('Positive duration required')
    columns=[np.ones(len(rows)),np.log(np.array([r['age'] for r in rows])/7),np.log1p([r['v0'] for r in rows])]
    if mode=='conditional':columns.append(np.log1p(np.array([r['dv'] for r in rows])/days))
    return np.column_stack(columns),np.log(days)


def fit(rows,mode):
    if len(rows)<100 or len({r['account'] for r in rows})<10:raise ValueError('Insufficient fitting support')
    counts=Counter(r['account'] for r in rows)
    weights=np.array([1/counts[r['account']] for r in rows]);weights*=len(rows)/weights.sum()
    x,offset=design(rows,mode)
    center=np.average(x,axis=0,weights=weights)
    scale=np.sqrt(np.average((x-center)**2,axis=0,weights=weights))
    center[0]=0;scale[0]=1;scale=np.maximum(scale,1e-8);x=(x-center)/scale
    y=np.array([r['dr'] for r in rows]);initial=np.zeros(x.shape[1]+1)
    initial[0]=np.log((weights@y+.5)/(weights@np.exp(offset)+.5))
    opt=minimize(G.nb_objective,initial,args=(x,y,offset,weights),jac=True,method='L-BFGS-B',
        bounds=[(None,None)]*x.shape[1]+[(-9,5)],options={'maxiter':700,'ftol':1e-10})
    if not opt.success:raise RuntimeError(f'NB fit failed: {opt.message}')
    return {'mode':mode,'center':center,'scale':scale,'beta':opt.x[:-1],'dispersion':float(np.exp(opt.x[-1])),
            'n':len(rows),'accounts':sorted(counts),'iterations':opt.nit}


def predict(model,rows):
    x,offset=design(rows,model['mode'])
    return np.exp(np.clip(offset+((x-model['center'])/model['scale'])@model['beta'],-25,25))


def score(window,model):
    value={k:v for k,v in window.items() if k!='rows'}
    if not window['eligible']:return value|{'status':'abstain_window_support'}
    rows=window['rows'];mu=predict(model,rows);alpha=model['dispersion']
    logzero=defaultdict(float)
    for r,m in zip(rows,mu):logzero[r['post']]+=-np.log1p(alpha*m)/alpha
    expected_breadth=sum(-np.expm1(v) for v in logzero.values())
    v=np.log((window['net_r']+.5)/(mu.sum()+.5))/np.log(2)
    b=(window['positive_posts']-expected_breadth)/window['observed_posts']/.1
    gate=window['minimum_growth_days']>=2 and window['positive_posts']>=3
    return value|{'status':'eligible','expected_r':float(mu.sum()),'expected_positive_posts':float(expected_breadth),
        'volume_component':float(v),'breadth_component':float(b),'recurrence_gate':gate,
        'scores':{'volume':float(max(0,v)) if gate else 0.,'joint':float(max(0,min(v,b))) if gate else 0.}}


def decision(target,cal,method,alpha=.05,platform='max'):
    if platform!='max':return {'status':'abstain','reason':'separate_platform_validation'}
    if target['status']!='eligible':return {'status':'abstain','reason':'window_support'}
    selected=[c['scores'][method] for c in cal if c['status']=='eligible' and c['support']==target['support']]
    return P.rank(target['scores'][method],selected,alpha=alpha)


def bootstrap(values,key):
    a=np.array(values,dtype=float)
    if len(a)==0:return {'n':0,'mean':None,'ci95':None}
    samples=rng(90,key).integers(0,len(a),size=(2000,len(a)))
    estimates=a[samples].mean(axis=1)
    return {'n':len(a),'mean':float(a.mean()),'ci95':np.quantile(estimates,[.025,.975]).tolist()}


def real_cycle(root):
    contract=source_contract(root);folder=root/'research/smart-engagement-2026-09/local_data'
    posts,_,digest=T.load(folder/'max_tail_panel_2026-09-28.jsonl.gz')
    if digest!=P.PANEL_SHA:raise ValueError('Frozen panel changed')
    accounts=[c['id'] for c in json.loads((folder/'max_tail_cohort_2026-09-28.json').read_text())]
    prepared,audit=I.prepare(posts)
    first=extract(prepared,I.START,I.SPLIT,accounts,source_verified=True)
    second=extract(prepared,I.SPLIT,I.END,accounts,source_verified=True)
    models={};results={};differences={k:[] for k in ('mae','nll')}
    for i,target in enumerate(sorted(accounts)):
        fitting,calibrating=P.partition(accounts,target)
        key=tuple(fitting)
        if key not in models:
            rows=[r for a in fitting for r in first[a]['rows']]
            models[key]={m:fit(rows,m) for m in MODES}
        pair=models[key];model=pair['conditional']
        assert target not in model['accounts'] and target not in calibrating
        cal=[score(first[a],model) for a in calibrating]
        test=score(second[target],model);prior=score(first[target],model)
        ranks={m:decision(test,cal,m) for m in METHODS}
        family=decision(test,cal,'joint',alpha=.05/len(accounts))
        errors={}
        rows=second[target]['rows']
        if rows:
            y=np.array([r['dr'] for r in rows])
            for m in MODES:
                mu=predict(pair[m],rows)
                errors[m]={'n':len(y),'mae':float(np.abs(y-mu).mean()),'nll':float(P.nll(y,mu,pair[m]['dispersion']).mean())}
            for metric in differences:differences[metric].append(errors['conditional'][metric]-errors['structural'][metric])
        results[target]={'case_name':T.CASES.get(target),'test':test,'first_week':prior,'ranks':ranks,
            'familywise':family,'fit_accounts':model['accounts'],'cal_accounts':calibrating,
            'reference_digest':P.model_digest(model),'errors':errors}
        if (i+1)%20==0:print(json.dumps({'H62_accounts':i+1}),flush=True)
    comparison={m:bootstrap(v,62+j) for j,(m,v) in enumerate(differences.items())}
    passed=all(x['ci95'] and x['ci95'][1]<0 for x in comparison.values())
    summary={'eligible_test':sum(v['test']['status']=='eligible' for v in results.values()),
        'rankable':{m:sum(v['ranks'][m]['status']=='diagnostic_only' for v in results.values()) for m in METHODS},
        'flags':{m:[a for a,v in results.items() if v['ranks'][m].get('flag')] for m in METHODS},
        'familywise_rankable':sum(v['familywise']['status']=='diagnostic_only' for v in results.values())}
    return {'source_contract':contract,'panel_sha256':digest,'preparation':audit,'accounts':results,
        'prediction_comparison':comparison,'conditional_prediction_gate':passed,'summary':summary,
        'models_fitted':len(models)*2,'future_validation':False,'production_admitted':False}


def synthetic_window(one,phase,world,mask,start,end):
    origin=T.dt('2026-08-31T00:00:00+03:00')
    uniform=rng(phase,world,3).random((31,P.NPOSTS));offset=rng(phase,world,4).integers(0,3,P.NPOSTS)
    posts,_=I.paths(one,origin,mask,uniform,offset)
    prepared,_=I.prepare(posts)
    return extract(prepared,origin+timedelta(days=start),origin+timedelta(days=end),source_verified=True)['target']


def contaminate(one):
    return {k:(2*v if k in ('r','early_r') else v.copy()) for k,v in one.items()}


def make_target(base,phase,world,family):
    return G.alter(base,0,family,rng(phase,world,2,FAMILIES.index(family)))


def simulation_cycle(train_n=300,cal_n=400,test_n=600):
    fit_rows={(mask,dirty):[] for mask in MASKS for dirty in (False,True)}
    for w in range(train_n):
        base=P.ordinary_world(rng(1,w,1));one=make_target(base,1,w,ORDINARY[w%len(ORDINARY)])
        for mask in MASKS:
            clean=synthetic_window(one,1,w,mask,0,10)
            dirty=synthetic_window(contaminate(one),1,w,mask,0,10) if w%10<3 else clean
            for changed,window in ((False,clean),(True,dirty)):
                fit_rows[mask,changed].extend(r|{'account':str(w)} for r in window['rows'])
        if (w+1)%100==0:print(json.dumps({'H63_fit_worlds':w+1}),flush=True)
    models={};fit_audit={}
    for key,rows in fit_rows.items():
        pair={m:fit(rows,m) for m in MODES};models[key]=pair['conditional']
        fit_audit[f'{key[0]}:{key[1]}']={m:{'digest':P.model_digest(v),'n':v['n'],'accounts':len(v['accounts']),
            'dispersion':v['dispersion'],'beta':v['beta'].tolist()} for m,v in pair.items()}
    del fit_rows
    cal=defaultdict(list)
    for w in range(cal_n):
        base=P.ordinary_world(rng(2,w,1));one=make_target(base,2,w,ORDINARY[w%len(ORDINARY)])
        for mask in MASKS:
            clean=synthetic_window(one,2,w,mask,10,17)
            dirty=synthetic_window(contaminate(one),2,w,mask,10,17) if w%10<3 else clean
            for regime,(fit_dirty,cal_dirty) in REGIMES.items():
                cal[mask,regime].append(score(dirty if cal_dirty else clean,models[mask,fit_dirty]))
        if (w+1)%100==0:print(json.dumps({'H63_cal_worlds':w+1}),flush=True)
    decisions=defaultdict(list)
    for w in range(test_n):
        base=P.ordinary_world(rng(3,w,1))
        for family in FAMILIES:
            one=make_target(base,3,w,family)
            for mask in MASKS:
                window=synthetic_window(one,3,w,mask,23,30)
                for regime,(fit_dirty,_) in REGIMES.items():
                    target=score(window,models[mask,fit_dirty])
                    for method in METHODS:
                        d=decision(target,cal[mask,regime],method)
                        decisions[mask,regime,family,method].append(bool(d['flag']) if d['status']=='diagnostic_only' else None)
        if (w+1)%50==0:print(json.dumps({'H63_test_worlds':w+1}),flush=True)
    records=[];gates={}
    for key,values in decisions.items():
        eligible=[v for v in values if v is not None];n=len(eligible);k=sum(eligible)
        records.append(dict(zip(('mask','regime','family','method'),key))|{'worlds':test_n,'eligible':n,'abstain':test_n-n,
            'flags':k,'rate':k/n if n else None,'wilson95':P.wilson(k,n) if n else None})
    lookup={(r['mask'],r['regime'],r['family'],r['method']):r for r in records}
    for mi,mask in enumerate(MASKS):
        for ri,regime in enumerate(REGIMES):
            errors={f:lookup[mask,regime,f,'joint']['wilson95'] for f in ORDINARY+STRESS}
            arrays={m:{f:decisions[mask,regime,f,m] for f in ('baseline','small_daily30')} for m in METHODS}
            common=[i for i in range(test_n) if all(arrays[m][f][i] is not None for m in METHODS for f in arrays[m])
                and not any(arrays[m]['baseline'][i] for m in METHODS)]
            delta=[int(arrays['joint']['small_daily30'][i])-int(arrays['volume']['small_daily30'][i]) for i in common]
            gain=bootstrap(delta,6300+mi*10+ri)
            ordinary_pass=all(ci and ci[1]<=.05 for ci in errors.values())
            gain_pass=bool(len(common)>=200 and gain['mean']>=.1 and gain['ci95'][0]>0)
            gates[f'{mask}:{regime}']={'ordinary_wilson95':errors,'ordinary_pass':ordinary_pass,
                'common_unflagged_baseline':len(common),'small_daily30_gain':gain,'gain_pass':gain_pass,
                'pass':bool(ordinary_pass and gain_pass)}
    cal_support={f'{mask}:{regime}':dict(Counter(v['support'] if v['status']=='eligible' else 'ineligible' for v in values))
        for (mask,regime),values in cal.items()}
    return {'train_worlds':train_n,'cal_worlds':cal_n,'test_worlds':test_n,'fit_models':fit_audit,
        'cal_support':cal_support,'records':records,'gates':gates,'all_gates_pass':all(g['pass'] for g in gates.values()),
        'target_excluded_by_construction':True,'new_period_validated':False,'production_admitted':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[3])
    ap.add_argument('--mode',choices=('real','simulation'),required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out={'provenance':provenance(args.root),'mode':args.mode}
    out[args.mode]=real_cycle(args.root) if args.mode=='real' else simulation_cycle()
    G.dump(out,args.output)
    print(json.dumps({'output':str(args.output),'sha256':P.sha(args.output)}),flush=True)


if __name__=='__main__':main()
