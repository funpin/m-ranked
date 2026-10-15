"""Blind review cards → one HTML page with inline SVG charts.

cards.json: {"sections": [{"id","title","intro","cards":[{"id","meta","x":"age"|"msk",
  "points":[[x_hours, views, reactions]], "bands":[[x0,x1,label,kind]], "facts":[str], "note": str}]}],
  "tables": [{"title","head":[...],"rows":[[...]]}] }
"""
import html, json, sys

def esc(s): return html.escape(str(s))

def nice_max(v):
    if v <= 0: return 1
    import math
    e = 10 ** math.floor(math.log10(v)); f = v / e
    return (1 if f <= 1 else 2 if f <= 2 else 2.5 if f <= 2.5 else 5 if f <= 5 else 10) * e

def fmt(v):
    v = float(v)
    if v >= 1000: return f"{v/1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " тыс."
    return f"{v:.0f}"

def chart(card):
    pts = card["points"]
    if len(pts) < 2: return "<p class='muted'>нет замеров</p>"
    W, H, L, R, T, B = 640, 220, 68, 44, 14, 30
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    if card.get("xmax"): x1 = min(x1, card["xmax"])
    pts = [p for p in pts if p[0] <= x1]
    vmax = nice_max(max(p[1] or 0 for p in pts)); rmax = nice_max(max(p[2] or 0 for p in pts))
    sx = lambda x: L + (x - x0) / max(x1 - x0, 1e-9) * (W - L - R)
    sv = lambda v: T + (1 - (v or 0) / vmax) * (H - T - B)
    sr = lambda v: T + (1 - (v or 0) / rmax) * (H - T - B)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(card["meta"])}">']
    for b in card.get("bands", []):
        a, z = max(b[0], x0), min(b[1], x1)
        if z <= a: continue
        out.append(f'<rect class="band {esc(b[3])}" x="{sx(a):.1f}" y="{T}" width="{max(sx(z)-sx(a),1.5):.1f}" height="{H-T-B}"><title>{esc(b[2])}</title></rect>')
    for i in range(5):
        y = T + i * (H - T - B) / 4
        out.append(f'<line class="grid" x1="{L}" x2="{W-R}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick v" x="{L-6}" y="{y+3:.1f}" text-anchor="end">{fmt(vmax*(1-i/4))}</text>')
        out.append(f'<text class="tick r" x="{W-R+6}" y="{y+3:.1f}">{fmt(rmax*(1-i/4))}</text>')
    span = x1 - x0
    step = next(s for s in (1, 2, 3, 6, 12, 24, 48, 72, 168, 336) if span / s <= 8)
    import math
    t = math.ceil(x0 / step) * step
    while t <= x1:
        lab = card.get("xlabels", {}).get(str(int(t))) if card["x"] == "msk" else None
        if card["x"] == "age":
            lab = f"{int(t)} ч" if t < 48 else f"{t/24:.0f} сут"
        out.append(f'<text class="tick" x="{sx(t):.1f}" y="{H-10}" text-anchor="middle">{esc(lab or "")}</text>')
        out.append(f'<line class="grid faint" x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{T}" y2="{H-B}"/>')
        t += step
    pv = " ".join(f"{sx(p[0]):.1f},{sv(p[1]):.1f}" for p in pts if p[1] is not None)
    pr = " ".join(f"{sx(p[0]):.1f},{sr(p[2]):.1f}" for p in pts if p[2] is not None)
    out.append(f'<polyline class="views" points="{pv}"/><polyline class="reacts" points="{pr}"/>')
    out.append("</svg>")
    return "".join(out)

def card_html(sec, card):
    import re
    facts = "".join(f"<li>{esc(re.sub(r'(?<=[0-9])[.](?=[0-9])', ',', f))}</li>" for f in card.get("facts", []))
    cid = f'{sec["id"]}-{card["id"]}'
    verdict = "".join(
        f'<label><input type="radio" name="{cid}" value="{v}" id="{cid}-{v}"> {t}</label>'
        for v, t in (("yes", "заслуживает"), ("no", "не заслуживает"), ("maybe", "спорно")))
    return (f'<article class="card" id="{cid}"><header><span class="num">#{esc(card["id"])}</span>'
            f'<span class="meta">{esc(card["meta"])}</span></header>{chart(card)}'
            f'<ul class="facts">{facts}</ul>'
            + (f'<p class="note">{esc(card["note"])}</p>' if card.get("note") else "")
            + ("" if card.get("reference") else f'<fieldset class="verdict"><legend>Ваша оценка</legend>{verdict}</fieldset>') + '</article>')

def page(data):
    secs = []
    for sec in data["sections"]:
        cards = "".join(card_html(sec, c) for c in sec["cards"])
        secs.append(f'<section id="{sec["id"]}"><h2>{esc(sec["title"])}</h2><p class="intro">{esc(sec["intro"])}</p>'
                    f'<div class="cards">{cards}</div></section>')
    tables = []
    for t in data.get("tables", []):
        head = "".join(f"<th>{esc(h)}</th>" for h in t["head"])
        rows = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in t["rows"])
        tables.append(f'<section><h2>{esc(t["title"])}</h2>' + (f'<p class="intro">{esc(t["intro"])}</p>' if t.get("intro") else "")
                      + f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></section>')
    nav = "".join(f'<a href="#{s["id"]}">{esc(s["title"])}</a>' for s in data["sections"])
    return TEMPLATE.replace("{{TITLE}}", esc(data["title"])).replace("{{LEAD}}", esc(data["lead"])) \
        .replace("{{NAV}}", nav).replace("{{BODY}}", "".join(tables) + "".join(secs))

TEMPLATE = open(__file__.rsplit("/", 1)[0] + "/cards_template.html").read()
if __name__ == "__main__":
    open(sys.argv[2], "w").write(page(json.load(open(sys.argv[1]))))
