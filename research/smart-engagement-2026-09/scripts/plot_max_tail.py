"""Render frozen aggregate results; plotting never refits the models."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def render(result, output):
    names = ["МГУ Ломоносова", "МФТИ", "МГУ Куинджи", "ЮЗГУ", "КГУ Курск"]
    ids = {v["case_name"]: k for k, v in result["cohort"].items() if v["case_name"]}
    main = [result["cohort"][ids[n]] for n in names]
    loose = [result["sensitivities"]["loose_6h"]["cases"][ids[n]] for n in names]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig = plt.figure(figsize=(14, 9.5), facecolor="#fafbfc")
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.3], width_ratios=[1.5, 1],
                          left=.145, right=.95, top=.84, bottom=.21, hspace=.58, wspace=.5)
    ax = fig.add_subplot(gs[0, 0])
    pos = np.arange(5)
    for values, delta, color, label in [(main, -.17, "#276b91", "Границы ≤3 ч (основной расчёт)"),
                                      (loose, .17, "#71b0a0", "Границы ≤6 ч (чувствительность)")]:
        bars = ax.barh(pos + delta, [100*v["late"]["positive_fraction"] for v in values],
                       height=.30, color=color, label=label)
        for bar, v in zip(bars, values):
            ax.text(bar.get_width()+.6, bar.get_y()+bar.get_height()/2,
                    f'{v["late"]["positive"]}/{v["late"]["n"]}', va="center", fontsize=9)
    ax.set_yticks(pos, names); ax.invert_yaxis(); ax.set_xlim(0, 67)
    ax.set_xlabel("Интервалы с приростом реакций, %")
    ax.set_title("A. Отклик на посты возрастом 4–14 дней", loc="left", fontsize=12, pad=12)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -.22), frameon=False, fontsize=9)
    ax.grid(axis="x", alpha=.15); ax.set_axisbelow(True)

    ax2 = fig.add_subplot(gs[0, 1])
    rates = [100*v["late"]["n"]/sum(d["opportunities"] for d in v["days"]) for v in main]
    bars = ax2.barh(pos, rates, height=.5, color="#718091")
    ax2.invert_yaxis(); ax2.set_yticks(pos, names); ax2.set_xlim(0, 100)
    for bar, value in zip(bars, rates):
        ax2.text(value+2, bar.get_y()+bar.get_height()/2, f"{value:.0f}%", va="center", fontsize=10)
    ax2.set_xlabel("Пригодная доля возможных интервалов, %")
    ax2.set_title("B. Покрытие основного расчёта", loc="left", fontsize=12, pad=12)
    ax2.grid(axis="x", alpha=.15); ax2.set_axisbelow(True)

    heat = np.full((5, 14), np.nan)
    for i, values in enumerate(loose):
        for j, d in enumerate(values["days"]):
            if d["n"] >= 10 and d["coverage"] >= .5:
                heat[i, j] = 100*d["positive_fraction"]
    ax3 = fig.add_subplot(gs[1, :])
    cmap = plt.get_cmap("YlGnBu").copy(); cmap.set_bad("#dedfe2")
    im = ax3.imshow(heat, vmin=0, vmax=100, cmap=cmap, aspect="auto")
    ax3.set_yticks(pos, names); ax3.set_xticks(np.arange(14), [str(d) for d in range(14, 28)])
    ax3.set_xlabel("Сентябрь 2026, московские календарные дни")
    ax3.set_title("C. Повторяемость: доля старых постов с приростом реакций за день, % (границы ≤6 ч)",
                  loc="left", fontsize=12, pad=12)
    for i in range(5):
        for j in range(14):
            v = heat[i, j]
            ax3.text(j, i, "—" if np.isnan(v) else f"{v:.0f}", ha="center", va="center",
                     color="white" if v >= 60 else "#162c3d", fontsize=10)
    cb = fig.colorbar(im, ax=ax3, fraction=.025, pad=.025)
    cb.set_ticks([0, 50, 100]); cb.set_label("%")
    fig.text(.07, .945, "MAX: длинные хвосты реакций и повторные эпизоды", fontsize=19, weight="bold", color="#162c3d")
    fig.text(.07, .899, "14–27 сентября · 81 аккаунт в когорте · показаны пять примеров пользователя", fontsize=12, color="#526070")
    fig.text(.145, .065,
             "Числа у столбцов: интервалы с приростом / все пригодные интервалы; один пост встречается в разные дни.\n"
             "Серые дни: <10 наблюдаемых старых постов или покрытие <50%; это неизвестность, а не нулевой отклик.\n"
             "Реальные пары замеров, без интерполяции. Длительность 18–30 ч. График не оценивает вероятность накрутки.",
             fontsize=10, color="#526070", linespacing=1.55)
    fig.savefig(output, dpi=165, facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    render(json.loads(args.result.read_text()), args.output)
