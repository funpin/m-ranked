"""H58-H60: lower bounds on observed counter growth, never a fraud score."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path

import numpy as np

import tail_generalization as G
P=G.P
T=P.tail
SEED=20269328
PROTOCOL_SHA="d60eabad8620b2fad715b33d79044ca03e80637496921475446636d3244b058b"
H61_PROTOCOL_SHA="4a4dd86039b63c1604490b1a9b327b8e5f6602993efe0d55bddedbfc7e3376fa"
START=T.dt("2026-09-14T00:00:00+03:00")
SPLIT=T.dt("2026-09-21T00:00:00+03:00")
END=T.dt("2026-09-28T00:00:00+03:00")
SCOPES={"week1":(START,SPLIT),"week2":(SPLIT,END),"whole":(START,END)}


def rng(*keys):return np.random.default_rng(np.random.SeedSequence([SEED,*keys]))


def provenance(root):
    doc=(root/"research/smart-engagement-2026-09/INTERVAL_EVIDENCE.md").read_text()
    value=doc.split("## Протокол H58–H60 до исходов\n",1)[1].split("## Результаты H58–H60\n",1)[0]
    digest=hashlib.sha256(value.encode()).hexdigest()
    if digest!=PROTOCOL_SHA:raise ValueError("Registered protocol changed")
    h61=hashlib.sha256(doc.split("## Протокол H61: семантика версий — после H59, до нового сравнения\n",1)[1].split("## Результаты H61\n",1)[0].encode()).hexdigest()
    if h61!=H61_PROTOCOL_SHA:raise ValueError("H61 protocol changed")
    return {"protocol_sha256":digest,"script_sha256":P.sha(__file__),"parent_sha256":P.sha(P.__file__),
            "h61_protocol_sha256":h61,
            "generalization_sha256":P.sha(G.__file__),"endpoint_parser_sha256":P.sha(T.__file__),
            "test_sha256":P.sha(root/"tests/test_interval_evidence_research.py"),"seed":SEED,
            "production_changed":False,"new_fraud_classifier":False}


def prospective_status(now,manifest):
    now=T.dt(now) if isinstance(now,str) else now
    if now.tzinfo is None or T.dt(manifest["earliest_assessment"])<T.dt(manifest["end_exclusive"]):
        raise ValueError("Timezone and complete holdout window required")
    if now<T.dt(manifest["start_inclusive"]):state="not_started"
    elif now<T.dt(manifest["earliest_assessment"]):state="immature"
    else:state="calendar_mature_requires_support_audit"
    return {"state":state,"observations_validated":False,"evaluation_permitted":False,
            "new_period_completed":False,"reason":"Clock alone cannot establish measurement/calibration support"}


def trusted(point,latest_version_verified=False,policy="zero_revision"):
    if policy not in ("zero_revision","latest_as_of_cutoff"):raise ValueError("Unknown revision policy")
    revision=point.get("correction_sequence") if point else None
    revision_ok=revision==0 if policy=="zero_revision" else (
        latest_version_verified and isinstance(revision,int) and not isinstance(revision,bool) and revision>=0)
    return bool(point and point.get("rq")=="exact" and point.get("vq")=="exact"
                and point.get("uncertain") is False and not point.get("synthetic",False)
                and revision_ok
                and all(isinstance(point.get(k),int) and not isinstance(point[k],bool) and point[k]>=0 for k in ("r","v")))


def normalize(points):
    """Bad/conflicting points remain as barriers; never filter before adjacency."""
    if any(not p.get("observed_at") for p in points):return [],{"post_missing_time":1}
    grouped=defaultdict(list)
    for p in points:grouped[T.dt(p["observed_at"])].append(p)
    out=[];audit=Counter()
    fields=("r","v","rq","vq","uncertain","correction_sequence")
    for at,group in sorted(grouped.items()):
        signatures={tuple(p.get(k) for k in fields)+(p.get("synthetic",False),) for p in group}
        audit["duplicate_points"]+=len(group)-1
        if len(signatures)>1:
            out.append({"at":at,"point":{"uncertain":True}});audit["conflicting_timestamps"]+=1
        else:out.append({"at":at,"point":group[0]})
    return out,dict(audit)


def prepare(posts):
    prepared=[];audit=Counter()
    for post in posts:
        meta=post["post"]
        if meta["is_repost"]:audit["reposts_excluded"]+=1;continue
        points,check=normalize(post.get("daily") or [])
        audit.update(check)
        prepared.append({"id":meta["id"],"account":meta["primary_account_id"],
                         "published":T.dt(meta["published_at"]),"points":points})
    return prepared,dict(audit)


def minimum_days(intervals):
    """Minimum calendar-day hitting set; witness dates are not observed dates."""
    windows=sorted((end.astimezone(T.MSK).date(),start.astimezone(T.MSK).date()) for start,end in intervals)
    selected=None;count=0
    for right,left in windows:
        if right<left:raise ValueError("Reversed interval")
        if selected is None or selected<left:selected=right;count+=1
    return count


def strict_keys(posts,clocks,stale):
    rows,_,_,_=T.intervals(posts,clocks,stale=stale)
    by_id={p["post"]["id"]:p for p in posts};keys=set()
    for row in rows:
        p=by_id[row["id"]];day=T.dt(row["day"])
        a=p["daily_by_day"][(day-timedelta(days=1)).date().isoformat()]
        b=p["daily_by_day"][row["day"]]
        keys.add((row["id"],T.dt(a["observed_at"]),T.dt(b["observed_at"])))
    return keys


def ledger(prepared,start,end,allowed=None,retain_edges=False,accounts=None,policy="zero_revision",latest_version_verified=False):
    result={};kept=[]
    def bucket():return {"possible_posts":0,"possible_hours":0.,"intervals":0,"hours":0.,
        "sum_positive_net_r":0,"sum_net_v":0,"zero_net_r_intervals":0,"positive_intervals":0,"intervals_with_nonzero_revision":0,
        "posts":set(),"positive_posts":set(),"positive_times":[],"bands":defaultdict(Counter),"excluded":Counter()}
    raw=defaultdict(bucket)
    for account in accounts or []:raw[account]
    for post in prepared:
        pub=post["published"];a=post["account"];b=raw[a]
        opportunity=max(0.,(min(pub+timedelta(days=14),end)-max(pub+timedelta(days=4),start)).total_seconds()/3600)
        if opportunity<=0:continue
        b["possible_posts"]+=1;b["possible_hours"]+=opportunity
        for left,right in zip(post["points"],post["points"][1:]):
            t0,t1=left["at"],right["at"];key=(post["id"],t0,t1)
            if t0<start or t1>=end:
                if t1>=start and t0<end:b["excluded"]["crosses_period_boundary"]+=1
                continue
            if t0<pub+timedelta(days=4) or t1>pub+timedelta(days=14):
                b["excluded"]["outside_actual_age_4_to_14"]+=1;continue
            if not trusted(left["point"],latest_version_verified,policy) or not trusted(right["point"],latest_version_verified,policy):
                b["excluded"]["untrusted_endpoint"]+=1;continue
            dr=right["point"]["r"]-left["point"]["r"];dv=right["point"]["v"]-left["point"]["v"]
            if dr<0 or dv<0:b["excluded"]["known_counter_decrease"]+=1;continue
            if allowed is not None and key not in allowed:b["excluded"]["not_in_strict_subset"]+=1;continue
            hours=(t1-t0).total_seconds()/3600
            if hours<=0:raise ValueError("Duplicate/reversed timestamps survived normalization")
            band="le30h" if hours<=30 else "30to72h" if hours<=72 else "gt72h"
            b["intervals"]+=1;b["hours"]+=hours;b["sum_positive_net_r"]+=dr;b["sum_net_v"]+=dv
            b["zero_net_r_intervals"]+=dr==0;b["positive_intervals"]+=dr>0;b["posts"].add(post["id"])
            b["intervals_with_nonzero_revision"]+=left["point"]["correction_sequence"]>0 or right["point"]["correction_sequence"]>0
            b["bands"][band].update({"intervals":1,"hours":hours,"net_r":dr,"positive_intervals":int(dr>0)})
            if dr>0:b["positive_posts"].add(post["id"]);b["positive_times"].append((t0,t1))
            if retain_edges:kept.append({"post":post["id"],"account":a,"start":t0,"end":t1,"dr":dr,"dv":dv,"hours":hours})
    for a,b in raw.items():
        lower=minimum_days(b.pop("positive_times"))
        b["observed_posts"]=len(b.pop("posts"));b["positive_posts"]=len(b["positive_posts"])
        b["minimum_growth_days"]=lower
        b["coverage_hours"]=b["hours"]/b["possible_hours"] if b["possible_hours"] else None
        b["status"]="unknown_no_trusted_interval" if not b["intervals"] else "observed_counter_growth" if lower else "no_observed_positive_net_change"
        b["not_a_normality_or_fraud_verdict"]=True
        b["bands"]={k:dict(v) for k,v in b["bands"].items()};b["excluded"]=dict(b["excluded"])
        result[a]=b
    return result,kept


def real_cycle(root,policy="zero_revision",latest_version_verified=False):
    folder=root/"research/smart-engagement-2026-09/local_data"
    posts,clocks,digest=T.load(folder/"max_tail_panel_2026-09-28.jsonl.gz")
    if digest!=P.PANEL_SHA:raise ValueError("Panel changed")
    prepared,audit=prepare(posts)
    accounts=[r["id"] for r in json.loads((folder/"max_tail_cohort_2026-09-28.json").read_text())]
    keys={"strict3":strict_keys(posts,clocks,3),"strict6":strict_keys(posts,clocks,6),"all_exact":None}
    report={"panel_sha256":digest,"revision_policy":policy,"latest_version_source_contract_verified":latest_version_verified,
            "input_posts":len(posts),"preparation_audit":audit,"scopes":{}}
    for name,(start,end) in SCOPES.items():
        records={m:ledger(prepared,start,end,allowed=k,accounts=accounts,policy=policy,latest_version_verified=latest_version_verified)[0] for m,k in keys.items()}
        totals={m:{"accounts_with_intervals":sum(r["intervals"]>0 for r in values.values()),
            "intervals":sum(r["intervals"] for r in values.values()),"net_r":sum(r["sum_positive_net_r"] for r in values.values()),
            "account_growth_day_lower_bounds_sum":sum(r["minimum_growth_days"] for r in values.values())} for m,values in records.items()}
        report["scopes"][name]={"start":start.isoformat(),"end_exclusive":end.isoformat(),"records":records,"totals":totals}
        named={T.CASES[a]:{m:values[a] for m,values in records.items()} for a in T.CASES if a in records["all_exact"]}
        print(json.dumps({"H59_scope":name,"policy":policy,"totals":totals,"named":{n:{m:{k:r[k] for k in ("intervals","positive_posts","sum_positive_net_r","minimum_growth_days","coverage_hours")} for m,r in ms.items()} for n,ms in named.items()}},ensure_ascii=False),flush=True)
    gap=folder/"missed_gap/series.jsonl"
    if gap.exists():
        raw=[json.loads(line) for line in gap.read_text().splitlines()];meta=raw[0]
        points=[{"observed_at":r["at"],"r":r["r"],"v":r["v"],"rq":r["rq"],"vq":r["vq"],
                 "uncertain":r["uncertain"],"synthetic":r["synthetic"],"correction_sequence":r["correction"]} for r in raw[1:] if "at" in r]
        post={"post":{"id":meta["id"],"primary_account_id":meta["account"],"published_at":meta["published_at"],"is_repost":meta["is_repost"]},"daily":points}
        pg,check=prepare([post]);values,edges=ledger(pg,START,END,retain_edges=True,policy=policy,latest_version_verified=latest_version_verified)
        selected=[e for e in edges if e["dr"]==316 and e["dv"]==1]
        report["previously_known_gap_case"]={"input_sha256":P.sha(gap),"post":meta["id"],"preparation":check,
            "matched_intervals":[e|{"start":e["start"].isoformat(),"end":e["end"].isoformat()} for e in selected],
            "no_early_fit_used":True,"not_new_validation_case":True}
    return report


def revision_cycle(root):
    folder=root/"research/smart-engagement-2026-09"
    old=json.loads((folder/"evidence/max_tail_provenance_2026-09-28.json").read_text())
    sql=folder/"sql/max_tail_endpoints.sql"
    if P.sha(sql)!=old["sha256"]["sql/max_tail_endpoints.sql"] or old["panel_uncompressed_sha256"]!=P.PANEL_SHA:
        raise ValueError("Panel/SQL contract not verified against prior provenance")
    gap_sql=folder/"local_data/missed_gap/query.sql"
    if P.sha(gap_sql)!="484e492f6f87074685571b36b00bf923d4c8862439affd455631b4b84373bc91":
        raise ValueError("Known gap extraction query changed")
    contract={"panel_sql_sha256":P.sha(sql),"prior_provenance_sha256":P.sha(folder/"evidence/max_tail_provenance_2026-09-28.json"),
        "gap_sql_sha256":P.sha(gap_sql),"source_view_sha256":P.sha(root/"db/migrations/0012_views.sql"),
        "trigger_source_sha256":P.sha(root/"db/migrations/0011_functions_base.sql"),
        "collector_source_sha256":P.sha(root/"collector_target/repository.py"),
        "panel_contract":"Latest sampling-bucket version available at frozen created_at cutoff; no synthetic rows",
        "gap_contract":"Active versions at original extraction, not replay of versions available at saved analysis time"}
    zero=real_cycle(root)
    latest=real_cycle(root,policy="latest_as_of_cutoff",latest_version_verified=True)
    differences={}
    for scope in SCOPES:
        before=zero["scopes"][scope]["records"]["all_exact"]
        after=latest["scopes"][scope]["records"]["all_exact"]
        differences[scope]={a:{k:after[a][k]-before[a][k] for k in ("intervals","sum_positive_net_r","minimum_growth_days","hours")}
                            for a in after}
    return {"source_contracts":contract,"zero_revision":zero,"latest_as_of_cutoff":latest,
            "all_accounts_difference":differences,"source_origin_classified":False,"production_changed":False}


def paths(one,origin,scheme,uniform,phase,with_decreases=False):
    r=one["early_r"].copy();v=one["early_v"].copy();records=[[] for _ in range(P.NPOSTS)]
    truths=[]
    for day in range(31):
        dr=np.zeros(P.NPOSTS,dtype=int);dv=np.zeros(P.NPOSTS,dtype=int)
        if day:
            ids=P.POST_INDEX[day-1];dr[ids]=one["r"][day-1];dv[ids]=one["v"][day-1]
            if with_decreases and day%5==0:dr[ids]=-np.minimum(r[ids],2)
            r+=dr;v+=dv
        at=origin+timedelta(days=day)
        for post in range(P.NPOSTS):
            published=origin+timedelta(days=post//2-13)
            if day and dr[post]>0 and published+timedelta(days=4)<at<=published+timedelta(days=14):
                truths.append({"post":str(post),"at":at,"dr":int(dr[post])})
            keep=scheme=="full" or (scheme=="independent" and uniform[day,post]<.6) or (
                scheme=="reaction_dependent" and uniform[day,post]<( .85 if dr[post]!=0 else .35)) or (
                scheme=="every_third" and day%3==phase[post])
            if keep and published+timedelta(days=4)<=at<=published+timedelta(days=14):
                records[post].append({"observed_at":at.isoformat(),"r":int(r[post]),"v":int(v[post]),
                    "rq":"exact","vq":"exact","uncertain":False,"correction_sequence":0})
    posts=[{"post":{"id":str(i),"primary_account_id":"target","published_at":(origin+timedelta(days=i//2-13)).isoformat(),"is_repost":False},"daily":points} for i,points in enumerate(records)]
    return posts,truths


def simulation_cycle(worlds=600):
    origin=T.dt("2026-08-31T00:00:00+03:00");end=origin+timedelta(days=30)
    families=("baseline","wide_sessions","persistent_r100","small_daily30","known_decreases")
    schemes=("full","independent","reaction_dependent","every_third")
    buckets=defaultdict(list);violations=Counter()
    for w in range(worlds):
        base=P.ordinary_world(rng(60,w,1))
        for j,family in enumerate(families):
            one=G.alter(base,0,"baseline" if family=="known_decreases" else family,rng(60,w,2,j))
            uniform=rng(60,w,3,j).random((31,P.NPOSTS));phase=rng(60,w,4,j).integers(0,3,P.NPOSTS)
            full=None
            for scheme in schemes:
                posts,truth=paths(one,origin,scheme,uniform,phase,with_decreases=family=="known_decreases")
                prepared,_=prepare(posts);record,_=ledger(prepared,origin,end)
                r=record["target"]
                actual=[t for t in truth if origin<t["at"]<end]
                true_days=len({t["at"].date() for t in actual});true_r=sum(t["dr"] for t in actual)
                observed=(r["minimum_growth_days"],r["sum_positive_net_r"])
                if observed[0]>true_days:violations["days_above_truth"]+=1
                if observed[1]>true_r:violations["net_r_above_true_positive_changes"]+=1
                if scheme=="full":full=observed
                if family!="known_decreases" and any(x>y for x,y in zip(observed,full)):violations["coarsening_increases_bound"]+=1
                buckets[(family,scheme)].append({"days":observed[0],"r":observed[1],"true_days":true_days,"true_r":true_r,
                    "full_days":full[0],"full_r":full[1],"unknown":r["intervals"]==0})
        if (w+1)%100==0:print(json.dumps({"H60_worlds":w+1}),flush=True)
    results=[]
    for (family,scheme),rows in sorted(buckets.items()):
        sums={k:sum(r[k] for r in rows) for k in ("days","r","true_days","true_r","full_days","full_r","unknown")}
        results.append({"family":family,"scheme":scheme,"worlds":worlds,**sums,
            "day_bound_retention":sums["days"]/sums["full_days"] if sums["full_days"] else None,
            "reaction_bound_retention":sums["r"]/sums["full_r"] if sums["full_r"] else None})
    return {"worlds":worlds,"records":results,"invariant_violations":dict(violations),
            "measurement_gate_pass":not violations,"not_detection_accuracy":True,"new_production_signal":False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[3])
    ap.add_argument("--mode",choices=("real","simulation","availability","revision"),required=True)
    ap.add_argument("--availability",type=Path)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    if args.availability and args.availability.resolve()==args.output.resolve():
        ap.error("Input audit and derived output must be different files")
    out={"provenance":provenance(args.root),"mode":args.mode}
    if args.mode=="real":out["real"]=real_cycle(args.root)
    elif args.mode=="simulation":out["simulation"]=simulation_cycle()
    elif args.mode=="revision":out["revision"]=revision_cycle(args.root)
    else:
        if not args.availability:ap.error("--availability required")
        raw=json.loads(args.availability.read_text())[0]
        prior=json.loads((args.root/"research/smart-engagement-2026-09/evidence/tail_generalization_2026-09-28.json").read_text())
        out["availability"]={"receipt_audit":raw,"input_sha256":P.sha(args.availability),
            "sql_sha256":hashlib.sha256(G.AVAILABILITY_SQL.encode()).hexdigest(),"manifest":prior["prospective"],
            "prospective_gate":prospective_status(raw["query_time"],prior["prospective"])}
    G.dump(out,args.output)
    print(json.dumps({"output":str(args.output),"sha256":P.sha(args.output)}),flush=True)


if __name__=="__main__":main()
