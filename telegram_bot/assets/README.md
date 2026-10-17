# Ресурсы обложек Telegram-бота

Обложки 1280x640 рисует Pillow (`telegram_bot/cover.py`) из файлов этого
каталога. Всё нужное лежит в репозитории: ни образ, ни прод ничего не
скачивают и не растеризуют.

## Шрифты (`fonts/`)

Взяты как есть из репозитория <https://github.com/google/fonts> (каталоги
`ofl/geologica`, `ofl/onest`, `ofl/jetbrainsmono`), получены 18.10.2026.
Лицензия SIL OFL 1.1, тексты лицензий рядом: `OFL-<семейство>.txt`.

В Google Fonts этих семейств есть только переменные файлы, поэтому лежат они
же, а нужное начертание выбирается по имени после открытия:

```python
font = ImageFont.truetype(str(ASSETS / "fonts" / "Geologica-Variable.ttf"), size)
font.set_variation_by_name("Bold")
```

| Файл | Начертание (`set_variation_by_name`) | Для чего |
|---|---|---|
| `Geologica-Variable.ttf` | `Bold` | заголовки |
| `Onest-Variable.ttf` | `Regular` | основной текст |
| `JetBrainsMono-Variable.ttf` | `Medium`, `Bold` | числа и подписи |

Ловушка: у Geologica вес по умолчанию `Thin`, без `set_variation_by_name("Bold")`
заголовок получится волосяным. У Onest и JetBrains Mono по умолчанию Regular.
Имена начертаний Pillow возвращает через `font.get_variation_names()` как
`bytes`; `set_variation_by_name` принимает строку.

Символы `▲` и `▼` в JetBrains Mono есть, поэтому рисуются шрифтом, а не
примитивами; это закреплено тестом `test_triangles_have_glyphs`.

## Значки (`icons/`) и знак (`logo.png`)

Собираются скриптом `operations/scripts/build-bot-assets.py` и коммитятся:

- `icons/{telegram,vk,max,rutube}.png`: 88x88 RGBA (2x от 44 px), растр
  официальных SVG из `frontend/public/brands` без изменения формы и цвета;
- `logo.png`: знак m-ranked, три пути из `frontend/public/icons/app-icon.svg`
  (фоновый `<rect>` и обёртка translate/scale отброшены), ширина 400 RGBA
  (2x от 200), пропорции 589:344.

Растеризация идёт внешней программой `rsvg-convert` (librsvg; macOS:
`brew install librsvg`, Debian: `apt install librsvg2-bin`). Это инструмент
разработчика, в `requirements/*.txt` его нет. Перезапускать скрипт нужно
только при смене исходных SVG:

```bash
python3 operations/scripts/build-bot-assets.py
```
