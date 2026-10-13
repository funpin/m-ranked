import os
import json, random
from datetime import datetime
SP = os.environ.get("MR_WORK", ".")
posts = {}
for f in ("sample_posts.json", "four_posts.json", "extra_posts.json"):
    posts.update(json.load(open(f"{SP}/{f}")))
cur, eq, tol = (json.load(open(f"{SP}/signs_{n}.json")) for n in ("cur", "eq", "tol"))
TYPES = {"photo": "фото", "video": "видео", "album": "альбом", "text": "текст", "link": "ссылка", "poll": "опрос"}
PLAT = {"vk": "ВК", "telegram": "Telegram", "max": "MAX"}
keys = [k for k in cur if cur[k]["level"] != eq[k]["level"] or cur[k]["level"] != tol[k]["level"]]
random.Random(20261013).shuffle(keys)
cards, key_rows = [], []
sig = lambda s: (s["pattern"], s["metric"], s["start"][:13])
for i, k in enumerate(keys, 1):
    e = posts[k]; meta = e["meta"]
    pub = datetime.fromisoformat(meta["publishedAt"])
    age = lambda iso: (datetime.fromisoformat(iso) - pub).total_seconds() / 3600
    pts = sorted(([p["ageHours"], (p["views"] or {}).get("value"), (p["reactions"] or {}).get("value")] for p in e["points"]), key=lambda x: x[0])
    old = {sig(s): s for s in cur[k]["signs"]}; new = {sig(s): s for s in tol[k]["signs"]}
    added = [s for key, s in new.items() if key not in old]; removed = [s for key, s in old.items() if key not in new]
    ends = [age(s["end"]) for s in cur[k]["signs"] + tol[k]["signs"]]
    xmax = max(72.0, min(max(ends + [0]) + 36, 24 * 14))
    bands = [[age(s["start"]), age(s["end"]), f"признак {s['pattern']}", "sign"] for key, s in old.items() if key in new]
    bands += [[age(s["start"]), age(s["end"]), f"новый признак {s['pattern']}", "newsign"] for s in added]
    bands += [[age(s["start"]), age(s["end"]), f"снятый признак {s['pattern']}", "sign"] for s in removed]
    facts = [f"уровень сейчас {cur[k]['level']}, с правкой {tol[k]['level']}"]
    facts += [f"новый: {s['pattern']} ({s['metric']}) — {s['formula'][:220]}" for s in added]
    facts += [f"снят: {s['pattern']} ({s['metric']}) — {s['formula'][:220]}" for s in removed]
    cards.append({"id": f"{i:02d}", "meta": f"{PLAT.get(meta.get('platform','vk'),'ВК')} · {TYPES.get(meta.get('publicationType'), meta.get('publicationType'))}",
                  "x": "age", "xmax": xmax, "points": pts, "bands": bands, "facts": facts})
    key_rows.append({"card": f"P{i:02d}", "post": k, "url": meta.get("publicUrl"), "cur": cur[k]["level"], "eq": eq[k]["level"], "tol": tol[k]["level"]})
json.dump({"cards": cards}, open(f"{SP}/plateau_cards.json", "w"), ensure_ascii=False)
json.dump(key_rows, open(f"{SP}/plateau_key.json", "w"), ensure_ascii=False, indent=1)
print(len(cards), "cards;", sum(1 for r in key_rows if r["cur"] != r["eq"]), "change under equal-edges")
