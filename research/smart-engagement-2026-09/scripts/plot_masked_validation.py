"""Render saved research aggregates; never recompute numerical experiments."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 3, figsize=(16, 7.6), gridspec_kw={'width_ratios': [1, 1, 1.35]})
    fig.subplots_adjust(left=.055, right=.98, bottom=.36, top=.80, wspace=.6)
    fig.suptitle('MAX: ранняя маскировка, загрязнение нормы и обычные альтернативы',
                 x=.055, y=.96, ha='left', fontsize=17, weight='bold')
    fig.text(.055, .9, 'Исследование 28.09.2026 • Замороженные данные и контролируемые воздействия • Публичные оценки не меняются', color='#555555')
    colors = ['#285f9e', '#d45e26', '#37816d']
    ax = axes[0]
    early = data['early_masking']['models']
    for mode, kind, label, color in [
        ('conditional_v24', 'late_only', 'V24: добавка только поздно', colors[0]),
        ('conditional_v24', 'already_in_v24', 'V24: добавка уже рано', colors[1]),
        ('historical_account_only', 'already_in_v24', 'История без V24: рано', colors[2]),
    ]:
        y = [100*early[mode]['injections'][f][kind]['new_among_base_clear']['rate'] for f in ('0.1', '0.3', '1.0')]
        ax.plot(range(3), y, 'o-', color=color, label=label)
    ax.set_xticks(range(3), ['10%', '30%', '100%'])
    ax.set_title('A. Ранний охват скрывает добавку', loc='left', fontsize=11, pad=18)
    ax.set_xlabel('Добавлено к конечному счётчику')
    ax.set_ylabel('Новые сигналы, % (n=366)')
    ax.set_ylim(0, 105)
    ax.legend(loc='upper left', bbox_to_anchor=(0, -.20), frameon=False, fontsize=9)

    ax = axes[1]
    for method, label, color in zip(('own_mean', 'own_median', 'peer_median'),
                                  ('Свой средний log-уровень', 'Своя медиана', 'Медиана других аккаунтов'), colors):
        rows = [r for r in data['history_contamination']['results'] if r['method']==method and r['calibration_also_contaminated']]
        ax.plot([100*r['contaminated_fraction'] for r in rows],
                [100*r['double_count_test_alerts']['rate'] for r in rows], 'o-', label=label, color=color)
    ax.set_title('B. История и порог поглощают рост', loc='left', fontsize=11, pad=18)
    ax.set_xlabel('Изменённая история, %')
    ax.set_ylabel('Сигналы на удвоенном тесте, %')
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_ylim(0, 105)
    ax.legend(loc='upper left', bbox_to_anchor=(0, -.20), frameon=False, fontsize=9)

    ax = axes[2]
    cases = [('proportional_path', '1.0', 'Точное V×2 и R×2\nER сохранён', colors[0]),
             ('shared_reaction_pulses', '1.0', 'Общие волны R\nфактически +55% R', colors[0]),
             ('independent_reaction_pulses', '1.0', 'Независимые волны R\nфактически +56% R', colors[0]),
             ('archive_reader_session', 'one', 'Один читатель архива\n+1 V и +1 R на пост', colors[1])]
    vals = [100*data['trajectory_stress']['scenarios'][name][f]['new_among_base_clear']['rate'] for name, f, _, _ in cases]
    ax.barh(np.arange(4), vals, color=[c[3] for c in cases], height=.56)
    ax.set_yticks(np.arange(4), [c[2] for c in cases], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 106)
    ax.set_xlabel('Новые сигналы, % (n=1398)')
    ax.set_title('C. Сигнал не определяет причину', loc='left', fontsize=11, pad=18)
    for i, val in enumerate(vals):
        ax.text(val+1.5, i, f'{val:.1f}', va='center', fontsize=10)
    for ax in axes:
        ax.grid(axis='y' if ax is not axes[2] else 'x', color='#e6e6e6', linewidth=.7)
        ax.set_axisbelow(True)
    fig.text(.055, .075, 'A — изменены реальные немеченые счётчики; B — сопоставимость аккаунтов задана; C — известный генератор на 59 масках MAX.', fontsize=10, color='#555555')
    fig.text(.055, .035, 'Контрольный генератор C: 6.8% сигналов при номинале 5%. Это чувствительность к заданным воздействиям, не точность выявления реальной накрутки.', fontsize=10, color='#555555')
    fig.savefig(args.output, dpi=160, facecolor='white', metadata={'Software': 'matplotlib; saved research aggregates'})
    plt.close(fig)


if __name__ == '__main__':
    main()
