"""H54–H57: research-only scale/context checks; no production integration."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import uuid

import numpy as np
from scipy.optimize import minimize

import tail_generalization as G
import post_curve_similarity as C
P = G.P

SEED = 20269228
PROTOCOL_SHA = "eee7eda7a1761fac46c7acd7c3c78492be0e45c26f021a4c51f2cf8d20d62ac3"
CUTOFF = "2026-09-13 21:00:00+00"


def rng(*keys):
    return np.random.default_rng(np.random.SeedSequence([SEED, *keys]))


def paired_curves(root, stale=6):
    report = json.loads((root / "research/smart-engagement-2026-09/evidence/tail_generalization_2026-09-28.json").read_text())
    source = report["curves_real"]["real"]["tolerances"][str(stale)]["fixed_age_descriptive"]
    result = {}
    for a, record in source.items():
        if record["curves"] is None:
            continue
        result[a] = [p for p in record["curves"] if p["mature_days"] >= 7 and p["points"][0] is not None and p["points"][6] is not None
                     and all(p["points"][6][m] >= p["points"][0][m] for m in ("r", "v"))]
    return result


def metadata_sql(root):
    cohort = json.loads((root / "research/smart-engagement-2026-09/local_data/max_tail_cohort_2026-09-28.json").read_text())
    accounts = ",".join(f"('{uuid.UUID(c['id'])}'::uuid)" for c in cohort)
    return f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='20s'; SET LOCAL lock_timeout='1s';
WITH accounts(id) AS (VALUES {accounts})
SELECT jsonb_build_object('account',a.id,'subscriber_count',s.subscriber_count,
 'observed_at',s.observed_at,'created_at',s.created_at,'quality',s.subscriber_quality,
 'snapshot_id',s.id,'correction_sequence',s.correction_sequence)
FROM accounts a LEFT JOIN LATERAL (
 SELECT s.id,s.subscriber_count,s.observed_at,s.created_at,s.subscriber_quality,s.correction_sequence
 FROM ingest.account_metric_snapshot s
 WHERE s.platform_account_id=a.id AND s.observed_at>='2026-08-30 21:00:00+00'
 AND s.observed_at<'{CUTOFF}' AND s.created_at<'{CUTOFF}'
 AND s.subscriber_quality='exact' AND s.subscriber_count>0
 AND NOT EXISTS (SELECT 1 FROM ingest.account_metric_snapshot n
   WHERE n.platform_account_id=a.id AND n.supersedes_snapshot_id=s.id AND n.created_at<'{CUTOFF}')
 ORDER BY s.observed_at DESC,s.correction_sequence DESC,s.id DESC LIMIT 1
) s ON true ORDER BY a.id;
COMMIT;
"""


def public_sample(root):
    paired = paired_curves(root)
    chosen = {}
    for a in list(P.tail.CASES)[:4]:
        chosen[a] = sorted(paired[a], key=lambda p: hashlib.sha256(p["post"].encode()).digest())[:4]
    return chosen


def public_sql(root):
    ids = [p["post"] for values in public_sample(root).values() for p in values]
    values = ",".join(f"('{uuid.UUID(i)}'::uuid)" for i in ids)
    return f"""BEGIN READ ONLY;
SET LOCAL statement_timeout='20s'; SET LOCAL lock_timeout='1s';
WITH sample(id) AS (VALUES {values})
SELECT jsonb_build_object('post',p.id,'account',p.primary_account_id,'published_at',p.published_at,
 'type',p.publication_type,'public_url',i.public_url,'account_url',a.current_url)
FROM sample t JOIN ingest.publication p ON p.id=t.id
JOIN catalog.platform_account a ON a.id=p.primary_account_id
LEFT JOIN LATERAL (SELECT public_url FROM ingest.publication_identity i
 WHERE i.publication_id=p.id AND i.role='primary' ORDER BY i.id LIMIT 1) i ON true
ORDER BY p.primary_account_id,p.id;
COMMIT;
"""


def provenance(root):
    document=(root / "research/smart-engagement-2026-09/CONTEXT.md").read_text()
    actual=hashlib.sha256(document.split("## Протокол до исходов\n",1)[1].split("## Результаты\n",1)[0].encode()).hexdigest()
    if actual != PROTOCOL_SHA:
        raise ValueError("Protocol changed after fixation")
    return {"protocol_sha256": actual, "script_sha256": P.sha(__file__),
            "parent_sha256": P.sha(P.__file__), "generalization_sha256": P.sha(G.__file__),
            "curve_script_sha256": P.sha(C.__file__), "test_sha256": P.sha(root / "tests/test_tail_context.py"),
            "seed": SEED, "no_new_real_period": True, "platform": "max", "production_changed": False}


def load_subscribers(path):
    rows=json.loads(path.read_text())
    result={}
    for r in rows:
        if r["subscriber_count"] is None:
            continue
        if not (r["quality"] == "exact" and r["subscriber_count"] > 0 and
                P.tail.dt("2026-08-31T00:00:00+03:00") <= P.tail.dt(r["observed_at"]) < P.tail.dt("2026-09-14T00:00:00+03:00") and
                P.tail.dt(r["created_at"]) < P.tail.dt("2026-09-14T00:00:00+03:00")):
            raise ValueError("Invalid pre-fit subscriber observation")
        result[r["account"]]=r["subscriber_count"]
    return result


def design(rows, types, mode, subscribers, extra):
    x, offset=P.raw_design(rows,types,mode)
    if extra:
        x=np.column_stack((x,np.log([subscribers[r["account"]] for r in rows])))
    return x,offset


def fit(rows,mode,weights,subscribers,extra):
    types=sorted({r["type"] for r in rows})
    x,offset=design(rows,types,mode,subscribers,extra)
    center=np.average(x,axis=0,weights=weights)
    scale=np.sqrt(np.average((x-center)**2,axis=0,weights=weights))
    center[0],scale[0]=0,1
    scale=np.maximum(scale,1e-8);x=(x-center)/scale
    y=np.array([r["dr"] for r in rows])
    initial=np.zeros(x.shape[1]+1);initial[0]=np.log((weights@y+.5)/(weights@np.exp(offset)+.5))
    fitted=minimize(G.nb_objective,initial,args=(x,y,offset,weights),jac=True,method="L-BFGS-B",
                    bounds=[(None,None)]*x.shape[1]+[(-9,5)],options={"maxiter":700,"ftol":1e-10})
    if not fitted.success: raise RuntimeError(str(fitted.message))
    return {"mode":mode,"types":types,"center":center,"scale":scale,"beta":fitted.x[:-1],
            "dispersion":float(np.exp(fitted.x[-1])),"extra":extra,
            "fit_accounts":sorted({r["account"] for r in rows}),"fit_days":sorted({r["day"] for r in rows}),
            "raw_log_s_slope":float(fitted.x[-2]/scale[-1]) if extra else None}


def predict(model,rows,subscribers):
    x,offset=design(rows,model["types"],model["mode"],subscribers,model["extra"])
    return np.exp(np.clip(offset+((x-model["center"])/model["scale"])@model["beta"],-25,25))


def bootstrap(values,key,alpha=.05):
    values=np.asarray(values,float)
    if not len(values): return None
    means=values[rng(54,key).integers(0,len(values),(2000,len(values)))].mean(axis=1)
    return {"n":len(values),"mean":float(values.mean()),"interval":np.quantile(means,[alpha/2,1-alpha/2]).tolist()}


def real_cycle(root,metadata):
    data=root / "research/smart-engagement-2026-09/local_data"
    posts,clocks,digest=P.tail.load(data/"max_tail_panel_2026-09-28.jsonl.gz")
    assert digest==P.PANEL_SHA
    cohort=json.loads((data/"max_tail_cohort_2026-09-28.json").read_text())
    accounts=[c["id"] for c in cohort]
    subscribers=load_subscribers(metadata)
    context,context_audit=G.publication_context(posts,accounts)
    context={a:np.r_[v,np.log(subscribers[a])] for a,v in context.items() if a in subscribers}
    out={"panel_sha256":digest,"subscriber_sha256":P.sha(metadata),"accounts_with_subscribers":len(subscribers),
         "missing_subscriber_accounts":sorted(set(accounts)-set(subscribers)),"tolerances":{}}
    for stale in (3,6):
        rows,opp,_,_=P.tail.intervals(posts,clocks,stale=stale)
        usable=[r for r in rows if r["actual_start_age"]>=4 and r["q24"] is not None]
        daily=P.observations(rows,opp,accounts)
        first=defaultdict(list)
        for r in usable:
            if r["day"] in P.FIRST: first[r["account"]].append(r)
        result,cache={},{}
        for target in sorted(accounts):
            if target not in subscribers:
                result[target]={"status":"abstain","reason":"no_prior_subscribers"};continue
            selected=[d for d in daily[target] if d["day"] in P.SECOND and d["eligible"]]
            if len(selected)<3:
                result[target]={"status":"abstain","reason":"fewer_than_three_observed_days"};continue
            fitting,_=P.partition(accounts,target)
            fitting=[a for a in fitting if a in subscribers and first[a]]
            if len(fitting)<20:
                result[target]={"status":"abstain","reason":"fewer_than_twenty_fit_accounts"};continue
            local,support=G.context_weights(context,fitting,target)
            train=[r for a in fitting for r in first[a]]
            test=[r for d in selected for r in d["rows"]]
            y=np.array([r["dr"] for r in test])
            rec={"status":"eligible","test_days":len(selected),"test_intervals":len(test),
                 "fit_accounts":len(fitting),"local_effective_support":support["effective_accounts"],"models":{}}
            for mode in P.MODES:
                rec["models"][mode]={}
                for strategy in ("A","B","C"):
                    if strategy=="C" and support["effective_accounts"]<20:
                        rec["models"][mode][strategy]={"status":"abstain","reason":"effective_support_below_twenty"};continue
                    key=(tuple(fitting),mode,strategy,target if strategy=="C" else None)
                    if key not in cache:
                        weights=G.balanced_weights(train,local if strategy=="C" else dict.fromkeys(fitting,1.))
                        cache[key]=fit(train,mode,weights,subscribers,strategy!="A")
                    model=cache[key]
                    assert target not in model["fit_accounts"] and set(model["fit_days"])<=set(P.FIRST)
                    mu=predict(model,test,subscribers)
                    rec["models"][mode][strategy]={"status":"eligible","mae":float(np.abs(y-mu).mean()),
                        "nll":float(P.nll(y,mu,model["dispersion"]).mean()),"log_s_slope":model["raw_log_s_slope"],
                        "expected":float(mu.sum()),"observed":int(y.sum()),
                        "model_sha256":hashlib.sha256(json.dumps(G.plain(model),sort_keys=True).encode()).hexdigest()}
            result[target]=rec
        eligible=[r for r in result.values() if r["status"]=="eligible"]
        summary={}
        for mode in P.MODES:
            summary[mode]={}
            for left,right in (("B","A"),("C","B")):
                common=[r for r in eligible if all(r["models"][mode][s]["status"]=="eligible" for s in (left,right))]
                summary[mode][left+"_minus_"+right]={m:bootstrap([r["models"][mode][left][m]-r["models"][mode][right][m] for r in common],stale) for m in ("mae","nll")}
        passed=bool(eligible) and all(summary[m]["B_minus_A"][k]["interval"][1]<0 for m in P.MODES for k in ("mae","nll"))
        out["tolerances"][str(stale)]={"eligible_accounts":len(eligible),"accounts":result,"summary":summary,"primary_style_gate":passed}
        print(json.dumps({"H54_stale":stale,"eligible":len(eligible),"summary":summary,"gate":passed}),flush=True)
    return out


def statistics(values):
    x=np.asarray(values,float)
    if not len(x) or x.mean()<=0: return {"n":len(x),"status":"no_positive_mean"}
    mean=float(x.mean());variance=float(x.var())
    return {"n":len(x),"mean":mean,"variance":variance,"cv":variance**.5/mean,
            "fano":variance/mean,"H":(variance-mean)/mean**2}


def blocks(curves,metric):
    groups=defaultdict(list)
    for p in curves:
        date=P.tail.dt(p["published_at"]).astimezone(P.tail.MSK).date().isoformat()
        y=p["points"][6]["r"]-(p["points"][0]["r"] if metric=="late" else 0)
        groups[date].append(y)
    return dict(groups)


def paired_resample_h(left,right,key):
    """One draw of calendar days for both accounts preserves common shocks."""
    random=rng(55,key)
    dates=sorted(set(left)|set(right))
    picks=random.integers(0,len(dates),(2000,len(dates)))
    return np.array([statistics([y for i in ix for y in left.get(dates[i],[])]).get("H",np.nan)
                     -statistics([y for i in ix for y in right.get(dates[i],[])]).get("H",np.nan) for ix in picks])


def compare(left,right,key,minimum=12,days=4,alpha=.0125):
    lb,rb=blocks(left,"r7"),blocks(right,"r7")
    support={"left_posts":len(left),"right_posts":len(right),"left_days":len(lb),"right_days":len(rb)}
    if min(len(left),len(right))<minimum or min(len(lb),len(rb))<days:
        return support|{"status":"abstain","reason":"insufficient_posts_or_publication_days"}
    diff=paired_resample_h(lb,rb,key)
    valid=np.isfinite(diff)
    if valid.sum()<1900:
        return support|{"status":"abstain","reason":"too_many_zero_mean_resamples"}
    observed=statistics([y for g in lb.values() for y in g])["H"]-statistics([y for g in rb.values() for y in g])["H"]
    interval=np.quantile(diff[valid],[alpha/2,1-alpha/2]).tolist()
    return support|{"status":"descriptive_only","H_difference":observed,"interval":interval,
                    "confidence":1-alpha,"left_less_heterogeneous":interval[1]<0}


def dispersion_cycle(root):
    data=root / "research/smart-engagement-2026-09/local_data"
    posts,_,_=P.tail.load(data/"max_tail_panel_2026-09-28.jsonl.gz")
    result={}
    for stale in (3,6):
        # fixed_horizons retains individual curves only for the five named cases;
        # regenerate the same point selection for all accounts without new reads.
        original=C.P.tail.CASES
        try:
            C.P.tail.CASES={p["post"]["primary_account_id"]:"" for p in posts}
            fixed=C.fixed_horizons(posts,stale)
        finally:
            C.P.tail.CASES=original
        paired={a:[p for p in r["curves"] if p["mature_days"]>=7 and p["points"][0] is not None and p["points"][6] is not None
                   and all(p["points"][6][m]>=p["points"][0][m] for m in ("r","v"))] for a,r in fixed.items()}
        profiles={}
        for a,curves in paired.items():
            profiles[a]={"name":P.tail.CASES.get(a),"posts":len(curves),"publication_days":len(blocks(curves,"r7")),
                         "r7":statistics([p["points"][6]["r"] for p in curves]),
                         "late":statistics([p["points"][6]["r"]-p["points"][0]["r"] for p in curves])}
        comparisons={}
        cases=list(P.tail.CASES)
        for i,left in enumerate(cases[2:4]):
            for j,right in enumerate(cases[:2]):
                key=f"{P.tail.CASES[left]} vs {P.tail.CASES[right]}"
                comparisons[key]={"all":compare(paired.get(left,[]),paired.get(right,[]),stale*10+i*2+j)}
                for kind in ("album","photo"):
                    comparisons[key][kind]=compare([p for p in paired.get(left,[]) if p["type"]==kind],
                        [p for p in paired.get(right,[]) if p["type"]==kind],stale*100+i*2+j,minimum=8,days=3,alpha=.05)
        result[str(stale)]={"accounts":profiles,"comparisons":comparisons,
            "eligible_accounts":sum(r["posts"]>=12 and r["publication_days"]>=4 for r in profiles.values())}
        print(json.dumps({"H55_stale":stale,"comparisons":comparisons},ensure_ascii=False),flush=True)
    return result


ORDINARY=("baseline","shallow_sessions","wide_sessions","high_engagement","campaign",
          "regular_reader","audience_growth","vk_recommendation")
INJECTIONS=("persistent_r100","early_r100","preserve_er100","small_daily10","small_daily30","test_only_r100")


def simulation_world(world):
    # Replay the frozen generator's first draw ONLY to generate observable S.
    # The detector is never given this latent size; P.ordinary_world is unchanged.
    size=rng(57,world,1).lognormal(-.55**2/2,.55,size=61)
    return P.ordinary_world(rng(57,world,1)),np.maximum(1,rng(57,world,2).poisson(800*size))


def subscriber_reference(data,subscribers):
    old=P.sim_reference(data)
    reference={m:old[m] for m in P.MODES}
    logs=np.log(subscribers[P.FIT]);center=float(logs.mean());x=logs-center
    y=data["r"][P.FIT,:10].sum(axis=(1,2))
    exposure={"structural":np.full(30,200.),
              "conditional":P.conditional_offset(data)[P.FIT,:10].sum(axis=(1,2))}
    model={"center":center,"modes":{}}
    for mode in P.MODES:
        response=np.log((y+.5)/(exposure[mode]+.5))
        slope=float(x@(response-response.mean())/(x@x+10))
        model["modes"][mode]={"slope":slope,"normalizer":float(np.exp(slope*x).mean())}
    return reference,model


def scaled_reference(reference,model,subscriber_count):
    if subscriber_count<=0: raise ValueError("S must be observed and positive")
    return {m:reference[m]*np.exp(model["modes"][m]["slope"]*(np.log(subscriber_count)-model["center"]))
            /model["modes"][m]["normalizer"] for m in P.MODES}


def calibrate(data,subscribers,reference,model):
    scores={"old":[],"subscriber":[]}
    for a in P.CAL:
        one={k:v[a] for k,v in data.items()}
        for method,ref in (("old",reference),("subscriber",scaled_reference(reference,model,subscribers[a]))):
            scores[method].append(P.sim_account_scores(one,ref,10)["independent_joint"])
    return {k:np.array(v) for k,v in scores.items()}


def decide(one,subscriber_count,reference,model,calibration):
    flags={}
    for method,ref in (("old",reference),("subscriber",scaled_reference(reference,model,subscriber_count))):
        score=P.sim_account_scores(one,ref,20)["independent_joint"]
        cal=calibration[method]
        flags[method]=bool((1+np.sum(cal>=score))/(len(cal)+1)<=.05)
    return flags


def rate(k,n):
    return {"flags":int(k),"n":int(n),"rate":float(k/n) if n else None,"wilson95":P.wilson(k,n)}


def simulation_cycle(worlds=600):
    scenarios=[(s,f) for s in ORDINARY for f in (1,2)]+[(s,1) for s in INJECTIONS]+[
        (s,f) for s in INJECTIONS[:3] for f in (2,4)]
    buckets=defaultdict(lambda:{"flags":Counter(),"new_flags":Counter(),"common":0,"n":0,"r_added":0,"r_before":0,"v_added":0})
    coefficients=defaultdict(list)
    families=P.SIMULATION_SPEC["enriched_peer_families"]
    for w in range(worlds):
        base,subscribers=simulation_world(w)
        peers=P.clone(base)
        for a in range(1,61):
            P.install(peers,a,G.alter(base,a,families[(a-1)%6],rng(57,w,3,a)))
        targets={s:G.alter(base,0,s,rng(57,w,4,j)) for j,s in enumerate(ORDINARY+INJECTIONS)}
        for fraction in (0,.3):
            data=P.clone(peers);observed_s=subscribers.copy()
            selected=P.FIT[:9] if fraction else []
            for a in selected:
                P.install(data,a,G.alter(peers,a,"early_r100",rng(57,w,5,int(a))))
                observed_s[a]*=2
            reference,model=subscriber_reference(data,observed_s)
            calibration=calibrate(data,observed_s,reference,model)
            for mode in P.MODES:coefficients[f"{fraction}:{mode}"].append(model["modes"][mode]["slope"])
            baseline=decide(targets["baseline"],observed_s[0],reference,model,calibration)
            common=not any(baseline.values())
            for scenario,factor in scenarios:
                one=targets[scenario]
                flags=decide(one,observed_s[0]*factor,reference,model,calibration)
                b=buckets[(fraction,scenario,factor)];b["n"]+=1;b["common"]+=common
                b["flags"].update(k for k,yes in flags.items() if yes)
                b["new_flags"].update(k for k,yes in flags.items() if yes and common)
                b["r_added"]+=int(one["r"].sum()-base["r"][0].sum())
                b["r_before"]+=int(base["r"][0].sum())
                b["v_added"]+=int(one["v"].sum()-base["v"][0].sum())
        if (w+1)%100==0: print(json.dumps({"H57_worlds":w+1}),flush=True)
    records=[]
    for (fraction,scenario,factor),b in sorted(buckets.items()):
        records.append({"fit_contamination":fraction,"scenario":scenario,"subscriber_factor":factor,
            "ordinary_by_construction":scenario in ORDINARY,"abstained":0,
            "added_r_fraction":b["r_added"]/b["r_before"],"total_added_v":b["v_added"],
            "rates":{k:rate(b["flags"][k],b["n"]) for k in ("old","subscriber")},
            "common_baseline_unflagged":b["common"],
            "new_flags":{k:rate(b["new_flags"][k],b["common"]) for k in ("old","subscriber")}})
    gates={m:all(r["rates"][m]["wilson95"][1]<=.05 for r in records if r["ordinary_by_construction"])
           for m in ("old","subscriber")}
    return {"worlds":worlds,"fully_observed_only":True,"records":records,"ordinary_error_gate":gates,
            "slopes":{k:{"mean":float(np.mean(v)),"quantiles":np.quantile(v,[.05,.5,.95]).tolist()} for k,v in coefficients.items()},
            "source_model":P.SIMULATION_SPEC,"not_real_fraud_accuracy":True}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[3])
    ap.add_argument("--mode",choices=("metadata-sql","public-sql","real","dispersion","simulation"),required=True)
    ap.add_argument("--metadata",type=Path)
    ap.add_argument("--output",type=Path)
    a=ap.parse_args()
    if a.mode.endswith("-sql"):
        print(metadata_sql(a.root) if a.mode=="metadata-sql" else public_sql(a.root));return
    if not a.output: ap.error("--output required")
    out={"provenance":provenance(a.root),"mode":a.mode}
    if a.mode=="real":
        if not a.metadata: ap.error("--metadata required")
        out["real"]=real_cycle(a.root,a.metadata)
    elif a.mode=="dispersion":out["dispersion"]=dispersion_cycle(a.root)
    else:out["simulation"]=simulation_cycle()
    G.dump(out,a.output)
    print(json.dumps({"output":str(a.output),"sha256":P.sha(a.output)}),flush=True)


if __name__=="__main__":main()
