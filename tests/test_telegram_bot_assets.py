"""Ресурсы обложек бота: шрифты, значки площадок и знак m-ranked."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageFont

ASSETS = Path(__file__).resolve().parents[1] / "telegram_bot" / "assets"

# Google Fonts отдаёт только переменные файлы; начертание выбираем по имени.
FONTS = {
    "Geologica-Variable.ttf": "Bold",
    "Onest-Variable.ttf": "Regular",
    "JetBrainsMono-Variable.ttf": "Medium",
}
JETBRAINS_INSTANCES = ("Medium", "Bold")
PLATFORMS = ("telegram", "vk", "max", "rutube")


@pytest.mark.parametrize("name,instance", sorted(FONTS.items()))
def test_fonts_load_and_have_cyrillic(name: str, instance: str) -> None:
    font = ImageFont.truetype(str(ASSETS / "fonts" / name), 40)
    font.set_variation_by_name(instance)
    assert font.getlength("Ёжик №1 «МФТИ»") > 0
    # Кириллица рисуется настоящими глифами, а не рамкой «нет символа».
    missing = font.getmask("\U0010FFFD")
    for letter in "ЁжМФТИ":
        mask = font.getmask(letter)
        assert mask.getbbox() is not None
        assert bytes(mask) != bytes(missing) or mask.size != missing.size


def test_variable_font_instances_exist() -> None:
    geologica = ImageFont.truetype(str(ASSETS / "fonts" / "Geologica-Variable.ttf"), 40)
    # У Geologica вес по умолчанию Thin: без выбора начертания заголовки тонкие.
    geologica.set_variation_by_name("Bold")
    onest = ImageFont.truetype(str(ASSETS / "fonts" / "Onest-Variable.ttf"), 40)
    onest.set_variation_by_name("Regular")
    mono = ImageFont.truetype(str(ASSETS / "fonts" / "JetBrainsMono-Variable.ttf"), 40)
    for instance in JETBRAINS_INSTANCES:
        mono.set_variation_by_name(instance)


def test_triangles_have_glyphs() -> None:
    """Решение: ▲/▼ берём из JetBrains Mono, примитивами не рисуем."""
    cover = ASSETS.parent / "cover.py"
    if cover.exists():
        assert "DRAW_TRIANGLES" not in cover.read_text(encoding="utf-8")
    font = ImageFont.truetype(str(ASSETS / "fonts" / "JetBrainsMono-Variable.ttf"), 40)
    font.set_variation_by_name("Bold")
    missing = font.getmask("\U0010FFFD")
    masks = {}
    for glyph in "▲▼":
        mask = font.getmask(glyph)
        assert mask.getbbox() is not None, glyph
        assert (mask.size, bytes(mask)) != (missing.size, bytes(missing)), glyph
        masks[glyph] = bytes(mask)
    assert masks["▲"] != masks["▼"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_icons_are_rgba_88(platform: str) -> None:
    icon = Image.open(ASSETS / "icons" / f"{platform}.png")
    assert icon.mode == "RGBA"
    assert icon.size == (88, 88)
    for corner in ((0, 0), (87, 0), (0, 87), (87, 87)):
        assert icon.getpixel(corner)[3] == 0, (platform, corner)
    # Значок не пустой: в центре есть непрозрачные пиксели.
    assert icon.getchannel("A").getbbox() is not None


def _components(alpha: Image.Image) -> list[tuple[int, int, int, int, int]]:
    """Связные области alpha > 127: (левый, правый, верх, низ, число пикселей)."""
    width, height = alpha.size
    pixels = alpha.load()
    seen = [[False] * width for _ in range(height)]
    found = []
    for y in range(height):
        for x in range(width):
            if pixels[x, y] <= 127 or seen[y][x]:
                continue
            stack, count = [(x, y)], 0
            left, right, top, bottom = x, x, y, y
            seen[y][x] = True
            while stack:
                cx, cy = stack.pop()
                count += 1
                left, right = min(left, cx), max(right, cx)
                top, bottom = min(top, cy), max(bottom, cy)
                for nx, ny in ((cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)):
                    if 0 <= nx < width and 0 <= ny < height and not seen[ny][nx] \
                            and pixels[nx, ny] > 127:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            found.append((left, right, top, bottom, count))
    return sorted(found)


def test_logo_is_real_mark() -> None:
    logo = Image.open(ASSETS / "logo.png")
    assert logo.mode == "RGBA"
    assert logo.width == 400
    assert logo.width / logo.height == pytest.approx(589/344, abs=0.02)
    parts = _components(logo.getchannel("A"))
    assert len(parts) == 3
    assert parts[0][1] < parts[1][0] and parts[1][1] < parts[2][0]
    colours = []
    for left, right, top, bottom, _ in parts:
        colours.append(logo.getpixel(((left+right)//2, (top+bottom)//2))[:3])
    for channel, expected in zip(colours[1], (0x00, 0x82, 0xFE)):
        assert abs(channel-expected) <= 8, colours[1]
    for outer in (colours[0], colours[2]):
        assert all(channel >= 247 for channel in outer), outer


@pytest.mark.parametrize("family", ("Geologica", "Onest", "JetBrainsMono"))
def test_licenses_present(family: str) -> None:
    licence = ASSETS / "fonts" / f"OFL-{family}.txt"
    assert "SIL OPEN FONT LICENSE" in licence.read_text(encoding="utf-8").upper()
