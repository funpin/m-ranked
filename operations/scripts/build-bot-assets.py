#!/usr/bin/env python3
"""Пересобрать PNG-значки и знак m-ranked для обложек Telegram-бота.

Берёт официальные SVG площадок из frontend/public/brands и три пути знака из
frontend/public/icons/app-icon.svg (фоновый <rect> и обёртка translate/scale
отбрасываются: у путей своя система координат 0..589 x 0..344). Растеризует
в telegram_bot/assets:

    icons/{telegram,vk,max,rutube}.png  88x88 RGBA (2x от 44 px)
    logo.png                            ширина 400 RGBA (2x от 200)

Растеризация идёт внешней программой rsvg-convert (librsvg): macOS
`brew install librsvg`, Debian `apt install librsvg2-bin`. Это инструмент
разработчика: в requirements её нет, а собранные PNG лежат в репозитории, так
что ни образ, ни прод её не требуют. Запускайте скрипт только когда меняются
исходные SVG:

    python3 operations/scripts/build-bot-assets.py
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[2]
BRANDS = ROOT / "frontend" / "public" / "brands"
APP_ICON = ROOT / "frontend" / "public" / "icons" / "app-icon.svg"
ASSETS = ROOT / "telegram_bot" / "assets"

PLATFORMS = ("telegram", "vk", "max", "rutube")
ICON_SIZE = 88
LOGO_WIDTH = 400
# Система координат трёх путей знака в app-icon.svg.
LOGO_VIEWBOX = "0 0 589 344"
SVG_NS = "http://www.w3.org/2000/svg"


def rasterize(source: Path, target: Path, *size: str) -> None:
    subprocess.run(["rsvg-convert", *size, "--format", "png", "--output", str(target), str(source)],
                   check=True)


class _Paths(HTMLParser):
    """Атрибуты <path> из SVG. html.parser, а не xml: он не раскрывает
    внешние сущности (XXE) — правило Semgrep use-defused-xml-parse."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "path":
            self.paths.append(dict(attrs))

    handle_startendtag = handle_starttag


def logo_paths(svg: str) -> list[dict[str, str | None]]:
    parser = _Paths()
    parser.feed(svg)
    parser.close()
    return parser.paths


def logo_svg() -> str:
    """SVG только из трёх путей знака, без фона и без трансформации."""
    paths = logo_paths(APP_ICON.read_text(encoding="utf-8"))
    if len(paths) != 3:
        raise SystemExit(f"в {APP_ICON} ожидалось три пути знака, найдено {len(paths)}")
    body = "".join(f'<path fill="{path.get("fill")}" d="{path.get("d")}"/>' for path in paths)
    return f'<svg xmlns="{SVG_NS}" viewBox="{LOGO_VIEWBOX}">{body}</svg>'


def main() -> int:
    if shutil.which("rsvg-convert") is None:
        print("нужен rsvg-convert (librsvg): brew install librsvg", file=sys.stderr)
        return 1
    (ASSETS / "icons").mkdir(parents=True, exist_ok=True)
    for platform in PLATFORMS:
        rasterize(BRANDS / f"{platform}.svg", ASSETS / "icons" / f"{platform}.png",
                  "--width", str(ICON_SIZE), "--height", str(ICON_SIZE))
    with tempfile.TemporaryDirectory() as directory:
        svg = Path(directory) / "logo.svg"
        svg.write_text(logo_svg(), encoding="utf-8")
        rasterize(svg, ASSETS / "logo.png", "--width", str(LOGO_WIDTH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
