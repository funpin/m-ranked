"""Слепые карточки для разметки: выборка по стратам, выгрузка рядов и отрисовка.

usage:
  python -I eval_cards.py extract BASE_DSN CAND_DSN OUT_DIR   (окружение проекта: psycopg)
  python -I eval_cards.py render OUT_DIR                      (любой Python с matplotlib)

Только посты 22.09–07.10 (пороги подбирались на 01–21.09), зерно 20261012,
не больше пяти карточек с аккаунта в страте. На карточке нет названия вуза,
ссылки и страты; ключ «номер → пост, страта» — в cards_key.csv, при разметке
не открывается.
"""
import csv
import json
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone

SEED = 20261012
HOLDOUT = datetime(2026, 9, 22, tzinfo=timezone.utc)
STRATA = (("new_sign", 40), ("near_miss", 15), ("clean", 15), ("tg_rounding_up", 15), ("vk_video_down", 10))


def extract(base_dsn, cand_dsn, out):
    import psycopg
    from psycopg.rows import dict_row
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    from eval_diff import load

    base, base_found = load(base_dsn)
    cand, cand_found = load(cand_dsn)
    rng = random.Random(SEED)
    with psycopg.connect(cand_dsn, row_factory=dict_row) as connection:
        states = {str(r["publication_id"]): r for r in connection.execute(
            """SELECT s.publication_id, s.level, s.signals, p.publication_type, p.published_at
                 FROM analytics.post_anomaly_state s JOIN ingest.publication p ON p.id = s.publication_id
                WHERE s.published_at >= %s""", (HOLDOUT,))}
    candidates = defaultdict(list)
    for key, row in cand.items():
        if row["published_at"] < HOLDOUT or key not in base or key not in states:
            continue
        before, signals = base[key], states[key]["signals"] or []
        modes = {(s.get("pattern"), (s.get("render") or {}).get("mode"), (s.get("render") or {}).get("measurementMode"))
                 for s in signals}
        new_modes = any(p == 1 and (mode == "short_views" or mm == "bounded_views") for p, mode, mm in modes)
        strong_new = any(s.get("pattern") == 1 and s.get("metric") == "views" and s.get("strength", 0) >= 0.7
                         and ((s.get("render") or {}).get("mode") == "short_views"
                              or (s.get("render") or {}).get("measurementMode") == "bounded_views") for s in signals)
        weak_new = any(s.get("pattern") == 1 and (s.get("render") or {}).get("mode") == "short_views"
                       and s.get("strength", 0) < 0.7 for s in signals)
        if strong_new and row["level"] >= 2:
            candidates["new_sign"].append(key)
        elif weak_new:
            candidates["near_miss"].append(key)
        if row["level"] == 0 and before["level"] == 0 and not new_modes:
            candidates["clean"].append(key)
        if row["platform"] == "telegram" and row["level"] > before["level"] and new_modes:
            candidates["tg_rounding_up"].append(key)
        if (row["platform"] == "vk" and states[key]["publication_type"] == "video"
                and row["level"] < before["level"]):
            candidates["vk_video_down"].append(key)
    picked = []
    for stratum, limit in STRATA:
        pool = sorted(candidates[stratum])
        rng.shuffle(pool)
        per_account, chosen = defaultdict(int), []
        for key in pool:
            account = cand[key]["account_id"]
            if per_account[account] < 5 and key not in {k for k, _ in picked}:
                per_account[account] += 1
                chosen.append(key)
            if len(chosen) == limit:
                break
        picked += [(key, stratum) for key in chosen]
        print(f"{stratum}: pool {len(pool)}, picked {len(chosen)}")
    # Аккаунтные находки по охватам — все, с шестью случайными участниками.
    accounts = []
    with psycopg.connect(cand_dsn, row_factory=dict_row) as connection:
        for row in connection.execute(
                """SELECT account_id::text, platform, kind, status, metrics, members FROM analytics.account_anomaly_finding
                    WHERE kind IN ('view_packs','view_waves','level3_share','flat_daily_views')"""):
            members = sorted(str(m) for m in row["members"])
            rng.shuffle(members)
            accounts.append({"kind": row["kind"], "status": row["status"], "platform": row["platform"],
                             "account_id": row["account_id"], "metrics": {
                                 k: v for k, v in row["metrics"].items() if k in (
                                     "posts", "packs", "share", "level3", "days", "hours", "views", "reactions",
                                     "viewShare", "latestN", "amplitude", "cohortP90", "patterns")},
                             "members": members[:6]})
    rng.shuffle(picked)
    needed = {key for key, _ in picked} | {m for a in accounts for m in a["members"]}
    with psycopg.connect(cand_dsn, row_factory=dict_row) as connection:
        series = defaultdict(list)
        for r in connection.execute(
                """SELECT pt.publication_id::text AS id, pt.age_seconds, pt.views_count, pt.reactions_count
                     FROM ingest.publication_metric_point pt
                    WHERE pt.publication_id = ANY(%s::uuid[]) AND pt.visible AND NOT pt.synthetic
                      AND pt.published_month >= '2026-08-01'
                    ORDER BY pt.publication_id, pt.observed_at""", (sorted(needed),)):
            series[r["id"]].append((r["age_seconds"] / 3600, r["views_count"], r["reactions_count"]))
        meta = {str(r["publication_id"]): r for r in connection.execute(
            """SELECT s.publication_id, s.level, s.signals, p.publication_type, a.platform::text AS platform
                 FROM analytics.post_anomaly_state s JOIN ingest.publication p ON p.id = s.publication_id
                 JOIN catalog.platform_account a ON a.id = p.primary_account_id
                WHERE s.publication_id = ANY(%s::uuid[])""", (sorted(needed),))}

    def post_card(key):
        m = meta[key]
        signs = [{"pattern": s.get("pattern"), "metric": s.get("metric"), "strength": s.get("strength"),
                  "mode": (s.get("render") or {}).get("mode"), "startAge": (s.get("render") or {}).get("startAge"),
                  "endAge": (s.get("render") or {}).get("endAge"), "formula": s.get("formula")}
                 for s in m["signals"] or []]
        return {"platform": m["platform"], "type": m["publication_type"], "level": m["level"],
                "points": series.get(key, []), "signs": signs}

    cards = [{"card": index + 1, **post_card(key)} for index, (key, _) in enumerate(picked)]
    account_cards = [{"card": f"A{index + 1}", **{k: v for k, v in a.items() if k not in ("account_id", "members")},
                      "posts": [post_card(m) for m in a["members"] if m in meta]}
                     for index, a in enumerate(accounts)]
    with open(f"{out}/cards.json", "w") as handle:
        json.dump({"posts": cards, "accounts": account_cards}, handle, ensure_ascii=False, default=str)
    with open(f"{out}/cards_key.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["card", "id", "stratum", "institution", "uname"])
        for index, (key, stratum) in enumerate(picked):
            writer.writerow([index + 1, key, stratum, cand[key]["institution"], cand[key]["uname"]])
        for index, a in enumerate(accounts):
            writer.writerow([f"A{index + 1}", a["account_id"], a["kind"], "", ""])
    print(f"post cards: {len(cards)}, account cards: {len(account_cards)}")


def render(out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = json.load(open(f"{out}/cards.json"))

    def draw(ax, card, title, until=72):
        pts = [p for p in card["points"] if p[0] <= until]
        ages = [p[0] for p in pts]
        ax.plot(ages, [p[1] for p in pts], color="#2b6cb0", lw=1.2, label="просмотры")
        ax.set_xlabel("часы", fontsize=7)
        ax.tick_params(labelsize=6)
        twin = ax.twinx()
        twin.plot(ages, [p[2] for p in pts], color="#c05621", lw=1.0, label="реакции")
        twin.tick_params(labelsize=6, colors="#c05621")
        for sign in card["signs"]:
            if sign["startAge"] is not None and sign["endAge"] is not None and sign["startAge"] / 3600 <= until:
                ax.axvspan(sign["startAge"] / 3600, min(until, sign["endAge"] / 3600),
                           color="#e53e3e" if sign["pattern"] == 1 and sign["metric"] == "views" else "#a0aec0",
                           alpha=0.18)
        ax.set_title(title, fontsize=7)

    for card in data["posts"]:
        fig, ax = plt.subplots(figsize=(6, 2.6))
        signs = ", ".join(f"{s['pattern']}{'/' + s['mode'] if s['mode'] else ''}:{s['strength']}" for s in card["signs"])
        draw(ax, card, f"#{card['card']} · {card['platform']} · {card['type']} · уровень {card['level']} · {signs}")
        fig.tight_layout()
        fig.savefig(f"{out}/card_{card['card']:03d}.png", dpi=110)
        plt.close(fig)
    for card in data["accounts"]:
        fig, axes = plt.subplots(2, 3, figsize=(10, 4.4))
        for ax, post in zip(axes.flat, card["posts"]):
            # Волны и сводные находки видны на всём сроке поста, а не в первые трое суток.
            draw(ax, post, f"уровень {post['level']}", until=30 * 24)
        fig.suptitle(f"{card['card']} · {card['platform']} · {card['kind']} · статус {card['status']} · "
                     f"{json.dumps(card['metrics'], ensure_ascii=False)}", fontsize=7)
        fig.tight_layout()
        fig.savefig(f"{out}/account_{card['card']}.png", dpi=100)
        plt.close(fig)
    print("rendered", len(data["posts"]), "post cards and", len(data["accounts"]), "account cards")


if __name__ == "__main__":
    if sys.argv[1] == "extract":
        extract(*sys.argv[2:5])
    else:
        render(sys.argv[2])
