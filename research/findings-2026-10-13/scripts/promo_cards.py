import os
import json, random
from datetime import datetime, timedelta
from promo_features import MSK
SP = os.environ.get("MR_WORK", ".")
posts = json.load(open(f"{SP}/stage2_posts.json")); rows = json.load(open(f"{SP}/promo_rows.json"))
TYPES = {"photo": "фото", "video": "видео", "album": "альбом", "text": "текст"}
PLAT = {"vk": "ВК", "telegram": "Telegram", "max": "MAX"}
def card(r, cid, reference=False):
    e = posts[r["key"]]; meta = e["meta"]
    w0, w1 = (datetime.fromisoformat(x) for x in r["window"])
    origin = w0 - timedelta(days=2)
    pts = []
    for p in sorted(e["points"], key=lambda p: p["observedAt"]):
        t = (datetime.fromisoformat(p["observedAt"]) - origin).total_seconds() / 3600
        if t < 0: continue
        pts.append([t, (p["views"] or {}).get("value"), (p["reactions"] or {}).get("value")])
    xmax = (w1 - origin).total_seconds() / 3600 + 48
    labels = {}
    d = origin.astimezone(MSK)
    for h in range(0, int(xmax) + 1):
        t = (origin + timedelta(hours=h)).astimezone(MSK)
        if t.hour == 0: labels[str(h)] = t.strftime("%d.%m")
    pub = (datetime.fromisoformat(meta["publishedAt"]) - origin).total_seconds() / 3600
    bands = [[(w0 - origin).total_seconds() / 3600, (w1 - origin).total_seconds() / 3600, "окно эпизода аккаунта", "promo"]]
    if pub > 0: bands.append([pub, pub + 0.6, "публикация", "sign"])
    facts = [f"темп в окне {r['waveRate']}/ч — в {r['excess']} раза выше медианы обычных постов аккаунта в те же дни",
             f"реакций на 1 000 просмотров: в окне {r['wavePerK']}, в первые сутки поста {r['firstDayPerK']}",
             f"ночь/день (00–06 к 09–21 МСК) {r['nightToDay']}; спад после окна ×{r['stopRatio']}",
             f"возраст поста в начале окна {r['ageAtOnsetH']} ч"]
    meta_s = f"{PLAT[r['platform']]} · {TYPES.get(meta.get('publicationType'), meta.get('publicationType'))}"
    if reference: meta_s += f" · эталон: МФТИ №{meta['externalId'].split('_')[-1]}"
    return {"id": cid, "reference": reference, "meta": meta_s, "x": "msk", "xmax": xmax, "xlabels": labels, "points": pts, "bands": bands, "facts": facts}
ref = [r for r in rows if "miptru" in r["key"] and r["candidate"]]
cand = [r for r in rows if r["candidate"] and "miptru" not in r["key"]]
contrast = [r for r in rows if "miptru" in r["key"] and r["key"].split("_")[-1] in ("59045", "59048")]
random.Random(20261013).shuffle(cand)
blind = cand + contrast; random.Random(7).shuffle(blind)
out = {"reference": [card(r, f"E{i}", True) for i, r in enumerate(ref, 1)],
       "blind": [card(r, f"{i:02d}") for i, r in enumerate(blind, 1)]}
json.dump(out, open(f"{SP}/promo_cards.json", "w"), ensure_ascii=False)
json.dump([{"card": f"A{i:02d}", "post": r["key"], "url": posts[r["key"]]["meta"].get("publicUrl"), "candidate": r["candidate"], "inst": r["inst"]}
           for i, r in enumerate(blind, 1)], open(f"{SP}/promo_key.json", "w"), ensure_ascii=False, indent=1)
print(len(out["reference"]), "reference;", len(out["blind"]), "blind")
