"""Run one code root over posts and dump level + sign intervals. usage: dump_signs.py ROOT OUT.json files..."""
import sys, json, os
root, out_path, files = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, root); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import local_run as lr
out = {}
for f in files:
    for name, e in json.load(open(f)).items():
        if "points" not in e: continue
        platform = e["meta"].get("platform") or ("telegram" if (e["meta"].get("externalId") or "").startswith("m:") else "vk")
        v = lr.run(e, platform, (e.get("analysis") or {}).get("analyzedAt"))
        pub = v.signs[0].interval.start if False else None
        out[name] = {"level": int(v.level), "signs": [
            {"pattern": s.pattern, "metric": s.metric.value, "strength": round(s.strength, 2), "formula": s.formula,
             "start": s.interval.start.isoformat(), "end": s.interval.end.isoformat()} for s in v.signs]}
json.dump(out, open(out_path, "w"), ensure_ascii=False)
print(len(out))
