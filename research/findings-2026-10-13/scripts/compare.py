import json, sys, importlib, subprocess
# usage: compare.py ROOT_A ROOT_B file1.json [file2.json ...]  — runs each root in its own process
import os
roots, files = sys.argv[1:3], sys.argv[3:]
code = r'''
import sys, json
root = sys.argv[1]; sys.path.insert(0, root)
sys.path.insert(0, "%s")
import local_run as lr
out = {}
for f in sys.argv[2:]:
    data = json.load(open(f))
    for name, e in data.items():
        if "analysis" not in e or "points" not in e: continue
        platform = e["meta"].get("platform") or ("telegram" if (e["meta"].get("externalId") or "").startswith("m:") else "vk")
        v = lr.run(e, platform, e["analysis"].get("analyzedAt"))
        out[name] = {"level": int(v.level), "signs": sorted({(s.pattern, s.metric.value) for s in v.signs})}
print(json.dumps(out))
''' % os.path.dirname(os.path.abspath(__file__))
res = []
for r in roots:
    p = subprocess.run([sys.executable, "-c", code, r, *files], capture_output=True, text=True)
    if p.returncode: print(p.stderr[-2000:]); sys.exit(1)
    res.append(json.loads(p.stdout.strip().splitlines()[-1]))
a, b = res
changed = [(n, a[n], b[n]) for n in a if a[n] != b[n]]
print(f"posts {len(a)}; changed {len(changed)}")
for n, x, y in changed: print(f"  {n}: {x['level']} {x['signs']} -> {y['level']} {y['signs']}")
