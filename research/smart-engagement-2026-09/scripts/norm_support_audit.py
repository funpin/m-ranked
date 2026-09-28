"""Operational replay of norm-support guards on the existing V/R panel.

Not a fraud-accuracy test or a reproduction of saved production scores.
Streaming collection retains compact sufficient statistics, not full histories.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID


def rows(path):
    with gzip.open(path, "rt") as stream:
        for line in stream:
            yield json.loads(line)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.repo.resolve()))
    from anomaly_analysis.v2.domain import Metric, PostSeries
    from anomaly_analysis.v2.series import CollectionCadence, prepare
    from anomaly_analysis.v2.norms import NORM_MODEL_VERSION, _Samples, _collect, _account_norm, combine, norm_to_payload
    from anomaly_analysis.norms_job import absolutely_clean
    from anomaly_analysis.v2.levels import assess
    from anomaly_analysis.v2.mature_reference import bundled_reference
    cadence = CollectionCadence()
    freeze = datetime(2026, 9, 20, tzinfo=timezone.utc)
    panel_end = datetime(2026, 9, 27, 17, tzinfo=timezone.utc)
    model = bundled_reference()
    def series(row, until):
        published = datetime.fromisoformat(row["published_at"])
        points = sorted((p for p in row["points"] or []
                         if datetime.fromisoformat(p["observed_at"]) < until), key=lambda p: p["observed_at"])
        return PostSeries(UUID(row["id"]), UUID(row["primary_account_id"]), row["platform"], published, False,
            tuple(datetime.fromisoformat(p["observed_at"]) for p in points),
            {m:tuple(p[k] for p in points) for m,k in ((Metric.VIEWS,"v"),(Metric.REACTIONS,"r"))},
            qualities={m:tuple(p[k+"q"] for p in points) for m,k in ((Metric.VIEWS,"v"),(Metric.REACTIONS,"r"))},
            interval_uncertain=tuple(p["uncertain"] for p in points))
    norm_source_sha256 = hashlib.sha256((args.repo/"anomaly_analysis/v2/norms.py").read_bytes()).hexdigest()
    stats = defaultdict(_Samples)
    selection = defaultdict(Counter)
    for index,row in enumerate(rows(args.panel)):
        if not "2026-09-06" <= row["published_at"][:10] < "2026-09-17":
            continue
        subject = series(row,freeze)
        platform = row["platform"]
        selection[platform]["catalog"] += 1
        if not subject.observed_at:
            selection[platform]["empty"] += 1
            continue
        p = prepare(subject,freeze,cadence)
        if not absolutely_clean(p):
            selection[platform]["absolute_signal"] += 1
            continue
        selection[platform]["accepted_rows"] += 1
        selection[platform]["no_precise_metrics"] += int(not p.metrics)
        one = _collect([p],frozenset(),30*86400)
        selection[platform]["contributed_posts"] += one.posts
        total = stats[(platform,subject.account_id)]
        total.posts += one.posts
        for name in ("rate_hours","rate_logs","shares","ervs"):
            for key,values in getattr(one,name).items():
                getattr(total,name).setdefault(key,[]).extend(values)
        for key,contributors in one.contributors.items():
            if contributors:
                total.contributors.setdefault(key,set()).add(index)
    norms = {p:combine(p,{a:_account_norm(p,a,s) for (platform,a),s in stats.items() if platform==p})
             for p in ("max","telegram","vk","rutube")}
    output = {"norm_model":NORM_MODEL_VERSION,
              "scope":"existing non-repost V/R panel; no saved-level filtering, siblings, subscribers or C/S qualities; not live scores or fraud labels",
              "fit_publications":["2026-09-06","2026-09-17"],"fit_observed_before":freeze.isoformat(),
              "norm_source_sha256":norm_source_sha256,
              "selection":dict(selection),"norms":{},"replay":{},"post_results":{}}
    for platform,n in norms.items():
        output["norms"][platform]={"platform":norm_to_payload(n.platform),
                                   "accounts":len(n.accounts),
                                   "account_posts":sum(x.posts for x in n.accounts.values())}
    for row in rows(args.panel):
        published=datetime.fromisoformat(row["published_at"])
        moment=published+timedelta(hours=72)
        if published<freeze or moment>panel_end:
            continue
        subject=series(row,moment+timedelta(microseconds=1))
        if not subject.observed_at:
            continue
        before=assess(subject,norms=norms[subject.platform],analyzed_at=moment,cadence=cadence)
        after=assess(subject,norms=norms[subject.platform],analyzed_at=moment,cadence=cadence,reference=model)
        assert after.level<=max(1,before.level)
        output["post_results"][row["id"]]={"platform":subject.platform,"without_reference":int(before.level),
            "with_reference":int(after.level),"patterns":sorted({x.pattern for x in after.signs}),
            "quality":list(after.quality.codes)}
    for platform in norms:
        results=[r for r in output["post_results"].values() if r["platform"]==platform]
        output["replay"][platform]={"posts":len(results),"levels":dict(Counter(str(r["with_reference"]) for r in results)),
            "reference_transitions":dict(Counter(f'{r["without_reference"]}->{r["with_reference"]}' for r in results)),
            "patterns":dict(Counter(str(p) for r in results for p in r["patterns"]))}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    print(json.dumps({k:output[k] for k in ("norm_model","selection","replay")},ensure_ascii=False))


if __name__ == "__main__":
    main()
