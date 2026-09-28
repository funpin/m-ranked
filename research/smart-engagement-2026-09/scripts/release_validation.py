"""H36–H38 frozen endpoint release validation; see ../RELEASE.md.

No production mutation. The input is the compact read-only export selected
before fresh outcomes. No anomaly label is used to filter fit/calibration.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
from uuid import UUID

import numpy as np


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+"\n")


def reason(row):
    if row['known_decrease']:
        return 'known_decrease'
    if any(p['observed_at'] is None for p in row['points']):
        return 'missing_window'
    if any(p[m] is None or p[m+'q'] != 'exact' or p['uncertain'] is not False
           for p in row['points'] for m in ('v','r')):
        return 'nonexact_endpoint'
    return 'eligible'


def fit_reference(rows):
    counts=Counter(r['primary_account_id'] for r in rows if r['fold']=='fit' and reason(r)=='eligible')
    accounts=sorted(a for a,n in counts.items() if n>=5)
    good=[r for r in rows if reason(r)=='eligible' and r['primary_account_id'] in accounts]
    train=[r for r in good if r['fold']=='fit']
    cal=[r for r in good if r['fold']=='cal']
    if min(len(train),len(cal))<100:
        raise ValueError(f'insufficient fit/calibration: {len(train)}/{len(cal)}')
    def matrix(records, k, center, sd):
        cols=[np.ones(len(records))]
        if k<2:
            cols.append((np.log1p([r['points'][0]['vr'[k%2]] for r in records])-center)/sd)
        cols.extend(np.array([r['primary_account_id']==a for r in records],float) for a in accounts)
        return np.column_stack(cols)
    components=[]; scores=[]
    for k in range(4):
        m='vr'[k%2]
        early=np.log1p([r['points'][0][m] for r in train])
        center=float(early.mean());sd=max(float(early.std()),1e-8)
        x=matrix(train,k,center,sd); y=np.log1p([r['points'][1][m] for r in train])
        penalty=10*np.eye(x.shape[1]);penalty[0,0]=0
        beta=np.linalg.solve(x.T@x+penalty,x.T@y)
        residual=y-x@beta
        scale=max(float(np.quantile(residual,.75)-np.quantile(residual,.25)),.05)
        prediction=matrix(cal,k,center,sd)@beta
        scores.append((np.log1p([r['points'][1][m] for r in cal])-prediction)/scale)
        offset=2 if k<2 else 1
        components.append({'conditional':k<2,'metric':('views','reactions')[k%2],
                           'intercept':float(beta[0]),'slope':float(beta[1]) if k<2 else 0.,
                           'center':center,'sd':sd,'scale':scale,
                           'effects':{a:float(beta[i+offset]) for i,a in enumerate(accounts)}})
    score=np.maximum(0,np.array(scores).max(axis=0))
    cutoff=float(np.sort(score)[math.ceil((len(cal)+1)*.95)-1])
    artifact={'schema_version':'1.0.0','reference_version':'max-2026-09-v1','platform':'max',
              'fit_start':'2026-09-06T00:00:00+00:00','calibration_end':'2026-09-17T00:00:00+00:00',
              'available_at':'2026-09-20T00:00:00+00:00','expires_at':'2026-10-18T00:00:00+00:00',
              'fit_count':len(train),'calibration_count':len(cal),
              'account_counts':{a:counts[a] for a in accounts},'cutoff':cutoff,'components':components}
    return artifact


def to_series(row, dose=0., kind='late'):
    from anomaly_analysis.v2.domain import Metric, PostSeries
    points=row['points']
    # The SQL separately audited all known exact decreases before 72h.
    # Two endpoints suffice for this model; full-series v2 comparison is separate.
    values={m:tuple(p[k]+round(p[k]*dose) if dose and (i==1 or kind=='early') else p[k]
                    for i,p in enumerate(points)) for m,k in ((Metric.VIEWS,'v'),(Metric.REACTIONS,'r'))}
    return PostSeries(UUID(row['id']),UUID(row['primary_account_id']),'max',
        datetime.fromisoformat(row['published_at']),False,
        tuple(datetime.fromisoformat(p['observed_at']) for p in points),values,
        qualities={m:tuple(p[k+'q'] for p in points) for m,k in ((Metric.VIEWS,'v'),(Metric.REACTIONS,'r'))},
        interval_uncertain=tuple(p['uncertain'] for p in points))


def rate(flags, records):
    flags=np.asarray(flags,dtype=float)
    if not len(flags):return {'n':0,'hits':0,'fraction':None,'account_bootstrap95':None}
    groups=sorted({r['primary_account_id'] for r in records})
    out={'n':len(flags),'hits':int(flags.sum()),'fraction':float(flags.mean()),'accounts':len(groups)}
    out['account_bootstrap95']=None
    if len(groups)>1 and not np.all(flags==flags[0]):
        sums=np.array([flags[[r['primary_account_id']==a for r in records]].sum() for a in groups])
        ns=np.array([sum(r['primary_account_id']==a for r in records) for a in groups])
        draws=np.random.default_rng(20264236).integers(0,len(groups),(2000,len(groups)))
        boot=sums[draws].sum(axis=1)/ns[draws].sum(axis=1)
        out['account_bootstrap95']=list(map(float,np.quantile(boot,[.025,.975])))
    return out


def evaluate(rows, artifact):
    from anomaly_analysis.v2.mature_reference import MatureReference
    model=MatureReference.from_payload(artifact)
    out={}
    for fold in ('fit','cal','reused','fresh'):
        catalog=[r for r in rows if r['fold']==fold]
        reasons=Counter();records=[]
        for r in catalog:
            code=reason(r)
            if code=='eligible' and r['primary_account_id'] not in artifact['account_counts']:
                code='insufficient_account_history'
            reasons[code]+=1
            if code=='eligible':records.append(r)
        result={'catalog':len(catalog),'coverage':dict(reasons)};out[fold]=result
        if fold in ('fit','cal'):continue
        signs=[]
        for row in records:
            series=to_series(row)
            signs.append(model.detect(series,series.published_at+timedelta(hours=72)))
        flags=[bool(s) for s in signs]
        result['observed_flags']=rate(flags,records)
        result['patterns']=dict(Counter(str(s.pattern) for ss in signs for s in ss))
        result['accounts']=[{'account_id':a,**rate([f for f,r in zip(flags,records) if r['primary_account_id']==a],
                      [r for r in records if r['primary_account_id']==a])}
                      for a in sorted({r['primary_account_id'] for r in records})]
        result['injections']={}
        clear=[r for r,f in zip(records,flags) if not f]
        for kind in ('early','late'):
            for dose in (.1,.3,1.):
                changed=[]
                for row in clear:
                    s=to_series(row,dose,kind)
                    changed.append(bool(model.detect(s,s.published_at+timedelta(hours=72))))
                result['injections'][f'{kind}:{dose}']=rate(changed,clear)
    return out


def contamination(rows, artifact):
    from copy import deepcopy
    from anomaly_analysis.v2.mature_reference import MatureReference
    accounts=sorted(artifact['account_counts'],key=lambda a:hashlib.sha256(a.encode()).hexdigest())
    targeted=set(accounts[:len(accounts)//3])
    baseline=MatureReference.from_payload(artifact)
    clear=[]
    for row in rows:
        if row['fold']!='reused' or reason(row)!='eligible' or row['primary_account_id'] not in targeted:
            continue
        series=to_series(row)
        if not baseline.detect(series,series.published_at+timedelta(hours=72)):clear.append(row)
    result={'target_accounts':len(targeted),'clear_target_posts':len(clear),'scenarios':{}}
    for dose in (.1,.3,1.):
        for phase in ('none','fit','cal','fit_and_cal'):
            changed=deepcopy(rows)
            for row in changed:
                if (row['primary_account_id'] in targeted and reason(row)=='eligible'
                        and row['fold'] in ({'fit','cal'} if phase=='fit_and_cal' else {phase})):
                    for point in row['points']:
                        for m in ('v','r'):point[m]+=round(point[m]*dose)
            candidate=fit_reference(changed)
            model=MatureReference.from_payload(candidate);flags=[]
            for row in clear:
                series=to_series(row,dose,'early')
                flags.append(bool(model.detect(series,series.published_at+timedelta(hours=72))))
            result['scenarios'][f'{dose}:{phase}']={'cutoff':candidate['cutoff'],'new_flags':rate(flags,clear)}
    return result


def archive_replay(path, rows, artifact):
    from anomaly_analysis.v2.domain import Metric, PostSeries
    from anomaly_analysis.v2.levels import assess
    from anomaly_analysis.v2.mature_reference import MatureReference, endpoints
    model=MatureReference.from_payload(artifact)
    target={r['id']:r for r in rows if r['fold']=='reused' and reason(r)=='eligible'
            and r['primary_account_id'] in artifact['account_counts']}
    reasons=Counter();changes=Counter();patterns=Counter();examples=[];seen=set()
    import time
    timings=[];reference_timings=[]
    with gzip.open(path,'rt') as stream:
        for line in stream:
            raw=json.loads(line);rid=raw['id']
            if rid not in target:continue
            seen.add(rid);row=target[rid];published=datetime.fromisoformat(raw['published_at'])
            points=sorted((p for p in raw['points'] or [] if 0<=p['age_seconds']<=72*3600),key=lambda p:p['observed_at'])
            subject=PostSeries(UUID(rid),UUID(raw['primary_account_id']),'max',published,False,
                tuple(datetime.fromisoformat(p['observed_at']) for p in points),
                {m:tuple(p[k] for p in points) for m,k in ((Metric.VIEWS,'v'),(Metric.REACTIONS,'r'))},
                qualities={m:tuple(p[k+'q'] for p in points) for m,k in ((Metric.VIEWS,'v'),(Metric.REACTIONS,'r'))},
                interval_uncertain=tuple(p['uncertain'] for p in points))
            moment=published+timedelta(hours=72);ep,code=endpoints(subject,moment)
            if ep is None:reasons[code]+=1;continue
            target_ep=to_series(row)
            wanted,_=endpoints(target_ep,moment)
            if ep!=wanted:reasons['archive_endpoint_changed']+=1;continue
            reasons['eligible']+=1
            # Isolate the new reference on identical full rows. No platform
            # norm/sibling export is present: this is NOT a replay of live v2.
            before=assess(subject,analyzed_at=moment)
            start=time.perf_counter();after=assess(subject,analyzed_at=moment,reference=model)
            timings.append((time.perf_counter()-start)*1000)
            start=time.perf_counter();new=model.detect(subject,moment)
            reference_timings.append((time.perf_counter()-start)*1000)
            changes[f'{int(before.level)}->{int(after.level)}']+=1
            patterns.update(str(s.pattern) for s in new)
            assert {s.pattern for s in new}<={s.pattern for s in after.signs}
            assert int(after.level)<=max(1,int(before.level))
            if new:examples.append({'publication_id':rid,'old_level_without_norm':int(before.level),
                'new_level_without_norm':int(after.level),'new_patterns':[s.pattern for s in new]})
    reasons['not_in_archive']=len(target)-len(seen)
    return {'scope':'same_full_series_quality_fixed_v2_without_norms_or_sibling_context_not_live_scores',
            'coverage':dict(reasons),'level_transitions':dict(changes),'new_patterns':dict(patterns),
            'examples':examples,'runtime_ms':{'n':len(timings),'assess_p95':float(np.quantile(timings,.95)) if timings else None,
                  'new_reference_p95':float(np.quantile(reference_timings,.95)) if timings else None}}


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True)
    p.add_argument('--repo',type=Path,required=True);p.add_argument('--artifact',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--panel',type=Path);args=p.parse_args()
    sys.path.insert(0,str(args.repo))
    raw=gzip.decompress(args.input.read_bytes())
    rows=[json.loads(line) for line in raw.splitlines() if line]
    artifact=fit_reference(rows)
    artifact['input_sha256']=hashlib.sha256(raw).hexdigest()
    dump(args.artifact,artifact)
    result={'input_sha256':artifact['input_sha256'],'model':{'version':artifact['reference_version'],
        'fit':artifact['fit_count'],'calibration':artifact['calibration_count'],
        'accounts':len(artifact['account_counts']),'cutoff':artifact['cutoff']},
        'evaluation':evaluate(rows,artifact), 'contamination':contamination(rows,artifact),
        'archive_replay':archive_replay(args.panel,rows,artifact) if args.panel else None,
        'limitations':['unlabeled_reference_not_fraud_precision','reused_control_not_independent',
                      'fresh_posts_clustered_small_window','counterfactual_not_real_manipulation_labels']}
    dump(args.output,result)
    print(json.dumps({'model':result['model'],'evaluation':{k:{kk:vv for kk,vv in v.items() if kk!='accounts'}
                                      for k,v in result['evaluation'].items()}},ensure_ascii=False))


if __name__=='__main__':main()
