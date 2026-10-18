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

## Замер отрисовки

`operations/scripts/measure-bot-cover.py` рисует `draw()` на 20 наборах (12
крайних, 8 случайных с фиксированным зерном): три прохода прогрева, затем пять
проходов по 20 кадров = 100 замеров. Норма: p95 < 0,5 с, рост RSS после
прогрева < 10 МБ, пик < 120 МБ (потолок юнита бота 128 МБ).

Эталон от 18.10.2026: `python:3.13-slim`, `--platform linux/amd64`, зависимости
из `requirements/api.lock` через `pip install --require-hashes --no-deps`
(Pillow 13.0.0, Python 3.13.16), три запуска подряд. Контейнер шёл на Mac с
arm64 под эмуляцией x86_64, поэтому время завышено, на сервере ожидается
быстрее.

| Показатель | Значение |
|---|---|
| время кадра p50 | 45-47 мс |
| время кадра p95 | 63-70 мс |
| время кадра max | 65-106 мс (разовый выброс в одном запуске из трёх) |
| PNG | до 45 КБ |
| RSS после импорта | 34,8 МБ |
| RSS после прогрева | 46,1-46,3 МБ |
| рост RSS за 100 кадров после прогрева | 0,0 МБ |

Для справки, нативный запуск на macOS (arm64, Python 3.13.5): p50 31 мс,
p95 42 мс, пик 64 МБ (аллокатор macOS выходит на плато выше, чем glibc). После
выкатки те же числа снимаются на сервере тем же скриптом и дописываются сюда.
