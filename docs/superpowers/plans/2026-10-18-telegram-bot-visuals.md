# Обложки, компактный текст и значки бота — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дайджест и `/week` начинаются с картинки-обложки, нарисованной
ботом, текст под ней компактный и разбит на заметные блоки, меню `/top` явно
показывает выбор и в группе слушается только автора команды.

**Architecture:** Новый модуль `telegram_bot/cover.py`: чистая раскладка
(данные → прямоугольники, проверяется тестами на крайних и случайных
данных) и отдельное рисование Pillow по этим прямоугольникам. Новый модуль
`telegram_bot/emoji.py`: именованные слоты значков с запасным обычным
эмодзи и местом под id кастомного эмодзи. `render.py` переходит на
компактные строки и слоты, сообщения получают необязательную картинку,
которую отправляет `handlers.py` (загрузка один раз, дальше по `file_id`).

**Tech Stack:** Python 3.13 (общий venv API/бота на Сервере 2), Pillow
(новая зависимость, решение владельца), httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-10-18-telegram-bot-visuals-design.md`
(и исходный `docs/superpowers/specs/2026-10-17-telegram-bot-design.md`).

## Global Constraints

- Холст обложки 1280×640, фон `#0d1117`, поля 64 px; зоны шапка / логотип 200×117 справа сверху на одной линии с шапкой / график на всю ширину 1152 px — не пересекаются никогда.
- Название: сначала `shortName`, кегль 64 → 44 pt по реальной ширине (`ImageFont.getlength`), потом обрезка по слову с «…».
- Полосы: линейно от максимума, самая длинная — 70 % дорожки; ненулевой минимум 10 px; ноль — без полосы. Подпись справа, не влезает — внутрь полосы белым; не влезает и туда — без плашки процента.
- Плашка «▲ N %» / «▼ N %» только если прошлое значение есть и > 0; округление до 0 — серая «≈ 0 %». «нет данных» — площадка есть только в прошлом снимке.
- Логотип m-ranked — только настоящие формы `frontend/public/icons/app-icon.svg` (три пути, без тёмного квадрата). Логотипы площадок — `frontend/public/brands/*.svg` без изменений формы и цвета.
- Шрифты Geologica (название, жирный), Onest (подзаголовок), JetBrains Mono (числа), с лицензиями OFL.
- Картинка — только в дайджесте и `/week`; `/top` — без картинки. Подпись к фото — только шапка (≤ 1024 символов, проверяется тестом).
- Меню `/top`: четыре ряда, ✅ у выбранного, ⬜ у остальных; последний ряд — «⬜ Подозрительные» / «✅ Подозрительные». Никаких кастомных эмодзи на кнопках.
- Замок на автора в группах: чужое нажатие → подсказка «Это меню вызвал другой участник — напишите свой /top», сообщение не меняется. Старые кнопки без автора работают для всех.
- Слоты эмодзи: `logo`, `telegram`, `vk`, `max`, `rutube`, `band_ours`, `band_others`, `band_week`, `band_forecast`, `rank_1`, `rank_2`, `rank_3`, `up`, `down`, `promo`, `anomaly`, `spike`, `alert_urgent`. Таблица id пустая до части 2.
- Никаких адресов, портов, ключей, токенов и Telegram ID в репозитории (`AGENTS.md`). Коммиты без `Co-Authored-By`.
- Без регрессий: рисование — только по запросу (`/week`) и раз в неделю (дайджест), вне цикла событий (`asyncio.to_thread`); бот в `MemoryMax=128M`.
- Работа в ветке `feat/telegram-bot-visuals` (поверх `feat/telegram-bot`, PR #40), worktree `.claude/worktrees/telegram-bot`. Прод — только после «делай».

## Review Focus

1. **Шрифт без нужного глифа.** Название с редкими символами (« », №, ё, латиница) или ▲/▼ не должно рисоваться «тофу»-квадратами — тест в Task 2 рисует строку со всеми этими символами и проверяет, что у каждого глифа ненулевая ширина в выбранном шрифте.
2. **Огромные и пустые числа.** 0 у всех площадок, одно значение, 10⁹ рядом с 1 — раскладка не делит на ноль и не выходит за край (крайние наборы в Task 2).
3. **Подпись к фото.** Длинное название вуза в подписи `sendPhoto` укладывается в 1024 символа (тест в Task 5).
4. **Telegram отверг фото для одного получателя.** Остальные получают картинку по `file_id`, этот — текст без картинки; ничего не дублируется (тест в Task 5).
5. **Нажатие старой кнопки после выкатки.** Кнопка без автора работает и не ломает меню (тест в Task 4).

---

## Файлы

- Create `telegram_bot/emoji.py` — слоты значков и вывод `<tg-emoji>`.
- Create `telegram_bot/cover.py` — данные обложки, раскладка, рисование.
- Create `telegram_bot/assets/` — `fonts/*.ttf` + `fonts/OFL-*.txt`, `icons/{telegram,vk,max,rutube}.png`, `logo.png`, `README.md` (откуда и как пересобрать).
- Create `operations/scripts/build-bot-assets.py` — растеризация SVG → PNG (запускается вручную на машине разработчика).
- Modify `telegram_bot/render.py` — компактные строки, слоты, клавиатура ✅/⬜, автор в callback, `Message.photo`.
- Modify `telegram_bot/telegram.py` — `send_photo`.
- Modify `telegram_bot/handlers.py` — отправка сообщений с картинкой, замок на автора, `/week` с обложкой.
- Modify `telegram_bot/content.py` — дайджест с обложкой, значки в «выстрелил»/«накрутке».
- Modify `requirements/api.txt`, `requirements/api.lock` — Pillow.
- Modify `operations/runbooks/TELEGRAM_BOT.md` — внешний вид, ассеты, Pillow при выкатке.
- Tests: `tests/test_telegram_bot_assets.py`, `tests/test_telegram_bot_cover.py`, `tests/test_telegram_bot_emoji.py`, изменения в `tests/test_telegram_bot_render.py`, `tests/test_telegram_bot_handlers.py`, `tests/test_telegram_bot_content.py`, `tests/test_telegram_bot_client.py`.

---

### Task 1: Pillow, шрифты и растеризованные значки

**Files:**
- Modify: `requirements/api.txt`, `requirements/api.lock`
- Create: `telegram_bot/assets/**`, `operations/scripts/build-bot-assets.py`
- Test: `tests/test_telegram_bot_assets.py`

**Interfaces:**
- Produces:
  - `telegram_bot/assets/fonts/Geologica-Bold.ttf`, `Onest-Regular.ttf`, `JetBrainsMono-Medium.ttf`, `JetBrainsMono-Bold.ttf` (статические начертания; если в Google Fonts только переменный шрифт — сохранить переменный и выбирать начертание через `font.set_variation_by_name`, указать в README);
  - `assets/icons/{telegram,vk,max,rutube}.png` — 88×88 RGBA (2× от 44 px);
  - `assets/logo.png` — RGBA, только три пути знака, ширина 400 (2× от 200), пропорции 589:344.
  - Константа `ASSETS = Path(__file__).parent / "assets"` в `telegram_bot/cover.py` (Task 2 создаёт модуль; здесь только файлы).

- [ ] **Step 1: Write the failing tests** `tests/test_telegram_bot_assets.py`:
  - `test_fonts_load_and_have_cyrillic`: каждый TTF открывается `ImageFont.truetype(path, 40)`; `font.getlength("Ёжик №1 «МФТИ»") > 0`.
  - `test_triangles_have_glyphs`: в JetBrains Mono `font.getmask("▲").getbbox()` и `"▼"` не `None` и отличаются от маски заведомо отсутствующего символа `"\U0010FFFD"`. Если глифов нет — тест помечается в README и Task 3 рисует треугольники примитивами; тогда тест проверяет наличие константы `DRAW_TRIANGLES = True` в cover.py (выбрать одно и зафиксировать тестом).
  - `test_icons_are_rgba_88`: каждый PNG — `RGBA`, `(88, 88)`, есть прозрачные пиксели по углам.
  - `test_logo_is_real_mark`: `logo.png` — RGBA, отношение ширины к высоте `589/344 ± 0.02`, ровно три связные непрозрачные области слева направо, средняя — цвета `#0082fe` (± 8 по каналу), крайние — белые.
  - `test_licenses_present`: для каждого семейства шрифтов есть `OFL-<family>.txt`.
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_assets.py -q`. Expected: FAIL (нет Pillow / файлов).
- [ ] **Step 3: Implement.**
  - Pillow: добавить строку в `requirements/api.txt` с комментарием (зачем: обложки бота), пересоздать `requirements/api.lock` скриптом `operations/scripts/generate_python_lock.py` (см. шапку файла), установить в локальный venv.
  - Шрифты — из `github.com/google/fonts` (каталоги `ofl/geologica`, `ofl/onest`, `ofl/jetbrainsmono`), вместе с `OFL.txt`.
  - `build-bot-assets.py`: читает SVG из `frontend/public/brands` и три пути из `frontend/public/icons/app-icon.svg` (без `<rect>` фона), растеризует в PNG указанных размеров. Инструмент растеризации — на выбор (например, `rsvg-convert` или headless-браузер); зависимости скрипта — не в `api.txt`. Сгенерированные PNG коммитятся.
- [ ] **Step 4: Run** тесты. Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): Pillow, шрифты и значки для обложек`.

### Task 2: Данные и раскладка обложки

**Files:**
- Create: `telegram_bot/cover.py`
- Test: `tests/test_telegram_bot_cover.py`

**Interfaces:**
- Consumes: ассеты Task 1; `format_count` из `render.py`.
- Produces:
  - `Row(platform: str, value: int | None, previous: int | None)` — `value=None` значит «нет данных»;
  - `CoverData(title: str, subtitle: str, rows: list[Row])`;
  - `cover_rows(current: dict[str, dict[str, int]], previous: dict[str, dict[str, int]] | None, key: str = "views") -> list[Row]` — правило из спека («Решения автора», п. 1), порядок — по убыванию значения, «нет данных» в конце;
  - `badge(value: int | None, previous: int | None) -> str | None` — `"▲ 12 %"`, `"▼ 5 %"`, `"≈ 0 %"` или `None`;
  - `Box(x: int, y: int, w: int, h: int)` с `intersects(other) -> bool`, `inside(other) -> bool`;
  - `Layout(canvas: Box, header: Box, logo: Box, chart: Box, title: str, title_size: int, items: dict[str, Box])` — `items` — все нарисованные элементы (`"title"`, `"subtitle"`, `"icon:<platform>"`, `"bar:<platform>"`, `"label:<platform>"`, `"badge:<platform>"`);
  - `layout(data: CoverData, measure: Callable[[str, str, int], int]) -> Layout` — `measure(text, font_key, size)` возвращает ширину в px; `font_key` ∈ `{"title", "subtitle", "number"}`;
  - `pil_measure(text, font_key, size) -> int` — реальная мера через шрифты Task 1;
  - константы `WIDTH = 1280`, `HEIGHT = 640`, `MARGIN = 64`, `LOGO_SIZE = (200, 117)`, `TITLE_MAX = 64`, `TITLE_MIN = 44`, `BAR_SHARE = 0.70`, `BAR_MIN = 10`.

- [ ] **Step 1: Write the failing tests:**
  - `test_rows_mapping`: текущая `{"vk": {"views": 6400}, "telegram": {"views": 2100}}`, прошлая `{"max": {"views": 900}, "vk": {"views": 6000}}` → `[Row("vk", 6400, 6000), Row("telegram", 2100, None), Row("max", None, 900)]`; ноль в текущей → `Row(p, 0, …)`.
  - `test_badge`: `badge(112, 100) == "▲ 12 %"`, `badge(95, 100) == "▼ 5 %"`, `badge(1000, 999) == "≈ 0 %"`, `badge(5, 0) is None`, `badge(5, None) is None`, `badge(None, 5) is None`.
  - `test_zones_never_overlap` (основной): параметризация по ~300 наборам — крайние (длинное название 200 символов, `shortName` пустой, 1 строка, 4 строки, все нули, `[10**9, 1, 0, None]`, проценты ±999) и случайные (`random.Random(seed)`, 0–4 площадки, значения 0..10⁹, длина названия 1..120). Для каждого: все `items` внутри `canvas` с полями (`MARGIN`), попарно не пересекаются, `items` из графика внутри `chart`, `"title"`/`"subtitle"` внутри `header`, `logo` не пересекает ни `header`, ни `chart`. Мера — `pil_measure` (реальные шрифты).
  - `test_title_shrinks_then_ellipsis`: «МФТИ» — `title_size == 64`; название, которое влезает только мельче, — `44 <= title_size < 64`; очень длинное — `title_size == 44` и `title.endswith("…")`, обрезано по пробелу.
  - `test_longest_bar_is_70_percent` и `test_tiny_bar_min_10px`, `test_zero_has_no_bar` (`"bar:<p>"` отсутствует).
  - `test_label_moves_inside_when_no_room` и `test_badge_dropped_when_no_room_anywhere` — на искусственной мере `measure`, возвращающей большие ширины.
  - `test_review_focus_glyphs`: каждый символ строки `"«Ёжик» №1 Café ▲▼…"` имеет `pil_measure(ch, key, 40) > 0` во всех трёх шрифтах (или документированная замена для ▲▼ из Task 1).
- [ ] **Step 2: Run** `python -m pytest tests/test_telegram_bot_cover.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** раскладку как чистые вычисления: шапка шириной `WIDTH - 2*MARGIN - LOGO_SIZE[0] - 32`; строки графика центрируются в зоне `chart` с равным шагом; ширина дорожки = ширина `chart` минус значок и отступ.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): раскладка обложки — зоны не пересекаются ни на каких данных`.

### Task 3: Рисование обложки

**Files:**
- Modify: `telegram_bot/cover.py`
- Test: `tests/test_telegram_bot_cover.py`

**Interfaces:**
- Consumes: `layout`, `Layout`, ассеты.
- Produces: `draw(data: CoverData) -> bytes` — PNG; цвета полос — `PLATFORM_COLORS = {"telegram": …, "vk": …, "max": …, "rutube": …}` из `--platform-*` тёмной темы `frontend/app/globals.css`, переведённые в sRGB.

- [ ] **Step 1: Write the failing tests:**
  - `test_draw_png_size`: `Image.open(BytesIO(draw(data)))` — PNG, `(1280, 640)`.
  - `test_background_and_logo_drawn`: пиксель `(5, 5)` — фон `#0d1117` (скруглённые углы допускают прозрачность — тогда проверять `(64, 600)`); в прямоугольнике `layout(...).logo` есть пиксели `#0082fe` ± 8.
  - `test_draw_matches_layout`: в каждом `bar:<p>` центр полосы — цвет площадки ± 10; вне `canvas` с полями — только фон.
  - `test_draw_is_fast_and_small`: на крайнем наборе `draw` < 0.5 с, `tracemalloc` пик < 30 МБ, PNG < 400 КБ.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** рисование по `Layout` (суперсэмплинг 2× и уменьшение `LANCZOS` для гладких скруглений, если нужно); шрифты кэшировать по `(font_key, size)` в модуле (`functools.lru_cache`, ограниченный).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): рисование обложки Pillow по раскладке`.

### Task 4: Слоты значков, компактный текст, меню и замок на автора

**Files:**
- Create: `telegram_bot/emoji.py`
- Modify: `telegram_bot/render.py`, `telegram_bot/handlers.py` (только замок на автора в `_top_callback` и выбор вуза), `telegram_bot/content.py` (`spike_message`, `anomaly_message`)
- Test: `tests/test_telegram_bot_emoji.py`, `tests/test_telegram_bot_render.py`, `tests/test_telegram_bot_handlers.py`, `tests/test_telegram_bot_content.py`

**Interfaces:**
- Produces:
  - `emoji.SLOTS: dict[str, tuple[str, str | None]]` — слот → (запасное эмодзи, id кастомного или `None`); все id пока `None`;
  - `emoji.icon(slot: str) -> str` — `<tg-emoji emoji-id="ID">запасное</tg-emoji>` или запасное; неизвестный слот → `KeyError`;
  - `emoji.band(slot: str, label: str) -> str` — разделитель: значок слота + `<b>LABEL</b>` (до набора — так; позже — до 5 слотов подряд);
  - `render.Message(text: str, keyboard: list[list[dict]] | None = None, photo: bytes | None = None)` — если `photo` задан, `text` — подпись;
  - `render.encode_callback(query: TopQuery, author: int | None = None) -> str` — формат `t|who|platform|period|count|susp[|author]`, author — целое со знаком (для `sender_chat`); `decode_callback(data) -> tuple[TopQuery, int | None] | None`.
  - `render.top_keyboard(query: TopQuery, author: int | None = None)`.

- [ ] **Step 1: Write the failing tests:**
  - emoji: `icon("vk")` без id — запасное эмодзи; с подменённым `SLOTS` — `<tg-emoji emoji-id="1234567890123456789">…</tg-emoji>` с экранированием; все 18 слотов из Global Constraints есть.
  - render, «наши»: в строках нет названия нашего вуза; строка = значок площадки · значок места (1–3) или «4.» · `<a href>`на слове типа`</a>` · ×индекс · просмотры; площадка без постов — `значок + <i>выше нормы постов нет</i>`; подзаголовков площадок нет.
  - render, «все»: строка содержит вуз, «(мы)» у нашего, просмотры есть; дайджест «Другие вузы» — без просмотров, 10 строк, нас нет.
  - render, ленты: в дайджесте по порядку `band_ours`, `band_others`, `band_week`, `band_forecast` (по запасным эмодзи + надписи «НАШИ ЛУЧШИЕ», «ДРУГИЕ ВУЗЫ», «НЕДЕЛЯ», «ПРОГНОЗ»).
  - render, клавиатура: тексты кнопок `"✅ Наши"`, `"⬜ Все вузы"`, …, `"⬜ Подозрительные"` / `"✅ Подозрительные"`; символа `"✓ "` больше нет; 4 ряда.
  - callback: `decode(encode(q, 42)) == (q, 42)`; `decode(encode(q, -1001234567890)) == (q, -1001234567890)`; старый формат без автора → `(q, None)`; ≤ 64 байт на всей сетке с автором `-1009999999999`.
  - handlers (Review Focus 5): в группе нажатие автора правит сообщение; чужое — `answer_callback` с текстом «Это меню вызвал другой участник — напишите свой /top», `edit_message` не вызывается; кнопка без автора — работает для любого; в личке замка нет; клавиатура «Какой из них?» тоже несёт автора; сообщение от анонимного админа (`sender_chat`) — автор `sender_chat.id`.
  - content: `spike_message` начинается с `icon("spike")`, `anomaly_message` — с `icon("anomaly")`.
- [ ] **Step 2: Run** перечисленные файлы тестов. Expected: FAIL.
- [ ] **Step 3: Implement.** Если `render.py` перевалит за ~450 строк — вынести текстовые строки постов в `telegram_bot/lines.py` (разрешено).
- [ ] **Step 4: Run** все `tests/test_telegram_bot_*.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): компактные строки, значки-слоты, ✅/⬜ в меню и замок на автора`.

### Task 5: Отправка обложки в дайджесте и `/week`

**Files:**
- Modify: `telegram_bot/telegram.py`, `telegram_bot/handlers.py`, `telegram_bot/content.py`, `telegram_bot/render.py` (`render_week`, `render_digest` возвращают сообщения с обложкой)
- Test: `tests/test_telegram_bot_client.py`, `tests/test_telegram_bot_handlers.py`, `tests/test_telegram_bot_content.py`, `tests/test_telegram_bot_render.py`

**Interfaces:**
- Consumes: `cover.CoverData`, `cover.cover_rows`, `cover.draw`, `render.Message.photo`.
- Produces:
  - `TelegramClient.send_photo(chat_id: int, photo: bytes | str, caption: str) -> dict` — `bytes` — загрузка (multipart, имя `cover.png`), `str` — `file_id`; `parse_mode=HTML`; те же ошибки, что `send_message`;
  - `render.render_week(...)` и `render.render_digest(...)` принимают `cover: CoverData | None` первым ключевым аргументом и возвращают `list[Message]`, где первое — `Message(text=<подпись-шапка>, photo=None)` до рисования; рисование выполняет вызывающий (`await asyncio.to_thread(cover.draw, data)`) и подставляет `photo`;
  - `Bot.send_all` и `Bot.broadcast_report` умеют `Message.photo`: первому получателю — загрузка байтов, из ответа берётся `file_id` самого большого размера, остальным — по `file_id`; если `send_photo` для получателя упал `TelegramError` (не `BotBlocked`/`CannotInitiate`) — этому получателю уходит только текст следующих сообщений, без картинки.
  - `content.cover_for(bot, our, current, previous) -> CoverData` — название из `dashboard.institutions` (`shortName` → `name`), подзаголовок «<период> · просмотры за неделю».

- [ ] **Step 1: Write the failing tests:**
  - client: `send_photo` с байтами — multipart с полем `photo` и `caption`; со строкой — поле `photo` = file_id; ошибки как у `send_message`.
  - render (Review Focus 3): подпись-шапка для названия из 300 символов ≤ 1024 символов.
  - handlers (Review Focus 4): рассылка трём получателям — у первого загрузка байтов, у двух — `file_id`; если для второго `send_photo` → `TelegramError`, он получает только текст, третий — картинку и текст; ничего не уходит дважды.
  - handlers: `/week` — `send_photo`, затем текст «Неделя к неделе»; если `cover.draw` бросил исключение — только текст, в журнале класс ошибки.
  - content: `build_digest` возвращает первым сообщение с картинкой; `send_digest` доставляет картинку и текст; `/digest` в чат — то же самое одному чату.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** все `tests/test_telegram_bot_*.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(bot): обложка в дайджесте и /week`.

### Task 6: Замер, документация и проверка

**Files:**
- Modify: `operations/runbooks/TELEGRAM_BOT.md`, `telegram_bot/assets/README.md`
- Test: без новых файлов

- [ ] **Step 1: Замер в среде как на сервере.** `docker run --rm --platform linux/amd64 -v "$PWD":/w -w /w python:3.13-slim` — установить `requirements/api.lock` (`pip install --require-hashes --no-deps -r requirements/api.lock`), прогнать `tests/test_telegram_bot_cover.py` и скрипт замера: `draw()` на 20 крайних наборах — p50/p95 времени и пик памяти (`resource.getrusage` / `tracemalloc`). Ожидается: < 0.5 с и < 30 МБ на кадр. Записать числа в описание коммита и в README ассетов.
- [ ] **Step 2: Полный прогон** `python -m pytest -q` локально. Expected: 0 failed.
- [ ] **Step 3: Документация.** `TELEGRAM_BOT.md`: раздел «Внешний вид» (обложка, слоты значков, где таблица id, как подставить id после части 2), шаг выкатки — установка обновлённого `api.lock` в общий venv, проверка `python -c "import PIL"`, замер `draw()` на сервере.
- [ ] **Step 4: Commit** `docs(bot): внешний вид, ассеты и Pillow при выкатке`.
- [ ] **Step 5: Выкатка** — только после «делай» владельца: релиз-оверлей по памяти «Prod release procedure» поверх `mranked-tgbot-26cbcc8-s2-20261018`, установка `api.lock` в общий venv, перезапуск только бота, замер `draw()` на сервере, проверка `/week` и `/digest` в Telegram владельцем.
