# Редизайн на shadcn/ui — состояние и что доделать

Ветка `feat/shadcn-redesign` от `alpha`. Временный файл: удалить последним коммитом вместе с `legacy.css`.

## Окружение

Репозиторий требует Node 24 и pnpm 11.19.0, системные версии могут быть другими.

```bash
export PATH="/opt/homebrew/opt/node@24/bin:$PATH"
cd frontend
corepack pnpm <команда>     # именно corepack, иначе возьмётся pnpm 10.x
```

## Зафиксированные решения

Все двенадцать приняты явно в ходе опроса перед началом работ.

| # | Решение | Следствие |
|---|---|---|
| 1–2 | **Recharts везде, без исключений**, включая `/compare` | Порог INP для `/compare` перебазируется на факт, а не соблюдается |
| 3 | **Tailwind v4 начисто**; `legacy.css`, `_migration.css`, `manage.module.css` и `visual-parity` удаляются | Пиксельный гейт против Python-UI ликвидируется |
| 4 | Пресет даёт нейтральный UI; `--chart-1..18` **переопределены на разные тона** | Семантика сохранена: реакции зелёный, просмотры синий, комментарии янтарный |
| 5 | **Geologica** (заголовки) + **Montserrat** (текст) через `next/font`, подмножества `cyrillic, latin` | Oxanium из пресета не имеет кириллицы и был бы фолбэком на каждом заголовке |
| 6 | **Всё сразу**, включая `/manage` | — |
| 7 | **Гибрид по риску**: Radix/Base UI там, где нет восстановления истории и CSRF | Нативные `select`/`radio` остаются в фильтрах и формах `/manage` |
| 8 | Тема на `data-theme` + `@custom-variant`, иконка + дропдаун на 3 состояния | Меню темы загружается лениво (−48 КиБ на маршрут) |
| 9 | **Ноль новых зависимостей на анимации** | `tw-animate-css`, встроенная анимация Recharts, свой rAF-счётчик |
| 10 | Гейты **перебазировать, не удалять**; классовые селекторы → `data-testid` | — |
| 11 | **Вся информация на экране**, минимализм через типографику | Ничего не прячется за клик |
| 12 | Ветка + серия коммитов + PR в `alpha` | — |
| — | Финал: поднять Docker с копией прод-базы | `make stand-prodcopy COPY=~/Downloads/m-ranked-pgcopy ENV=~/Downloads/m-ranked-local/prodcopy.env` |

### Запреты, о которых нельзя забыть

- **API не трогать**: `contracts/openapi/*`, `lib/api.ts`, `lib/catalog-api.ts`, `lib/admin-api.ts`, `app/manage/[...path]/route.ts`, `app/export/*`, `app/emoji/*`. `pnpm check:api` должен оставаться зелёным.
- **Функционал не терять.** Русские тексты и `aria-label` сохраняются дословно; где кнопка стала иконкой — текст уезжает в `aria-label` и `title`, а не пропадает.

## Замеры, на которых стоят решения

`/compare`, 200 серий × 337 часов, два графика, мобильный профиль, CPU 4×:

| | С точками | Без точек |
|---|---|---|
| SVG-узлов | 136 592 | 1 392 |
| Отрисовка | 8 122 мс | 1 826 мс |
| Клик по легенде | 8 050 мс | 1 430 мс |
| Куча JS | 435 МБ | 199 МБ |

Поэтому на `/compare` точки-маркеры выключены (`dot={false}` + `activeDot`), а на `/publications` оставлены — там их мало и они несут смысл. Клик по легенде на `/compare` всё равно в 9 раз выше порога INP 152 мс; это принято сознательно, `useDeferredValue` держит отзывчивой саму легенду.

Recharts стоит **+102 КиБ gzip** на маршрут с графиком.

## Сделано (4 коммита, все гейты зелёные)

```
9135025 feat(frontend): redraw the overview and institution screens
08a5cf3 feat(frontend): redraw the publication screen on shadcn and Recharts
38b0deb feat(frontend): redraw the comparison screen on shadcn and Recharts
2349966 build(frontend): put Tailwind v4 and the shadcn preset under the app
```

Экраны: `/compare`, `/publications/[id]` (и `/posts`, `/platform-posts`), `/` обзор, `/institutions/[id]`.
Общее: шапка, тема, `components/ui.tsx`, `native-field.tsx`, `platform-chip.tsx`, `animated-number.tsx`.

Состояние гейтов на последнем коммите: lint 0 ошибок, typecheck чисто, 105/105 юнит, **88/88 e2e**, бандл — все маршруты в бюджете.

## Осталось сделать

### 1. Экраны (в порядке убывания объёма)

| Файл | Строк | Чем занят |
|---|---|---|
| `app/manage/admin-console.tsx` | 462 | Админка: формы, таблицы, storage-панель |
| `app/rating/page.tsx` | 278 | Таблица рейтинга, сортировка ссылками, continuation |
| `app/manage/page.tsx` | 70 | Каталог вузов и аккаунтов, матрица платформ |
| `components/account-detail.tsx` | 33 | Карточка аккаунта + список публикаций |
| `components/compare-bars.tsx` | 37 | Полосы сравнения |
| `components/platform-pending.tsx` | 18 | Заглушка неподключённой площадки |
| `components/loading-state.tsx` | 15 | Скелетоны загрузки → `Skeleton` из shadcn |
| `app/error.tsx`, `app/not-found.tsx` | 17 + 12 | Состояния ошибок |
| `app/institutions/[id]/page.tsx` | 78 | Обёртка, осталось немного |
| `components/catalog-forms.tsx` | 25 | Матрица аккаунтов, `window.confirm` → `AlertDialog` |

**Важно про `/rating`:** сортировка серверная, через ссылки с сохранением canonical query и позиции скролла. Не переводить на TanStack DataTable — это сломает continuation и историю. Использовать `Table` из shadcn, заголовки оставить ссылками.

**Важно про `/manage`:** формы нативные, `method="post"` + `action=`, CSRF и `rowVersion` в скрытых полях, работает без JS. Менять только оформление (`Input`, `Button`, `Table`, `NativeSelect`). `window.confirm` в `catalog-forms.tsx` → `AlertDialog`.

### 2. Снос legacy

- Удалить `app/legacy.css`, `app/_migration.css`, `app/manage/manage.module.css`.
- Из `app/globals.css` убрать: объявление слоя `legacy` в первой строке, `@import "./_migration.css" layer(legacy)` и весь блок `@layer legacy { … }` с оградой по голым `button/input/select`, а также нелойерное правило `body { … }` — после сноса оно избыточно.
- Проверить, что переименованные `--legacy-muted` / `--legacy-input` больше нигде не встречаются.

### 3. Оптимизация (обещана и не сделана)

Графики сейчас импортируются статически, из-за чего `/publications/[id]` = 296.64 КиБ при потолке 320. Прежняя Canvas-реализация грузила рендерер динамически (`await import("@/lib/chart-history")`) — **восстановить это**:

- вынести сам плот из `publication-measurements.tsx` и `comparison-chart.tsx` в отдельные модули;
- загружать их через `next/dynamic`, оставив тулбар (легенду и переключатель масштаба) в первом загруженном чанке, чтобы контролы были интерактивны сразу;
- после этого пересчитать и **ужать** оба бюджета в `scripts/bundle-budget.mjs` до факта + ~15% (сейчас `CHART_BUDGET` = 320 КиБ поставлен с запасом «на вырост»).

### 4. Гейты и документация

- `scripts/mobile-performance.mts`: перезаписать пороги по фактическому замеру. Особо: INP для `/compare` недостижим (см. таблицу выше) — вписать реальное значение и оставить комментарий, что это принятое следствие перехода на SVG-рендерер.
- `scripts/visual-parity.mts` и `evidence/` от пиксельной парности — удалить вместе с `pnpm test:visual` в `package.json` и `@types/pngjs`, `pixelmatch`, `pngjs` в зависимостях, если больше нигде не нужны.
- `frontend/README.md`: примерно 40% текста — утверждения про пиксельную парность с Python-UI и про пороги производительности, которые стали ложными. Переписать честно, не подгоняя историю: старые отчёты не переписывать, а пометить как относящиеся к снятому гейту.

### 5. Финальная проверка

```bash
corepack pnpm check     # lint + typecheck + check:api + unit + e2e + build + bundle
cd .. && make stand-prodcopy COPY=~/Downloads/m-ranked-pgcopy ENV=~/Downloads/m-ranked-local/prodcopy.env
```

Затем открыть PR в `alpha`.

## Ловушки, на которые уже наступили

1. **`Card` и `CardTitle` из shadcn — это `div`.** Панель перестаёт быть `region`, заголовок перестаёт быть заголовком. В `components/ui/card.tsx` добавлен проп `as`; для смысловых панелей писать `<Card as="section">` и `<CardTitle as="h2">`.
2. **Цвета графиков нельзя использовать как цвет текста.** Ramp рассчитан на линии (3:1), текст требует 4.5:1. Для смыслового текста есть `--success` и `--warning`, проверенные и на белом, и на собственном 12–15% тинте.
3. **Base UI ≠ Radix.** Вместо `asChild` — проп `render`. `ToggleGroup` принимает массив значений даже при одиночном выборе. `getAriaLabel` у слайдера живёт на ручке, а не на корне (в `components/ui/slider.tsx` проброшен вручную).
4. **axe меряет страницу в момент CSS-перехода** и видит смешанные цвета, которых нет ни в одной теме. Тест ждёт завершения анимаций, а смена темы сделана мгновенной через `data-theme-switching`.
5. **`legacy.css` красит голые `button`/`input` прямым объявлением**, что бьёт наследуемый цвет вариантов `ghost`/`outline` независимо от порядка слоёв. Пока legacy жив, своим не-shadcn кнопкам ставить явный `bg-transparent`.
6. **Папки с префиксом `_` в App Router не маршрутизируются** — если понадобится временная страница для замеров, называть без подчёркивания.
7. **Tailwind-утилиты выигрывают у слоя `legacy`, но не у прямых объявлений на голых элементах** — это разные механизмы, слои тут не помогают.
