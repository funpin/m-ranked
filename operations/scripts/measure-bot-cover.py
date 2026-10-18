#!/usr/bin/env python3
"""Замер отрисовки обложки Telegram-бота: время кадра и память процесса.

Рисует telegram_bot.cover.draw() на 20 наборах (12 крайних и 8 случайных с
фиксированным зерном), прогрев не считается. Печатает p50/p95/max времени
одного кадра, размер PNG и пиковую RSS (ru_maxrss) после импорта, после
прогрева и в конце. Только стандартная библиотека и Pillow; БД и сеть не
трогает. Запуск из корня репозитория или релиза, тем же python, что у бота:

    python operations/scripts/measure-bot-cover.py

Норма: p95 < 0,5 с на кадр, рост RSS после прогрева < 10 МБ, пик < 120 МБ.
"""
from __future__ import annotations

import random
import resource
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PLATFORMS = ("telegram", "vk", "max", "rutube")
SUBTITLE = "просмотры за неделю · 10–16 окт"
PASSES = 5  # проходов по всем наборам после прогрева


def rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024 if sys.platform == "darwin" else 1024)


def datasets(cover) -> list:
    Row, CoverData = cover.Row, cover.CoverData
    long_name = ("Федеральное государственное автономное образовательное учреждение высшего "
                 "образования Московский физико-технический институт национальный "
                 "исследовательский университет имени")
    sets = [
        CoverData(long_name.ljust(200, "я")[:200], SUBTITLE,
                  [Row("vk", 6400, 6000), Row("telegram", 2100, None)]),
        CoverData("Московский физико-технический институт (национальный "
                  "исследовательский университет)", SUBTITLE, [Row("telegram", 912, 1000)]),
        CoverData("Ж" * 200, "x" * 300, [Row("max", 5, 4)]),
        CoverData("МФТИ", SUBTITLE, [Row("rutube", 77, None)]),
        CoverData("МФТИ", SUBTITLE, [Row(p, v, v - 1) for p, v in
                                    zip(PLATFORMS, (9_200_000, 999_999, 1_250, 7))]),
        CoverData("МФТИ", SUBTITLE, [Row(p, 0, 0) for p in PLATFORMS]),
        CoverData("МФТИ", SUBTITLE, [Row("vk", 10 ** 9, 1), Row("telegram", 1, 1),
                                    Row("max", 0, 5), Row("rutube", None, 3)]),
        CoverData("МФТИ", SUBTITLE, [Row(p, 999_999 if i == 0 else 1099, 100)
                                    for i, p in enumerate(PLATFORMS)]),
        CoverData("МФТИ", SUBTITLE, [Row(p, 1, 1000) for p in PLATFORMS]),
        CoverData("МФТИ", SUBTITLE, []),
        CoverData("МФТИ", SUBTITLE, [Row(p, None, 5) for p in PLATFORMS]),
        CoverData("", "", [Row("vk", 3, None)]),
    ]
    alphabet = "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕ abcdefMWЖШЩ0123456789«»№-—."
    for seed in range(8):
        rng = random.Random(seed)
        title = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 120))).strip() or "Ж"
        rows = [Row(p, rng.choice((0, 1, rng.randint(2, 99), rng.randint(100, 10 ** 9))),
                    rng.choice((None, rng.randint(1, 10 ** 6))))
                for p in rng.sample(PLATFORMS, rng.randint(1, 4))]
        sets.append(CoverData(title, SUBTITLE, rows))
    return sets


def main() -> int:
    import PIL
    from telegram_bot import cover

    sets = datasets(cover)
    after_import = rss_mb()
    for _ in range(3):  # прогрев: шрифты, значки и плато аллокатора
        for data in sets:
            cover.draw(data)
    warm = rss_mb()
    times: list[float] = []
    size = 0
    for _ in range(PASSES):
        for data in sets:
            started = time.perf_counter()
            png = cover.draw(data)
            times.append(time.perf_counter() - started)
            size = max(size, len(png))
    times.sort()
    p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
    print(f"python {sys.version.split()[0]}, Pillow {PIL.__version__}, "
          f"{len(sets)} наборов x {PASSES} проходов = {len(times)} кадров")
    print(f"время кадра: p50 {statistics.median(times) * 1000:.0f} мс, "
          f"p95 {p95 * 1000:.0f} мс, max {times[-1] * 1000:.0f} мс")
    print(f"PNG: максимум {size / 1024:.0f} КБ")
    print(f"RSS, МБ: после импорта {after_import:.1f}, после прогрева {warm:.1f}, "
          f"в конце {rss_mb():.1f} (рост {rss_mb() - warm:.1f})")
    ok = p95 < 0.5 and rss_mb() - warm < 10 and rss_mb() < 120
    print("норма:", "да" if ok else "НЕТ")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
