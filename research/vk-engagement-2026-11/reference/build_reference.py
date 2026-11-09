"""Эталон постов ВК для проверки порогов (PLAN.md, этап 0).

Читает выгрузки схемы rvk с локальной копии прода и признаки формы, собирает
posts.csv: publication_id, класс, статус, источник решения, причина. Отбор
детерминирован. Доля реакций внутри всплеска в правила не входит: это проверяемая
величина этапа 2, и эталон, отобранный по ней, доказывал бы сам себя.

Классы описывают форму счётчиков, а не намерение: это рабочая разметка для
калибровки, не вывод о вузе (ADR-006).

    python build_reference.py <каталог с pfa_feat.pkl, ph.csv, subs.csv, accounts.csv> [выход.csv]
"""
import sys

import numpy as np
import pandas as pd

SEED = 20261108
PER_CLASS = 44
DISPUTED_PER_CLASS = 6
SOURCE_FORM = "form"
SOURCE_OWNER = "owner_test"

ORGANIZED = ("swsu_kursk", "mirea_official")
PROMOTION = ("bstubel", "smol_gu", "kostroma_university")
VIEW_BURSTS = ("kbsu.official", "mephi_official", "nust_misis", "gubkin.university", "rsukosygin")
REACTION_WAVES = ("maiuniversity", "reu")
TZ_SHIFT = ("siberianfederal", "nsu24")
FEDERAL = ("hse", "theacademy")
# Тест владельца, VK Ads 07–12.10.2026; единственный размеченный случай рекламы.
OWNER_PROMO_PREFIXES = ("26aabf8e", "5d9369ab", "f3e2f2e7", "bb6f379e", "85b17359")
# Аккаунты архетипов README и известные исключения не могут попасть в органику.
ORGANIC_EXCLUDED = set(ORGANIZED + PROMOTION + VIEW_BURSTS + REACTION_WAVES + TZ_SHIFT + FEDERAL) | {
    "miptru", "itmoru", "msu_official", "mgumariupolkuindzhi", "ncfu_main", "kursksu", "kamgu_beringa",
    "guap_ru", "sum_moscow",
}
# Просмотр графиков: реакции поднялись, частично сняты и не вернулись, либо один поздний
# всплеск. Правила по сводке это не отличают, поэтому решение записано явно.
VISUAL_DISPUTED = {
    "288c": "поздний единичный подъём реакций вместе с просмотрами",
    "1c0a": "реакции поднялись и были сняты",
    "401c": "реакции поднялись и были сняты",
    "908f": "реакции поднялись и были сняты",
    "70e8": "реакции поднялись и были сняты",
    "75da": "реакции поднялись и были сняты",
}
ORGANIC_METRICS = (
    "v72s", "erv72", "c72", "latestart", "top1", "steps", "lin6", "lin_night", "night", "cliff", "l2", "l3",
    "cv_r72", "cv_v72",
)
ORGANIC_ACCOUNTS = 10
ORGANIC_MIN_LOW_METRICS = 11
ORGANIC_MIN_POSTS = 50

WINDOW_START = "2026-09-01"
WINDOW_END = "2026-11-04"  # у всех постов окна есть полные 72 ч до дампа 07.11
LINEAR_MIN_HOURS = 6
# Одиночный скачок реакций — другая форма, чем отклик постоянной группы в течение дня.
ORGANIZED_MAX_REACTION_HOUR = 0.5
ORGANIZED_START = "2026-09-19"  # с этой даты ERV ЮЗГУ держится выше площадки (ADR-017)


def load(path):
    posts = pd.read_pickle(f"{path}/pfa_feat.pkl")
    subs = pd.read_csv(f"{path}/subs.csv").sort_values("d").groupby("aid").sc.last()
    posts["subs"] = posts.account_id.map(subs)
    posts["reach"] = posts.v72 / posts.subs
    hours = pd.read_csv(f"{path}/pha.csv", usecols=["pid", "ah", "dr"])
    peak = hours[hours.ah < 72].groupby("pid").dr.max()
    posts["top_r_share"] = posts.id.astype(str).map(peak).astype(float) / posts.r72.clip(lower=1)
    walls = pd.read_csv(f"{path}/ph.csv", parse_dates=["h"])
    return posts, walls, pd.read_csv(f"{path}/accounts.csv")


def wave_members(posts, walls):
    """Посты, попавшие в волну по стене: ≥ 10 старых постов аккаунта за один час."""
    v24 = posts.set_index("id").v24
    r24 = posts.set_index("id").r24
    w = walls.assign(v24=walls.pid.map(v24).fillna(0), r24=walls.pid.map(r24).fillna(0))
    w["vhit"] = w.dv >= np.maximum(100, 0.15 * w.v24)
    w["rhit"] = w.dr >= np.maximum(10, 0.2 * w.r24)
    hours = w.groupby(["account_id", "h"]).agg(vn=("vhit", "sum"), rn=("rhit", "sum")).reset_index()
    # Час, когда волна идёт у половины площадки, — обновление счётчика, а не событие аккаунта.
    wide = hours[hours.vn >= 10].groupby("h").account_id.nunique()
    bad = set(wide[wide >= hours.account_id.nunique() * 0.5].index)
    hours["vwave"] = (hours.vn >= 10) & ~hours.h.isin(bad)
    hours["rwave"] = hours.rn >= 10
    w = w.merge(hours[["account_id", "h", "vwave", "rwave"]], on=["account_id", "h"])
    return set(w[w.vhit & w.vwave].pid), set(w[w.rhit & w.rwave].pid)


def organic_accounts(accounts, rng):
    med = accounts[list(ORGANIC_METRICS)].median()
    low = (accounts[list(ORGANIC_METRICS)] <= med).sum(axis=1)
    pool = accounts[
        (low >= ORGANIC_MIN_LOW_METRICS)
        & (accounts.n >= ORGANIC_MIN_POSTS)
        & accounts.findings.isna()
        & ~accounts.uname.isin(ORGANIC_EXCLUDED)
    ].sort_values("uname")
    return list(rng.choice(pool.uname.to_numpy(), ORGANIC_ACCOUNTS, replace=False))


def num(x, digits=1):
    return f"{float(x):.{digits}f}"


def cliff(p):
    return p.day_cliff is True or p.day_cliff == True  # noqa: E712 — столбец object: bool и NaN


def shape(p):
    return (
        f"v72={int(p.v72)}, r72={int(p.r72)}, ступеней={int(p.steps)}, "
        f"обрыв={'да' if cliff(p) else 'нет'}, v6/v72={num(p.early6, 2)}"
    )


def night_run(p):
    return p.lin_len >= LINEAR_MIN_HOURS and bool(p.lin_night)


def organized(p):
    erv = p.r72 / p.v72
    single_jump = p.top_r_share > ORGANIZED_MAX_REACTION_HOUR
    if p.steps == 0 and not cliff(p) and p.c72 >= 5 and erv >= PLATFORM_ERV * 2.5 and not single_jump:
        return "confirmed", f"ERV {num(erv * 100)} % ≥ 2,5× площадки, комментариев {int(p.c72)}, просмотры без ступеней"
    if p.c72 >= 5 or erv >= PLATFORM_ERV * 2.5:
        return "disputed", (
            f"выполнена часть условий: ERV {num(erv * 100)} %, комментариев {int(p.c72)}, "
            f"ступеней {int(p.steps)}, доля реакций за один час {num(p.top_r_share, 2)}"
        )
    return None


def promotion(p):
    late = p.early6 < 0.05
    day_run = p.lin_len >= LINEAR_MIN_HOURS and not bool(p.lin_night)
    if p.reach >= 0.20 and (late or day_run) and not cliff(p):
        kind = "поздний старт" if late else f"ровный дневной участок {int(p.lin_len)} ч"
        return "confirmed", f"охват на подписчика {num(p.reach * 100)} %, {kind}, без дневного обрыва"
    if p.reach >= 0.20:
        return "disputed", f"охват на подписчика {num(p.reach * 100)} %, форма не подтверждает: {shape(p)}"
    return None


def view_bursts(p):
    if p.steps >= 1 and (cliff(p) or p.early6 < 0.05 or night_run(p)):
        tail = "дневной обрыв" if cliff(p) else "поздний старт" if p.early6 < 0.05 else "ровный участок сквозь ночь"
        return "confirmed", f"ступеней после второго часа {int(p.steps)}, {tail}, доля часа {num(p.top1_share, 2)}"
    if p.steps >= 1:
        return "disputed", f"ступень без обрыва и позднего старта, доля часа {num(p.top1_share, 2)}"
    return None


def reaction_waves(p):
    if p.id in REACTION_WAVE_POSTS and p.steps == 0:
        return "confirmed", f"пост в часе, когда ≥ 10 старых постов получили реакции; r72={int(p.r72)}"
    if p.id in REACTION_WAVE_POSTS:
        return "disputed", f"волна реакций, но у просмотров ступени: {int(p.steps)}"
    return None


def plain(p):
    if p.steps == 0 and not cliff(p) and p.early6 >= 0.05:
        return "confirmed", f"форма без особенностей: {shape(p)}"
    return "disputed", f"есть особенности формы: {shape(p)}"


RULES = (
    ("organized_audience", ORGANIZED, organized),
    ("external_promotion", PROMOTION, promotion),
    ("view_bursts", VIEW_BURSTS, view_bursts),
    ("reaction_waves", REACTION_WAVES, reaction_waves),
    ("timezone_shift", TZ_SHIFT, plain),
    ("federal", FEDERAL, plain),
)


def take(frame, rule, n, rng):
    """Равномерно по аккаунтам: иначе класс определял бы один самый частый аккаунт."""
    rows = []
    for uname, group in frame.groupby("uname", sort=True):
        ids = rng.permutation(group.id.astype(str).sort_values().to_numpy())
        rows.append((uname, group.set_index(group.id.astype(str)), list(ids)))
    picked = {"confirmed": [], "disputed": []}
    limits = {"confirmed": n, "disputed": DISPUTED_PER_CLASS}
    progress = True
    while progress:
        progress = False
        for _, group, ids in rows:
            while ids:
                pid = ids.pop()
                verdict = rule(group.loc[pid])
                if verdict is None or len(picked[verdict[0]]) >= limits[verdict[0]]:
                    continue
                picked[verdict[0]].append((pid, *verdict))
                progress = True
                break
    return [row for status in picked for row in picked[status]]


def build(path):
    global PLATFORM_ERV, REACTION_WAVE_POSTS
    rng = np.random.default_rng(SEED)
    posts, walls, accounts = load(path)
    _, REACTION_WAVE_POSTS = wave_members(posts, walls)
    all_posts = posts.copy()
    eligible = posts[
        (posts.published_at >= WINDOW_START)
        & (posts.published_at < WINDOW_END)
        & posts.v72.notna()
        & (posts.v72 >= 200)
        & posts.steps.notna()
        & (posts.is_repost == "f")
        & posts.publication_type.isin(["post", "text", "photo", "album"])
    ].copy()
    PLATFORM_ERV = float(accounts.erv72.median())

    rows = []
    for name, unames, rule in RULES:
        frame = eligible[eligible.uname.isin(unames)]
        if name == "organized_audience":
            frame = frame[frame.published_at >= ORGANIZED_START]
        rows += [(pid, name, status, SOURCE_FORM, why) for pid, status, why in take(frame, rule, PER_CLASS, rng)]

    organic = organic_accounts(accounts, rng)
    rows += [
        (pid, "organic", status, SOURCE_FORM, why)
        for pid, status, why in take(eligible[eligible.uname.isin(organic)], plain, PER_CLASS, rng)
    ]

    for prefix in OWNER_PROMO_PREFIXES:
        match = all_posts[all_posts.id.astype(str).str.startswith(prefix)]
        if len(match) != 1:
            raise SystemExit(f"пост теста владельца {prefix}: найдено {len(match)}")
        rows.append((
            str(match.id.iloc[0]), "external_promotion", "confirmed", SOURCE_OWNER,
            "оплаченное продвижение записи, тест владельца 07–12.10.2026",
        ))

    out = pd.DataFrame(rows, columns=["publication_id", "class", "status", "source", "reason"])
    for prefix, why in VISUAL_DISPUTED.items():
        hit = out.publication_id.str.startswith(prefix) & (out["class"] == "organized_audience")
        out.loc[hit, ["status", "reason"]] = ["disputed", f"при просмотре графика: {why}"]
    # Пост теста владельца важнее автоматического правила.
    out = out.sort_values("source", ascending=False).drop_duplicates("publication_id")
    return out.sort_values(["class", "status", "publication_id"]), organic


def main():
    path = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else "posts.csv"
    out, organic = build(path)
    out.to_csv(target, index=False)
    print(out.groupby(["class", "status"]).size().to_string())
    print("всего", len(out), "органика:", ", ".join(organic))


if __name__ == "__main__":
    main()
