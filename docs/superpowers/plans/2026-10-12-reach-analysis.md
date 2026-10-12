# Анализ охватов (этап 1) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Новые признаки поста (пакет просмотров, Telegram сквозь «1.2K», видео ВК) и четыре аккаунтные находки по просмотрам, проверенные на локальной копии БД «до/после», слепыми карточками и синтетикой.

**Architecture:** Всё внутри существующего анализатора `anomaly_analysis/v2`: признаки поста — в `linear_feed` и подготовке рядов, сводка поста `tail_ledger` получает v5 с часами притока, аккаунтные находки по охватам — новый модуль `reach_findings.py`, вызываемый ночным `account_tail_job`. Проверка — две копии локальной БД, `backfill`/`account_tail_job` с фиксированным временем `--as-of`, скрипты сравнения, карточек и синтетики в `research/reach-audit-2026-10/`.

**Tech Stack:** Python 3.13, numpy, psycopg 3, pytest, PostgreSQL 18 в Docker (`mranked-local-db`).

**Spec:** `docs/superpowers/specs/2026-10-12-reach-analysis-design.md`

## Global Constraints

- Прод не трогается: ни БД, ни выкатки, ни миграций; миграция `0079` — только локальные копии.
- Адреса, порты, ключи — никогда в репозиторий (`AGENTS.md`).
- Без регрессий скорости: `benchmarks/anomaly_throughput.py` p50/p95 не хуже базы; время `account_tail_job` и размер `tail_ledger` замерены до и после.
- Уровень 2 — почти без ложных; сомнительное — сила < 0,7 (уровень 1); уровень 3 — однозначное (решение владельца 07.10).
- Терминология ADR-006: «признак», «необычность»; слово «накрутка» в коде и текстах не появляется.
- Коммиты — без строки `Co-Authored-By` (правило владельца).
- Работа — в worktree `.claude/worktrees/reach-audit`, ветка `research/reach-audit-2026-10`; основной checkout не трогать (там работают другие сессии).
- Локальная БД: контейнер `mranked-local-db`, база-шаблон `mranked_prod_20261008` (прод на 07.10 23:40 UTC), суперпользователь `mranked_bootstrap` по сокету; для TCP — временный `local_probe` с паролем, удалить после.
- Пороги признаков поста подбираются только на постах 01–21.09; карточки и итоговые цифры — по 22.09–07.10; после разметки пороги не меняются.
- Новые виды находок: `view_packs`, `view_waves`, `level3_share`, `flat_daily_views`; `METHOD_VERSION = "account-findings-v4"`.

## Review Focus

- Пост ВК, опубликованный за 1–2 ч до границы ленты (22–26 ч): обрыв просмотров на 24-м часу — граница ленты, не пакет. Тест в Task 5.
- Пост, чей пакет совпал с пробелом сбора (нет замеров 1–3 ч): признак не ставится, вывод «нет данных». Тест в Task 5.
- Telegram-пост, где значение «12K» стоит 3 часа подряд при реальном росте: отображаемое плато — не обрыв, если допуск ±1 000 больше роста. Тест в Task 4.
- Аккаунт с 10+ постами в один час из-за общего события площадки (например, массовое обновление счётчиков): волна по стене не должна засчитываться, если тот же час — у большинства аккаунтов площадки. Тест в Task 8.
- Аккаунт с менее чем 20 постами в окне: `level3_share` не выносится. Тест в Task 7.

---

## Карта файлов

| Файл | Отвечает за |
|---|---|
| `anomaly_analysis/backfill.py` | `--as-of` (Task 1) |
| `anomaly_analysis/account_tail_job.py` | `--as-of`, вызов `reach_findings` (Tasks 1, 9) |
| `anomaly_analysis/v2/domain.py` | `PostSeries.publication_type` (Task 2) |
| `anomaly_analysis/v2/store.py` | чтение типа записи, читатели признаков и уровней окна (Tasks 2, 7) |
| `anomaly_analysis/v2/series.py` | видео ВК как «не аудитория», ограниченный ряд просмотров Telegram, `growth_bounds` (Tasks 2, 3) |
| `anomaly_analysis/v2/levels.py` | код качества `vk_video_views` (Task 2) |
| `anomaly_analysis/v2/detectors/engagement_regime.py`, `late_engagement.py` | пропуск видео ВК (Task 2) |
| `anomaly_analysis/v2/detectors/linear_feed.py` | поздняя ветка по ограниченному ряду, короткая подача просмотров (Tasks 4, 5) |
| `anomaly_analysis/v2/tail_ledger.py` | v5: `surges` (Task 6) |
| `anomaly_analysis/v2/reach_findings.py` (новый) | `view_packs`, `level3_share`, `view_waves`, `flat_daily_views` и их тексты (Tasks 7, 8) |
| `anomaly_analysis/v2/account_findings.py` | делегирование текстов новых видов, версия метода (Task 9) |
| `db/migrations/0079_account_finding_reach_kinds.sql` | новые виды в проверке `kind` (Task 9) |
| `research/reach-audit-2026-10/scripts/eval_*.py`, `eval_setup.sh` | прогоны, сравнение, синтетика, карточки (Tasks 10–12) |
| `research/reach-audit-2026-10/VALIDATION.md` | критерии, цифры, решения (Tasks 10–12) |

Тесты: `tests/test_anomaly_backfill.py`, `tests/test_anomaly_series.py`, `tests/test_anomaly_reach_feed.py` (новый), `tests/test_tail_ledger.py`, `tests/test_reach_findings.py` (новый), `tests/test_anomaly_store_postgres.py`.

Запуск тестов: `python -m pytest <файл> -q` из корня worktree.

---

### Task 1: Фиксированное время анализа и базовый прогон

**Files:**
- Modify: `anomaly_analysis/backfill.py` (аргументы, `now`, `moment`)
- Modify: `anomaly_analysis/account_tail_job.py` (`main`)
- Create: `research/reach-audit-2026-10/scripts/eval_setup.sh`
- Test: `tests/test_anomaly_backfill.py`, `tests/test_account_tail.py`

**Interfaces:**
- Produces: `backfill.parse_as_of(value: str | None) -> datetime` (UTC, aware); `account_tail_job.computed_for_from(as_of: str | None) -> date`; CLI `--as-of 2026-10-08T00:00:00+00:00` у обоих.

- [ ] **Step 1: Тесты**

```python
# tests/test_anomaly_backfill.py (добавить)
from datetime import datetime, timezone
from anomaly_analysis.backfill import parse_as_of

def test_as_of_defaults_to_now_and_parses_iso():
    before = datetime.now(timezone.utc)
    assert parse_as_of(None) >= before
    assert parse_as_of("2026-10-08T00:00:00+00:00") == datetime(2026, 10, 8, tzinfo=timezone.utc)

def test_as_of_requires_time_zone():
    import pytest
    with pytest.raises(SystemExit):
        parse_as_of("2026-10-08T00:00:00")
```

```python
# tests/test_account_tail.py (добавить)
from datetime import date
from anomaly_analysis.account_tail_job import computed_for_from

def test_computed_for_is_the_moscow_date_of_as_of():
    # 21:30 UTC 07.10 — уже 08.10 в Москве.
    assert computed_for_from("2026-10-07T21:30:00+00:00") == date(2026, 10, 8)
```

- [ ] **Step 2:** `python -m pytest tests/test_anomaly_backfill.py tests/test_account_tail.py -q` — FAIL (`ImportError`).

- [ ] **Step 3: Реализация**

В `backfill.py`:

```python
def parse_as_of(value: str | None) -> datetime:
    """Момент анализа: по умолчанию сейчас; для проверки на копии — фиксированный."""
    if value is None:
        return datetime.now(timezone.utc)
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise SystemExit("--as-of needs a time zone, e.g. 2026-10-08T00:00:00+00:00")
    return moment.astimezone(timezone.utc)
```

В `main()`: `parser.add_argument("--as-of", help="Analyse as of this ISO moment (local copies only)")`; `now = parse_as_of(arguments.as_of)`; внутри цикла `moment = now if arguments.as_of else datetime.now(timezone.utc)`.

В `account_tail_job.py`:

```python
def computed_for_from(as_of: str | None) -> date:
    """Сутки расчёта — московская дата момента: по умолчанию сейчас."""
    from .backfill import parse_as_of
    return parse_as_of(as_of).astimezone(MOSCOW).date()
```

В `main()`: `argparse` с `--as-of`; `computed_for = computed_for_from(arguments.as_of)`.

- [ ] **Step 4:** тесты — PASS.

- [ ] **Step 5: Скрипт копий БД** `research/reach-audit-2026-10/scripts/eval_setup.sh`:

```bash
#!/bin/bash
# Две копии локальной БД для прогонов «до/после». Прод не используется.
# usage: eval_setup.sh base|cand
set -euo pipefail
name="mranked_eval_$1"
psql_() { docker exec -i mranked-local-db psql -U mranked_bootstrap -X -v ON_ERROR_STOP=1 "$@"; }
psql_ -d postgres -c "DROP DATABASE IF EXISTS $name"
psql_ -d postgres -c "CREATE DATABASE $name TEMPLATE mranked_prod_20261008"
echo "created $name"
```

Запустить `bash research/reach-audit-2026-10/scripts/eval_setup.sh base`.

- [ ] **Step 6: Базовый прогон (текущий код, только `--as-of`)**

```bash
docker exec mranked-local-db psql -U mranked_bootstrap -d postgres -c "CREATE ROLE local_probe LOGIN SUPERUSER PASSWORD '<случайный>'"
export ANOMALY_DATABASE_URL="postgresql://local_probe:<пароль>@127.0.0.1:55432/mranked_eval_base"
export MRANKED_STORAGE_PATH="$TMPDIR"
python -m anomaly_analysis.backfill --days 40 --as-of 2026-10-08T00:00:00+00:00 --redetect-synchrony 2>&1 | tail -3
python -m anomaly_analysis.account_tail_job --as-of 2026-10-08T00:00:00+00:00
```

Записать в `VALIDATION.md` раздел «База»: время backfill, время `account_tail_job`, `SELECT avg(pg_column_size(tail_ledger)) FROM analytics.post_anomaly_state`, `python benchmarks/anomaly_throughput.py` (p50/p95).

- [ ] **Step 7: Commit**

```bash
git add anomaly_analysis/backfill.py anomaly_analysis/account_tail_job.py tests/test_anomaly_backfill.py tests/test_account_tail.py research/reach-audit-2026-10/scripts/eval_setup.sh research/reach-audit-2026-10/VALIDATION.md
git commit -m "feat(anomalies): --as-of for backfill and account findings; baseline run on a local copy"
```

---

### Task 2: Видео ВК — просмотры не аудитория поста

**Files:**
- Modify: `anomaly_analysis/v2/domain.py` (`PostSeries`), `anomaly_analysis/v2/store.py` (`SERIES`, `series_from_rows`), `anomaly_analysis/v2/series.py` (`views_belong_to_source`), `anomaly_analysis/v2/levels.py` (коды качества), `anomaly_analysis/v2/detectors/engagement_regime.py` (`detect`), `anomaly_analysis/v2/detectors/late_engagement.py` (`detect`)
- Test: `tests/test_anomaly_series.py`, `tests/test_anomaly_levels.py`

**Interfaces:**
- Produces: `PostSeries.publication_type: str | None = None` (последнее поле с умолчанием); `series.views_not_audience_reason(series) -> str | None` — `"repost_source_counter"` | `"vk_video_views"` | `None`; `views_belong_to_source(series)` = причина не `None`.

- [ ] **Step 1: Тесты**

```python
# tests/test_anomaly_series.py (добавить)
from datetime import datetime, timedelta, timezone
from uuid import UUID
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.series import views_belong_to_source, views_not_audience_reason

def _series(platform="vk", kind="video", repost=False):
    start = datetime(2026, 9, 10, 9, tzinfo=timezone.utc)
    at = tuple(start + timedelta(minutes=5 * i) for i in range(1, 4))
    return PostSeries(UUID(int=1), UUID(int=2), platform, start, repost, at,
                      {Metric.VIEWS: (10, 20, 30), Metric.REACTIONS: (5, 9, 12)}, publication_type=kind)

def test_vk_video_views_are_not_the_post_audience():
    assert views_not_audience_reason(_series()) == "vk_video_views"
    assert views_belong_to_source(_series())

def test_other_vk_types_and_other_platforms_keep_their_views():
    assert not views_belong_to_source(_series(kind="photo"))
    assert not views_belong_to_source(_series(platform="telegram"))
    assert not views_belong_to_source(_series(kind=None))
```

```python
# tests/test_anomaly_levels.py (добавить)
from anomaly_analysis.v2.levels import assess, compact

def test_vk_video_with_reactions_above_views_is_not_flagged_by_view_ratios():
    start = datetime(2026, 9, 6, 9, tzinfo=timezone.utc)
    at = tuple(start + timedelta(minutes=5 * i) for i in range(1, 300))
    views = tuple(100 + 3 * i for i in range(1, 300))           # стена: ~1 000 просмотров
    reactions = tuple(min(850, 6 * i) for i in range(1, 300))   # клип: 850 реакций
    series = PostSeries(UUID(int=1), UUID(int=2), "vk", start, False, at,
                        {Metric.VIEWS: views, Metric.REACTIONS: reactions}, publication_type="video")
    payload = compact(assess(series))
    assert "vk_video_views" in payload["quality"]["codes"]
    assert not any(signal["pattern"] in (5, 6, 7, 10, 13, 14) for signal in payload["signals"])
```

- [ ] **Step 2:** `python -m pytest tests/test_anomaly_series.py tests/test_anomaly_levels.py -q` — FAIL.

- [ ] **Step 3: Реализация**

`domain.py`, в `PostSeries` последним полем:

```python
    # Тип записи площадки (photo, video, album …); None — не прочитан.
    publication_type: str | None = None
```

`store.py`: в `SERIES` в CTE `target` добавить `publication.publication_type` и в итоговый `SELECT` — `target.publication_type`; в `series_from_rows` передать `publication_type=first.get("publication_type")`.

`series.py`, рядом с `views_belong_to_source`:

```python
# Видеозаписи ВК (клипы): просмотры записи на стене не включают ленту клипов,
# где их и смотрят; клип МАИ 06.09 — 850 реакций при 1 140 просмотрах записи.
# Сравнения «реакции против просмотров» у них не говорят ни о чём.
NOT_AUDIENCE_TYPES = {"vk": frozenset({"video"})}


def views_not_audience_reason(series: PostSeries) -> str | None:
    if series.is_repost and series.platform in REPOST_SOURCE_VIEW_PLATFORMS:
        return "repost_source_counter"
    if series.publication_type in NOT_AUDIENCE_TYPES.get(series.platform, ()):
        return "vk_video_views"
    return None


def views_belong_to_source(series: PostSeries) -> bool:
    """Просмотры поста — не его аудитория: репост с чужим счётчиком или видео ВК."""
    return views_not_audience_reason(series) is not None
```

`levels.py`: в словарь текстов кодов качества добавить
`"vk_video_views": "видео ВК: просмотры записи не включают ленту клипов, проверяются только реакции"`;
место, где добавляется `"repost_source_counter"` (строка ~495), заменить на:

```python
    reason = views_not_audience_reason(prepared.series)
    if reason is not None:
        codes.append(reason)
```

(импорт `views_not_audience_reason` из `.series`).

`engagement_regime.detect` и `late_engagement.detect` — первой строкой:

```python
    if views_belong_to_source(prepared.series):
        return ()
```

- [ ] **Step 4:** тесты Task 2 и весь набор анализатора — PASS: `python -m pytest tests -q -k "anomaly or tail or finding"`.

- [ ] **Step 5: Commit**

```bash
git add anomaly_analysis/v2/domain.py anomaly_analysis/v2/store.py anomaly_analysis/v2/series.py anomaly_analysis/v2/levels.py anomaly_analysis/v2/detectors/engagement_regime.py anomaly_analysis/v2/detectors/late_engagement.py tests/test_anomaly_series.py tests/test_anomaly_levels.py
git commit -m "fix(anomalies): VK videos are not judged by wall views against reactions"
```

---

### Task 3: Ограниченный ряд просмотров Telegram

**Files:**
- Modify: `anomaly_analysis/v2/series.py` (`PreparedSeries`, `prepare`, новые `BoundedViews`, `growth_bounds`)
- Test: `tests/test_anomaly_series.py`

**Interfaces:**
- Consumes: `counter_bounds`, `max_display_unit`, `_metric` (уже в `series.py`).
- Produces:
  - `@dataclass BoundedViews: data: MetricSeries; low: np.ndarray; high: np.ndarray` — точки с известными границами (точные: `low == high`), `data.values` — середины;
  - `PreparedSeries.bounded_views: BoundedViews | None = None` — только Telegram и только если есть хоть одна округлённая точка просмотров;
  - `growth_bounds(bounded: BoundedViews, start_age: float, end_age: float) -> tuple[float, float] | None` — наименьший и наибольший возможный прирост; `None`, если по краям нет точек.

- [ ] **Step 1: Тесты**

```python
# tests/test_anomaly_series.py (добавить)
import numpy as np
from anomaly_analysis.v2.series import CollectionCadence, growth_bounds, prepare

def _tg(views, qualities, step_minutes=30):
    start = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    at = tuple(start + timedelta(minutes=step_minutes * (i + 1)) for i in range(len(views)))
    return PostSeries(UUID(int=1), UUID(int=2), "telegram", start, False, at,
                      {Metric.VIEWS: tuple(views), Metric.REACTIONS: tuple(20 for _ in views)},
                      qualities={Metric.VIEWS: tuple(qualities), Metric.REACTIONS: ("exact",) * len(views)})

def test_rounded_telegram_views_get_a_bounded_series():
    views = [800, 950, 1200, 1800, 2400, 3000]
    series = _tg(views, ["exact", "exact", "rounded", "rounded", "rounded", "rounded"])
    prepared = prepare(series, series.observed_at[-1], CollectionCadence())
    bounded = prepared.bounded_views
    assert bounded is not None and bounded.data.values.size == 6
    assert (bounded.low[0], bounded.high[0]) == (800, 800)
    assert (bounded.low[2], bounded.high[2]) == (1100, 1300)   # шаг «1.2K» — сотня в обе стороны
    # Точные просмотры прежние: округлённые в них не попадают.
    assert prepared.metrics[Metric.VIEWS].values.size == 2

def test_growth_bounds_are_conservative_and_monotone():
    series = _tg([800, 950, 1200, 1800, 2400, 3000], ["exact", "exact"] + ["rounded"] * 4)
    bounded = prepare(series, series.observed_at[-1], CollectionCadence()).bounded_views
    ages = bounded.data.ages
    low, high = growth_bounds(bounded, ages[1], ages[5])
    assert low == 3000 - 1000 - 950 and high == 3000 + 1000 - 950   # шаг «3K» — тысяча

def test_exact_only_or_other_platforms_have_no_bounded_series():
    exact = _tg([100, 200, 300], ["exact"] * 3)
    assert prepare(exact, exact.observed_at[-1], CollectionCadence()).bounded_views is None
```

- [ ] **Step 2:** `python -m pytest tests/test_anomaly_series.py -q -k bounded` — FAIL.

- [ ] **Step 3: Реализация** (`series.py`)

```python
@dataclass(frozen=True, slots=True)
class BoundedViews:
    """Просмотры с коридором: точные и показанные «1,2K». Середины — в `data`."""

    data: MetricSeries
    low: np.ndarray
    high: np.ndarray


def growth_bounds(bounded: BoundedViews, start_age: float, end_age: float) -> tuple[float, float] | None:
    """Наименьший и наибольший прирост на [start_age; end_age] при любых значениях в коридорах.

    Счётчик не убывает: в момент t он не ниже нижней границы любой точки до t
    и не выше верхней любой точки после t.
    """
    ages = bounded.data.ages
    before_start = int(np.searchsorted(ages, start_age, side="right")) - 1
    after_start = int(np.searchsorted(ages, start_age, side="left"))
    before_end = int(np.searchsorted(ages, end_age, side="right")) - 1
    after_end = int(np.searchsorted(ages, end_age, side="left"))
    if before_start < 0 or before_end < 0 or after_start >= ages.size or after_end >= ages.size:
        return None
    lowest = max(0.0, float(bounded.low[before_end]) - float(bounded.high[after_start]))
    highest = max(0.0, float(bounded.high[after_end]) - float(bounded.low[before_start]))
    return lowest, highest
```

В `PreparedSeries` последним полем: `bounded_views: "BoundedViews | None" = None`.

В `prepare()` перед `return PreparedSeries(...)`:

```python
    bounded = _bounded_views(series, keep, ages, rows, cadence, scales, covered)
```

и передать `bounded_views=bounded`. Функция:

```python
def _bounded_views(series, keep, ages, rows, cadence, scales, covered) -> BoundedViews | None:
    column = series.values.get(Metric.VIEWS)
    if series.platform not in COMPACT_PLATFORMS or column is None or views_belong_to_source(series):
        return None
    pairs = [counter_bounds(value, quality, uncertain) for value, quality, uncertain in zip(
        column, series.qualities[Metric.VIEWS], series.interval_uncertain)]
    pairs = [pair for pair, active in zip(pairs, keep) if active]
    if not any(pair is not None and pair[0] != pair[1] for pair in pairs):
        return None
    low = np.array([np.nan if pair is None else pair[0] for pair in pairs], dtype=np.float64)[rows]
    high = np.array([np.nan if pair is None else pair[1] for pair in pairs], dtype=np.float64)[rows]
    data = _metric(Metric.VIEWS, ages, (low + high) / 2, series, cadence, scales, covered)
    if data is None:
        return None
    present = ~np.isnan(low)
    return BoundedViews(data, _frozen(low[present]), _frozen(high[present]))
```

- [ ] **Step 4:** `python -m pytest tests/test_anomaly_series.py -q` и `python -m pytest tests -q -k anomaly` — PASS (существующие детекторы `bounded_views` не читают).

- [ ] **Step 5: Commit**

```bash
git add anomaly_analysis/v2/series.py tests/test_anomaly_series.py
git commit -m "feat(anomalies): bounded Telegram view series with conservative growth bounds"
```

---

### Task 4: Поздняя линейная подача по ограниченному ряду

**Files:**
- Modify: `anomaly_analysis/v2/detectors/linear_feed.py` (`detect`, `_judge`, `VERSION = "2.5.0"`)
- Test: `tests/test_anomaly_reach_feed.py` (новый)

**Interfaces:**
- Consumes: `PreparedSeries.bounded_views`, `growth_bounds` (Task 3).
- Produces: признак 1 по просмотрам Telegram с `render["measurementMode"] == "bounded_views"`.

- [ ] **Step 1: Тесты** (`tests/test_anomaly_reach_feed.py`)

```python
"""Пакеты и подача просмотров: короткая с публикации, поздняя сквозь «1.2K»."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.detectors import DetectorContext, linear_feed
from anomaly_analysis.v2.domain import Metric, PostSeries
from anomaly_analysis.v2.series import CollectionCadence, prepare

MSK_NOON = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)   # 12:00 МСК


def tg_display(value: int) -> int:
    """Как Telegram показывает просмотры: три значащие цифры с тысячи."""
    if value < 1000:
        return value
    unit = 10 ** (len(str(value)) - 3)
    return value // unit * unit


def build(platform, rates, *, start=MSK_NOON, step=5, reactions=None, kind="photo", rounded=False,
          per_view=None):
    """Ряд по почасовым темпам просмотров; замер каждые `step` минут."""
    at, views, total = [], [], 0.0
    for minute in range(step, 60 * len(rates) + 1, step):
        total += rates[(minute - 1) // 60] * step / 60
        at.append(start + timedelta(minutes=minute))
        views.append(int(total))
    shown = [tg_display(value) for value in views] if rounded else views
    quality = tuple("rounded" if rounded and value >= 1000 else "exact" for value in views)
    reacts = (reactions if reactions is not None else
              [int(v * per_view) for v in views] if per_view is not None else
              [min(40 + i // 6, 400) for i in range(len(views))])
    return PostSeries(UUID(int=7), UUID(int=8), platform, start, False, tuple(at),
                      {Metric.VIEWS: tuple(shown), Metric.REACTIONS: tuple(reacts)},
                      qualities={Metric.VIEWS: quality, Metric.REACTIONS: ("exact",) * len(views)},
                      publication_type=kind)


def feed_signs(series):
    prepared = prepare(series, series.observed_at[-1], CollectionCadence())
    return [sign for sign in linear_feed.detect(prepared, DetectorContext(series.platform))
            if sign.metric is Metric.VIEWS]


def test_telegram_drip_through_rounded_views_is_found():
    # МИСИС 01.10: ~320/ч к шестому часу, затем ровно 1 200/ч ещё 30 часов
    # (ступенька вверх в 3,75 раза; конец ряда — подача ещё идёт).
    rates = [600, 400, 320, 300, 300, 300] + [1200] * 30
    (sign,) = feed_signs(build("telegram", rates, step=15, rounded=True))
    assert sign.render["measurementMode"] == "bounded_views"


def test_organic_decay_through_rounding_is_not_a_feed():
    # Крупный пост: 3 000 → 300/ч плавно; «13.2K» и т. п. — без ступеньки и обрыва.
    rates = [3000, 2500, 2000, 1500, 1200, 1000, 800] + [300] * 10
    assert feed_signs(build("telegram", rates, step=15, rounded=True)) == []
```

- [ ] **Step 2:** `python -m pytest tests/test_anomaly_reach_feed.py -q` — FAIL (первый тест: признака нет).

- [ ] **Step 3: Реализация** (`linear_feed.py`)

В `detect()` для `Metric.VIEWS` выбирать ряд:

```python
    for metric in METRICS:
        data = prepared.metrics.get(metric)
        bounded = prepared.bounded_views if metric is Metric.VIEWS else None
        if bounded is not None:
            data = bounded.data
        if data is None or data.source_counter:
            continue
        for scale in SCALES:
            grid = data.grids.get(scale)
            if grid is not None and grid.rates.size:
                signs.extend(_scan(prepared, context, metric, data, grid, bounded))
```

`_scan(..., bounded=None)` передаёт `bounded` в `_judge`. В `_judge` после вычисления `after`, `stepped_up`, `stepped_down`, `delta` и перед `make_sign`:

```python
    mode = None
    if bounded is not None:
        growth = growth_bounds(bounded, start_age, end_age)
        if growth is None:
            return None
        delta = growth[0]                                  # наименьший возможный прирост участка
        mean = delta / duration * HOUR
        if stepped_down:
            tail = growth_bounds(bounded, end_age, end_age + AFTER_CELLS * width)
            stepped_down = tail is not None and mean >= STEP_DOWN * max(tail[1] / (AFTER_CELLS * width) * HOUR, 1.0)
        if stepped_up:
            # Фон — наибольший возможный темп за 6 ч до участка (от первого замера).
            first = max(float(bounded.data.ages[0]), start_age - BACKGROUND_WINDOW)
            before = growth_bounds(bounded, first, start_age) if first < start_age else None
            stepped_up = before is not None and mean >= STEP_UP * max(
                before[1] / max(start_age - first, width) * HOUR, 1.0)
        if not stepped_up and not stepped_down:
            return None
        mode = "bounded_views"
    if delta < max(MIN_DELTA[metric], MIN_SHARE * start_value):
        return None
```

(перенести существующую проверку `delta` ниже этого блока), а в `render` добавить `**({"measurementMode": mode} if mode else {})`. Импорт `growth_bounds` из `..series`. `VERSION = "2.5.0"`.

- [ ] **Step 4:** `python -m pytest tests/test_anomaly_reach_feed.py tests/test_anomaly_detectors_absolute.py -q` — PASS.

- [ ] **Step 5: Commit**

```bash
git add anomaly_analysis/v2/detectors/linear_feed.py tests/test_anomaly_reach_feed.py
git commit -m "feat(anomalies): late view feeds are judged through Telegram display rounding"
```

---

### Task 5: Короткая подача просмотров с публикации (пакет)

**Files:**
- Modify: `anomaly_analysis/v2/detectors/linear_feed.py` (новая `_short_views`, константы `VIEW_SHORT_*`)
- Test: `tests/test_anomaly_reach_feed.py`

**Interfaces:**
- Consumes: `bounded_views`, `growth_bounds` (Task 3); `value_at` из `series`.
- Produces: признак 1, метрика `views`, `render["mode"] == "short_views"`, `render["packViews"]`, `render["packReactionsPerK"]`, `render["restReactionsPerK"]`, `render["afterRate"]`. По `mode` его читает `store.read_view_pack_members` (Task 7).

- [ ] **Step 1: Тесты** (добавить в `tests/test_anomaly_reach_feed.py`)

```python
def short(series):
    return [s for s in feed_signs(series) if s.render.get("mode") == "short_views"]


def kosygin(start=MSK_NOON, platform="vk", reactions=None, rounded=False, after=15, per_view=None):
    # ~400/ч три часа с публикации, затем `after`/ч: пакет ~1 200 при органике в десятки.
    return build(platform, [420, 400, 380] + [after] * 21, start=start, reactions=reactions,
                 rounded=rounded, per_view=per_view)


def pack_then_rest(pack_reactions, rest_reactions):
    """Реакции: `pack_reactions` за первые 3 ч, затем ровно до `rest_reactions` сверху."""
    return [round(pack_reactions * min(i, 36) / 36) + round(rest_reactions * max(0, i - 36) / 252)
            for i in range(288)]


def test_view_pack_from_publication_is_pronounced():
    # Обрыв в 6,7 раза (60/ч после), в пакете 2,5 реакции на 1 000, у остального поста ~24.
    (sign,) = short(kosygin(after=60, reactions=pack_then_rest(3, 30)))
    assert 0.75 <= sign.strength < 0.95
    assert 1000 <= sign.render["packViews"] <= 1300


def test_silent_pack_with_hard_stop_is_explicit():
    # Обрыв в 26 раз, в пакете ни одной реакции, остальной пост отвечает как обычно.
    (sign,) = short(kosygin(reactions=pack_then_rest(0, 30)))
    assert sign.strength >= 0.95


def test_pack_without_reactions_to_compare_stays_weak():
    # Реакций на посте нет вовсе: отклик не проверить — только слабый сигнал.
    (sign,) = short(kosygin(reactions=[0] * 288))
    assert sign.strength < 0.7


def test_organic_decay_is_not_a_pack():
    # Живой пост ВК: 400 → 200 → 120 → 80 … — без ровного участка и обрыва.
    assert short(build("vk", [400, 200, 120, 80, 60, 50, 40, 30, 25, 20] + [15] * 14)) == []


def test_pack_with_ordinary_response_is_not_flagged():
    # Попадание в рекомендации: темп ровный, но реакции идут как у остального поста.
    assert all(s.strength < 0.7 for s in short(kosygin(per_view=0.012)))


def test_stop_at_night_is_not_evidence():
    late = datetime(2026, 10, 1, 18, tzinfo=timezone.utc)   # 21:00 МСК, обрыв ~00:00
    assert short(kosygin(start=late)) == []


def test_vk_feed_limit_is_not_a_stop():
    # Ровные 400/ч с 12-го по 22-й час и спад на 22-м: это граница ленты ВК (22–26 ч).
    rates = [60] * 12 + [400] * 10 + [5] * 6
    assert short(build("vk", rates, per_view=0.012)) == []


def test_collection_gap_inside_the_pack_gives_no_sign():
    series = kosygin()
    keep = [i for i, at in enumerate(series.observed_at)
            if not timedelta(hours=1) <= at - series.published_at <= timedelta(hours=2, minutes=30)]
    gapped = PostSeries(series.publication_id, series.account_id, series.platform, series.published_at, False,
                        tuple(series.observed_at[i] for i in keep),
                        {m: tuple(col[i] for i in keep) for m, col in series.values.items()},
                        qualities={m: tuple(col[i] for i in keep) for m, col in series.qualities.items()},
                        publication_type="photo")
    assert short(gapped) == []


def test_rounded_telegram_pack_is_found_through_bounds():
    (sign,) = short(build("telegram", [1500, 1450, 1500] + [30] * 21, rounded=True,
                          reactions=pack_then_rest(1, 30)))
    assert sign.render["measurementMode"] == "bounded_views"
```

- [ ] **Step 2:** `python -m pytest tests/test_anomaly_reach_feed.py -q` — новые FAIL.

- [ ] **Step 3: Реализация** (`linear_feed.py`)

```python
# Короткая подача просмотров с публикации: пакет, заказанный к выходу поста.
# Косыгин в ВК: ~400/ч 2–3 ч с публикации, ~1 000 и обрыв в 25 раз, 2 реакции
# на 1 000 просмотров против 9 у остального поста. Поздняя ветка (MIN_ONSET_AGE
# 6 ч, MIN_DURATION 4 ч) такой пакет не видит.
VIEW_SHORT_SCALE = timedelta(minutes=15)
VIEW_SHORT_ONSET_UNTIL = 12 * HOUR
VIEW_SHORT_CELLS = (8, 40)            # 2–10 ч
VIEW_SHORT_MIN_RATE = 150.0           # в час
VIEW_SHORT_BACKGROUND = 3.0           # темп ≥ трёх фонов
VIEW_SHORT_SPREAD = 2.0               # min/max темпа в пределах ×2 по часам
VIEW_SHORT_MAX_CV = 0.35
VIEW_SHORT_STOP = 5.0
VIEW_SHORT_HARD_STOP = 10.0
VIEW_SHORT_AFTER = 2 * HOUR
VIEW_SHORT_RESPONSE = 1 / 3           # реакций на просмотр в пакете ≤ трети остального поста
VIEW_SHORT_SILENT_PER_K = 1.0
VIEW_SHORT_MIN_REST_REACTIONS = 10
VIEW_SHORT_LEVELS = (0.95, 0.75, 0.6)  # однозначный, выраженный, без проверки отклика
```

`detect()` после `_short_reactions`:

```python
    pack = _short_views(prepared)
    if pack is not None:
        signs.append(pack)
```

Функция:

```python
def _short_views(prepared: PreparedSeries) -> Sign | None:
    bounded = prepared.bounded_views
    data = bounded.data if bounded is not None else prepared.metrics.get(Metric.VIEWS)
    if data is None or data.source_counter:
        return None
    grid = data.grids.get(VIEW_SHORT_SCALE)
    if grid is None or grid.rates.size < VIEW_SHORT_CELLS[0] + 8:
        return None
    width = VIEW_SHORT_SCALE.total_seconds()
    rates = grid.rates * HOUR
    starts = grid.edges[:-1]
    valid = grid.usable & ~grid.negative & (expected_step(prepared, starts) <= width)
    after_cells = int(VIEW_SHORT_AFTER / width)
    published = prepared.series.published_at.timestamp()
    feed_limit = FEED_LIMIT.get(prepared.series.platform)
    best = None
    for begin in np.flatnonzero(starts <= VIEW_SHORT_ONSET_UNTIL):
        for cells in range(VIEW_SHORT_CELLS[1], VIEW_SHORT_CELLS[0] - 1, -1):
            end = begin + cells
            if end + after_cells > rates.size or not valid[begin:end + after_cells].all():
                continue
            run = rates[begin:end]
            mean = float(run.mean())
            hourly = run[: cells // 4 * 4].reshape(-1, 4).mean(axis=1) if cells >= 8 else run
            if (mean < VIEW_SHORT_MIN_RATE or hourly.min() * VIEW_SHORT_SPREAD < hourly.max()
                    or float(run.std()) / mean > VIEW_SHORT_MAX_CV):
                continue
            after = float(rates[end:end + after_cells].mean())
            end_age = float(grid.edges[end])
            clock = int((published + end_age + MSK_OFFSET) // HOUR) % 24
            if (clock not in DAY_HOURS_MSK or after * VIEW_SHORT_STOP > mean
                    or (feed_limit is not None and feed_limit[0] <= end_age <= feed_limit[1])):
                continue
            background = float(rates[max(0, begin - 4):begin].mean()) if begin >= 4 else after
            if mean < VIEW_SHORT_BACKGROUND * max(background, 1.0):
                continue
            best = (int(begin), int(end), mean, after)
            break
        if best is not None:
            break
    if best is None:
        return None
    return _pack_sign(prepared, grid, bounded, *best)


def _pack_sign(prepared, grid, bounded, begin, end, mean, after) -> Sign | None:
    start_age, end_age = float(grid.edges[begin]), float(grid.edges[end])
    duration = end_age - start_age
    mode = None
    if bounded is not None:
        pack = growth_bounds(bounded, start_age, end_age)
        tail = growth_bounds(bounded, end_age, end_age + VIEW_SHORT_AFTER)
        if pack is None or tail is None:
            return None
        views = pack[0]
        mean, after = views / duration * HOUR, tail[1] / VIEW_SHORT_AFTER * HOUR
        if mean < VIEW_SHORT_MIN_RATE or after * VIEW_SHORT_STOP > mean:
            return None
        mode = "bounded_views"
    else:
        views = float(grid.cumulative[end] - grid.cumulative[begin])
    reactions = prepared.metrics.get(Metric.REACTIONS)
    last_age = float(prepared.ages[-1]) if prepared.ages.size else end_age
    r_start, r_end = value_at(reactions, start_age), value_at(reactions, end_age)
    r_last, v_last = value_at(reactions, last_age), float(grid.cumulative[-1])
    strength = VIEW_SHORT_LEVELS[2]
    pack_per_k = rest_per_k = None
    if None not in (r_start, r_end, r_last):
        rest_views = max(1.0, v_last - views)
        rest_reactions = max(0.0, r_last - (r_end - r_start))
        pack_per_k = 1000 * max(0.0, r_end - r_start) / max(views, 1.0)
        rest_per_k = 1000 * rest_reactions / rest_views
        if rest_reactions >= VIEW_SHORT_MIN_REST_REACTIONS:
            if pack_per_k > VIEW_SHORT_RESPONSE * rest_per_k:
                return make_sign(PATTERN, FAMILY, prepared, Metric.VIEWS, 0.5, start_age, end_age,
                                 VIEW_SHORT_SCALE, _pack_formula(views, duration, mean, after, pack_per_k, rest_per_k),
                                 _pack_render(views, mean, after, pack_per_k, rest_per_k, mode),
                                 ("recommendation_feed", "paid_promotion", "site_embed"))
            strength = VIEW_SHORT_LEVELS[1]
            if after * VIEW_SHORT_HARD_STOP <= mean or pack_per_k <= VIEW_SHORT_SILENT_PER_K:
                strength = VIEW_SHORT_LEVELS[0]
    return make_sign(PATTERN, FAMILY, prepared, Metric.VIEWS, strength, start_age, end_age, VIEW_SHORT_SCALE,
                     _pack_formula(views, duration, mean, after, pack_per_k, rest_per_k),
                     _pack_render(views, mean, after, pack_per_k, rest_per_k, mode),
                     ("paid_promotion", "site_embed", "mailing_link"))


def _pack_formula(views, duration, mean, after, pack_per_k, rest_per_k) -> str:
    text = (f"просмотры: +{number(views)} за {age_text(duration)} ровным темпом ≈ {number(mean)}/ч, "
            f"затем {number(after)}/ч")
    if pack_per_k is not None:
        text += (f"; реакций на 1 000 просмотров в участке — {pack_per_k:.1f}, "
                 f"у остального поста — {rest_per_k:.1f}")
    return text + ". Живой приток в первые часы затухает, а не идёт ровно и не обрывается"


def _pack_render(views, mean, after, pack_per_k, rest_per_k, mode) -> dict:
    render = {"kind": "linear", "mode": "short_views", "stepDown": True, "packViews": round(views),
              "slope": round(mean, 3), "afterRate": round(after, 3),
              "packReactionsPerK": None if pack_per_k is None else round(pack_per_k, 2),
              "restReactionsPerK": None if rest_per_k is None else round(rest_per_k, 2)}
    if mode:
        render["measurementMode"] = mode
    return render
```

Импорт `value_at` из `..series`. Сила 0,5 при обычном отклике — уровень 1 (тест `test_pack_with_ordinary_response_is_not_flagged` требует < 0,7).

- [ ] **Step 4:** `python -m pytest tests/test_anomaly_reach_feed.py tests/test_anomaly_detectors_absolute.py tests/test_anomaly_reported_cases_2026_10.py tests/test_obvious_anomaly_regressions.py -q` — PASS. Если падают проверки «честные случаи молчат» — это ложные срабатывания: условия не ослаблять ради теста, разобрать случай.

- [ ] **Step 5: Бюджет времени:** `python -m pytest tests/test_anomaly_detectors_absolute.py -q -k fast` — PASS (детектор укладывается в бюджет поста).

- [ ] **Step 6: Commit**

```bash
git add anomaly_analysis/v2/detectors/linear_feed.py tests/test_anomaly_reach_feed.py
git commit -m "feat(anomalies): short steady view feed from publication (view pack)"
```

---

### Task 6: Сводка поста v5 — часы притока

**Files:**
- Modify: `anomaly_analysis/v2/tail_ledger.py` (`VERSION = 5`, `READABLE_VERSIONS = (3, 4, 5)`, `TailLedger.surges`, `payload`, `ledger_from_payload`, `build_ledger`, новая `_surges`)
- Test: `tests/test_tail_ledger.py`

**Interfaces:**
- Produces: `TailLedger.surges: tuple[tuple[int, int, int], ...] = ()` — `(час UTC с эпохи, просмотры, реакции)`; в payload — `"surges": [[h, v, r], …]` (ключ только если не пусто); `SURGE_MAX = 48`.

- [ ] **Step 1: Тесты**

```python
# tests/test_tail_ledger.py (добавить)
from anomaly_analysis.v2.tail_ledger import SURGE_MAX, build_ledger, ledger_from_payload

def _old_post_with_wave(rounded=False):
    start = datetime(2026, 9, 20, 9, tzinfo=timezone.utc)
    at, views, reactions = [], [], []
    for minute in range(5, 4 * 24 * 60, 30):
        at.append(start + timedelta(minutes=minute))
        base = min(1500, minute)                       # ~1 500 к суткам, потом почти стоит
        wave = 0 if minute < 50 * 60 else min(3, (minute - 50 * 60) // 60 + 1) * 1300
        views.append(base + wave)
        reactions.append(min(60, minute // 30))
    quality = tuple("rounded" if rounded and v >= 1000 else "exact" for v in views)
    shown = tuple(v // 100 * 100 if rounded and v >= 1000 else v for v in views)
    return PostSeries(UUID(int=1), UUID(int=2), "vk" if not rounded else "telegram", start, False, tuple(at),
                      {Metric.VIEWS: shown, Metric.REACTIONS: tuple(reactions)},
                      qualities={Metric.VIEWS: quality, Metric.REACTIONS: ("exact",) * len(at)})

def test_wave_hours_of_an_old_post_are_recorded():
    ledger = build_ledger(_old_post_with_wave())
    assert len(ledger.surges) == 3 and all(views >= 1000 for _, views, _ in ledger.surges)
    again = ledger_from_payload(ledger.payload())
    assert again.surges == ledger.surges

def test_fresh_hours_and_small_growth_are_not_surges():
    ledger = build_ledger(_old_post_with_wave())
    first_day = int((_old_post_with_wave().published_at.timestamp() + 86400) // 3600)
    assert all(hour >= first_day for hour, _, _ in ledger.surges)

def test_version_four_payload_is_read_without_surges():
    payload = {**build_ledger(_old_post_with_wave()).payload(), "v": 4}
    payload.pop("surges", None)
    assert ledger_from_payload(payload).surges == ()

def test_rounded_telegram_surges_use_the_lower_bound():
    ledger = build_ledger(_old_post_with_wave(rounded=True))
    assert ledger.surges and all(views <= 1300 for _, views, _ in ledger.surges)
```

- [ ] **Step 2:** `python -m pytest tests/test_tail_ledger.py -q` — FAIL.

- [ ] **Step 3: Реализация** (`tail_ledger.py`)

```python
VERSION = 5
READABLE_VERSIONS = (3, 4, 5)
# Часы притока (v5) для аккаунтной находки «волны просмотров по стене»:
# календарный час, в который пост старше суток получил не меньше
# max(SURGE_MIN_VIEWS, SURGE_SHARE × просмотров к суткам) по соседним замерам
# не дальше часа друг от друга. Округлённые просмотры Telegram — по нижней
# границе прироста. Хранится не больше SURGE_MAX самых крупных.
SURGE_FROM = DAY
SURGE_UNTIL = 30 * DAY
SURGE_MAX_GAP = HOUR
SURGE_MIN_VIEWS = 100
SURGE_SHARE = 0.15
SURGE_MAX = 48
```

Поле `surges: tuple[tuple[int, int, int], ...] = ()` в `TailLedger`; в `payload()` — `**({"surges": [list(item) for item in self.surges]} if self.surges else {})`; в `ledger_from_payload` — `tuple(tuple(int(x) for x in item) for item in payload.get("surges") or ())`.

В `build_ledger` для не репостов: `surges = _surges(series, joint, early, published, limit)` и передать в `TailLedger(...)`.

```python
def _surges(series: PostSeries, points: list[Point], early: Point | None,
            published: float, limit: float) -> tuple[tuple[int, int, int], ...]:
    if early is None:
        return ()
    threshold = max(SURGE_MIN_VIEWS, SURGE_SHARE * early.views)
    compact = series.platform in ROUNDED_PLATFORMS
    hours: dict[int, list[int]] = {}
    for left, right in zip(points, points[1:]):
        if left.age < SURGE_FROM or right.age > SURGE_UNTIL or right.age - left.age > SURGE_MAX_GAP:
            continue
        if published + right.age > limit:
            break
        unit_left = max_display_unit(left.views) if compact and left.views >= 1000 else 0
        unit_right = max_display_unit(right.views) if compact and right.views >= 1000 else 0
        views = max(0, (right.views - unit_right) - (left.views + unit_left))
        hour = int((published + right.age) // HOUR)
        bucket = hours.setdefault(hour, [0, 0])
        bucket[0] += views
        bucket[1] += max(0, right.reactions - left.reactions)
    found = [(hour, views, reactions) for hour, (views, reactions) in hours.items() if views >= threshold]
    return tuple(sorted(sorted(found, key=lambda item: -item[1])[:SURGE_MAX]))
```

Импорт `max_display_unit` из `.series`. Для точных значений `unit = 0`; `max_display_unit` применяется только к Telegram с тысячи, где точки помечены `rounded` (в `joint` они уже есть, см. `allowed`).

- [ ] **Step 4:** `python -m pytest tests/test_tail_ledger.py tests/test_account_findings.py tests/test_account_tail.py -q` — PASS.

- [ ] **Step 5: Commit**

```bash
git add anomaly_analysis/v2/tail_ledger.py tests/test_tail_ledger.py
git commit -m "feat(anomalies): tail ledger v5 records hours of view surges on old posts"
```

---

### Task 7: Находки `view_packs` и `level3_share`

**Files:**
- Create: `anomaly_analysis/v2/reach_findings.py`
- Modify: `anomaly_analysis/v2/store.py` (`read_view_pack_members`, `read_post_levels`)
- Test: `tests/test_reach_findings.py` (новый), `tests/test_anomaly_store_postgres.py`

**Interfaces:**
- Consumes: `AccountFinding` из `account_findings`.
- Produces:
  - `@dataclass PostLevel: publication_id: UUID; account_id: UUID; platform: str; published_at: datetime; level: int; patterns: frozenset[int]; view_pack: bool`
  - `view_pack_findings(posts: Sequence[PostLevel], computed_for: date) -> list[AccountFinding]`
  - `level3_findings(posts: Sequence[PostLevel], computed_for: date) -> list[AccountFinding]`
  - `store.read_post_levels(start: datetime, end: datetime) -> list[dict]` — ключи как у `PostLevel`, `patterns` — список, `view_pack` — bool.
  - `REACH_KINDS = ("view_packs", "view_waves", "level3_share", "flat_daily_views")`, `TITLES`, `ALTERNATIVES`, `summary(f)`, `headline(f)`, `figure(f)`.

- [ ] **Step 1: Тесты** (`tests/test_reach_findings.py`)

```python
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from anomaly_analysis.v2.reach_findings import PostLevel, level3_findings, view_pack_findings

TODAY = date(2026, 10, 8)


def posts(account: int, count: int, *, platform="vk", step_hours=7, **_):
    """count чистых постов через `step_hours`, с 08.09."""
    start = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)
    return [PostLevel(UUID(int=account * 10_000 + i), UUID(int=account), platform,
                      start + timedelta(hours=step_hours * i), 0, frozenset(), False) for i in range(count)]


def spread(account, count, k, **kw):
    """k постов из count, равномерно по окну."""
    items = posts(account, count, **kw)
    marked = set(range(0, count, max(1, count // k)))
    return [PostLevel(p.publication_id, p.account_id, p.platform, p.published_at,
                      3 if i in marked and kw.get("level3") else p.level,
                      frozenset((9, 14)) if i in marked and kw.get("level3") else frozenset(),
                      i in marked and bool(kw.get("packs"))) for i, p in enumerate(items)]


def cohort(n=12, count=60):
    return [p for a in range(2, 2 + n) for p in spread(a, count, 1, level3=1)]


def test_many_level3_posts_in_both_halves_are_a_persistent_finding():
    (finding,) = [f for f in level3_findings(cohort() + spread(1, 80, 40, level3=1), TODAY)
                  if f.account_id == UUID(int=1)]
    assert finding.kind == "level3_share" and finding.status == 2 and len(finding.members) == 40


def test_level3_of_a_single_pattern_is_at_most_status_one():
    items = [PostLevel(p.publication_id, p.account_id, p.platform, p.published_at, p.level,
                       frozenset({9}) if p.level == 3 else frozenset(), False)
             for p in spread(1, 80, 40, level3=1)]
    (finding,) = [f for f in level3_findings(cohort() + items, TODAY) if f.account_id == UUID(int=1)]
    assert finding.status == 1


def test_few_posts_give_no_level3_finding():
    assert not [f for f in level3_findings(cohort() + spread(1, 15, 10, level3=1), TODAY)
                if f.account_id == UUID(int=1)]


def test_repeated_view_packs_are_a_finding():
    (finding,) = [f for f in view_pack_findings(cohort() + spread(1, 80, 25, packs=1), TODAY)
                  if f.account_id == UUID(int=1)]
    assert finding.kind == "view_packs" and finding.status == 2


def test_packs_in_one_week_only_are_not_persistent():
    items = spread(1, 80, 80, packs=1)
    items = [PostLevel(p.publication_id, p.account_id, p.platform, p.published_at, 0, frozenset(),
                       p.view_pack and p.published_at < datetime(2026, 9, 15, tzinfo=timezone.utc)) for p in items]
    found = [f for f in view_pack_findings(cohort() + items, TODAY) if f.account_id == UUID(int=1)]
    assert all(f.status == 1 for f in found)
```

- [ ] **Step 2:** `python -m pytest tests/test_reach_findings.py -q` — FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Реализация** (`reach_findings.py`)

```python
"""Аккаунтные находки по охватам: пакеты и волны просмотров, суточный ритм, сводка уровня 3.

Считаются ночным `account_tail_job` рядом с `account_findings` по тем же
правилам: окно 30 суток, пороги относительно других аккаунтов площадки без
самого аккаунта, статус 1 «необычный», 2 — «устойчиво необычный»
(держится в обеих половинах окна). Необычность, а не доказательство (ADR-006).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import quantiles
from typing import Any, Iterable, Sequence
from uuid import UUID

from .account_findings import WINDOW_DAYS, AccountFinding, _halves_by_time

REACH_KINDS = ("view_packs", "view_waves", "level3_share", "flat_daily_views")
TITLES = {
    "view_packs": "Повторяющиеся пакеты просмотров",
    "view_waves": "Волны просмотров по стене",
    "level3_share": "Много постов с признаками искусственной активности",
    "flat_daily_views": "Просмотры без суточного ритма",
}
ALTERNATIVES = {
    "view_packs": "Регулярное платное продвижение записей; встраивание на сайт или рассылка со ссылкой",
    "view_waves": "Подборка или рекомендация площадки; виджет стены на сайте",
    "level3_share": "Сводка признаков постов, новых свидетельств не добавляет; методика может систематически "
                    "ошибаться на особом формате аккаунта",
    "flat_daily_views": "Аудитория в нескольких часовых поясах; круглосуточная трансляция на экраны",
}

PACK_MIN_POSTS = 5
PACK_SHARE = 0.15
PACK_STRONG_SHARE = 0.25
L3_MIN_POSTS = 20
L3_SHARE = 0.15
L3_WEAK_SHARE = 0.10
L3_HALF_SHARE = 0.10
L3_MIN_PATTERNS = 2


@dataclass(frozen=True, slots=True)
class PostLevel:
    publication_id: UUID
    account_id: UUID
    platform: str
    published_at: datetime
    level: int
    patterns: frozenset[int]
    view_pack: bool


def _window(posts: Iterable[PostLevel], computed_for: date) -> dict[UUID, list[PostLevel]]:
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account: dict[UUID, list[PostLevel]] = {}
    for post in posts:
        if start <= post.published_at.date() < computed_for:
            by_account.setdefault(post.account_id, []).append(post)
    return by_account


def _p90_without(values: dict[UUID, float], platform_of: dict[UUID, str], account: UUID) -> float:
    others = [value for other, value in values.items()
              if other != account and platform_of[other] == platform_of[account]]
    if len(others) < 2:
        return 0.0
    return quantiles(others, n=10, method="inclusive")[-1]


def view_pack_findings(posts: Sequence[PostLevel], computed_for: date) -> list[AccountFinding]:
    by_account = _window(posts, computed_for)
    start = computed_for - timedelta(days=WINDOW_DAYS)
    share = {account: sum(p.view_pack for p in items) / len(items) for account, items in by_account.items()}
    platform = {account: items[0].platform for account, items in by_account.items()}
    result = []
    for account, items in by_account.items():
        members = [p for p in items if p.view_pack]
        cohort = _p90_without(share, platform, account)
        if len(members) < PACK_MIN_POSTS or share[account] < max(PACK_SHARE, cohort):
            continue
        halves = _halves_by_time(items, start, computed_for)
        steady = share[account] >= PACK_STRONG_SHARE and all(any(p.view_pack for p in half) for half in halves)
        metrics = {"posts": len(items), "packs": len(members), "share": round(share[account], 3),
                   "cohortP90": round(cohort, 3)}
        result.append(AccountFinding(account, platform[account], "view_packs", 2 if steady else 1, start,
                                     computed_for, metrics, tuple(p.publication_id for p in members)))
    return result


def level3_findings(posts: Sequence[PostLevel], computed_for: date) -> list[AccountFinding]:
    by_account = _window(posts, computed_for)
    start = computed_for - timedelta(days=WINDOW_DAYS)
    share = {account: sum(p.level == 3 for p in items) / len(items) for account, items in by_account.items()}
    platform = {account: items[0].platform for account, items in by_account.items()}
    result = []
    for account, items in by_account.items():
        if len(items) < L3_MIN_POSTS:
            continue
        cohort = _p90_without(share, platform, account)
        if share[account] < max(L3_WEAK_SHARE, cohort):
            continue
        members = [p for p in items if p.level == 3]
        patterns = frozenset().union(*(p.patterns for p in members))
        halves = _halves_by_time(items, start, computed_for)
        steady = (share[account] >= max(L3_SHARE, cohort) and len(patterns) >= L3_MIN_PATTERNS
                  and all(half and sum(p.level == 3 for p in half) / len(half) >= L3_HALF_SHARE for half in halves))
        metrics = {"posts": len(items), "level3": len(members), "share": round(share[account], 3),
                   "cohortP90": round(cohort, 3), "patterns": sorted(patterns)}
        result.append(AccountFinding(account, platform[account], "level3_share", 2 if steady else 1, start,
                                     computed_for, metrics, tuple(p.publication_id for p in members)))
    return result
```

В `account_findings.py` добавить (общая для обоих модулей):

```python
def _halves_by_time(items, start: date, end: date) -> tuple[list, list]:
    """Посты первой и второй половины окна по дате публикации (по 15 суток)."""
    middle = start + (end - start) / 2
    return ([p for p in items if p.published_at.date() < middle],
            [p for p in items if p.published_at.date() >= middle])
```

`store.py`:

```python
    def read_post_levels(self, published_after: datetime, published_until: datetime) -> list[dict[str, Any]]:
        """Уровни и номера признаков постов окна; пакет просмотров — признак 1 режима short_views."""
        with self._factory() as connection:
            return connection.execute(
                """SELECT state.publication_id, publication.primary_account_id AS account_id,
                          account.platform::text AS platform, state.published_at, state.level,
                          COALESCE(ARRAY(SELECT DISTINCT (signal->>'pattern')::int
                                           FROM jsonb_array_elements(state.signals) signal
                                          WHERE state.level = 3), '{}') AS patterns,
                          EXISTS (SELECT 1 FROM jsonb_array_elements(state.signals) signal
                                   WHERE (signal->>'pattern')::int = 1 AND signal->>'metric' = 'views'
                                     AND signal->'render'->>'mode' = 'short_views'
                                     AND (signal->>'strength')::numeric >= 0.7) AS view_pack
                     FROM analytics.post_anomaly_state state
                     JOIN ingest.visible_publication publication ON publication.id = state.publication_id
                     JOIN catalog.visible_platform_account account ON account.id = publication.primary_account_id
                    WHERE state.published_at >= %s AND state.published_at < %s
                      AND publication.deleted_at IS NULL AND NOT publication.is_repost""",
                (published_after, published_until)).fetchall()
```

Проверить по `levels.compact`, что сила признака хранится в `signals[].strength`; если ключ другой — использовать фактический (тест Step 4 это поймает).

Тест на Postgres (`tests/test_anomaly_store_postgres.py`, по образцу соседних тестов с фикстурой БД): вставить состояние с сигналом `{"pattern":1,"metric":"views","strength":0.8,"render":{"mode":"short_views"}}` и уровнем 3 — `read_post_levels` возвращает `view_pack=True`, `patterns=[1]`.

- [ ] **Step 4:** `python -m pytest tests/test_reach_findings.py tests/test_anomaly_store_postgres.py -q` — PASS.

- [ ] **Step 5: Commit**

```bash
git add anomaly_analysis/v2/reach_findings.py anomaly_analysis/v2/account_findings.py anomaly_analysis/v2/store.py tests/test_reach_findings.py tests/test_anomaly_store_postgres.py
git commit -m "feat(anomalies): account findings for repeated view packs and many level-3 posts"
```

---

### Task 8: Находки `view_waves` и `flat_daily_views`

**Files:**
- Modify: `anomaly_analysis/v2/reach_findings.py`
- Test: `tests/test_reach_findings.py`

**Interfaces:**
- Consumes: `LedgerPost` (из `account_findings`), `TailLedger.surges` (Task 6), `TailLedger.hours`, `TailLedger.late`.
- Produces: `wave_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]`; `flat_day_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]`.

- [ ] **Step 1: Тесты** (добавить в `tests/test_reach_findings.py`)

```python
from anomaly_analysis.v2.account_findings import LedgerPost
from anomaly_analysis.v2.reach_findings import flat_day_findings, wave_findings
from anomaly_analysis.v2.tail_ledger import Point, TailLedger

BASE = datetime(2026, 9, 8, 9, tzinfo=timezone.utc)


def wall(account, count=60, waves=(), platform="vk", late=(5000, 100)):
    """count постов по 12 ч; волна — (час от BASE, сколько последних постов, просмотров на пост)."""
    items = []
    for i in range(count):
        published = BASE + timedelta(hours=12 * i)
        surges = []
        for at_hour, last_n, views in waves:
            moment = BASE + timedelta(hours=at_hour)
            older = [j for j in range(count) if BASE + timedelta(hours=12 * j) < moment - timedelta(days=1)]
            if i in older[-last_n:]:
                surges.append((int(moment.timestamp() // 3600), views, 0))
        ledger = TailLedger(Point(86400, 1000, 30), Point(4 * 86400, 1200, 32), Point(10 * 86400, 1200 + late[0] // count,
                            32 + late[1] // count), surges=tuple(surges))
        items.append(LedgerPost(UUID(int=account * 10_000 + i), UUID(int=account), platform, published, False, ledger))
    return items


def test_waves_over_the_latest_posts_on_two_weeks_are_persistent():
    items = wall(1, waves=[(24 * 5 + h, 15, 1300) for h in range(10)] + [(24 * 20 + h, 15, 1300) for h in range(6)])
    others = [p for a in range(2, 12) for p in wall(a)]
    (finding,) = [f for f in wave_findings(items + others, TODAY) if f.account_id == UUID(int=1)]
    assert finding.kind == "view_waves" and finding.status == 2 and finding.metrics["latestN"] >= 15


def test_scattered_surges_are_not_a_wave():
    # 12 постов в один час, но не последние подряд: каждый третий из 36.
    items = wall(1)
    hour = int((BASE + timedelta(days=20)).timestamp() // 3600)
    items = [LedgerPost(p.publication_id, p.account_id, p.platform, p.published_at, False,
                        TailLedger(p.ledger.early, p.ledger.start, p.ledger.end,
                                   surges=((hour, 900, 0),) if k % 3 == 0 and k < 36 else ()))
             for k, p in enumerate(items)]
    assert not [f for f in wave_findings(items, TODAY) if f.account_id == UUID(int=1)]


def test_hour_shared_by_most_accounts_of_the_platform_is_not_a_wave():
    hour = 24 * 15
    everyone = [p for a in range(1, 12) for p in wall(a, waves=[(hour, 20, 800)])]
    assert wave_findings(everyone, TODAY) == []


def flat(account, night_share, count=40, platform="max"):
    hours_views = [100] * 24
    for h in range(20, 24):
        hours_views[h] = int(100 * night_share)
    ledger = TailLedger(Point(86400, 500, 10), None, None, hours=(tuple(hours_views), (0,) * 24))
    return [LedgerPost(UUID(int=account * 10_000 + i), UUID(int=account), platform,
                       BASE + timedelta(hours=17 * i), False, ledger) for i in range(count)]


def test_views_without_a_night_trough_are_a_finding():
    others = [p for a in range(2, 12) for p in flat(a, 0.15)]
    (finding,) = [f for f in flat_day_findings(others + flat(1, 0.9), TODAY) if f.account_id == UUID(int=1)]
    assert finding.kind == "flat_daily_views" and finding.metrics["amplitude"] >= 0.5


def test_ordinary_night_trough_is_not_a_finding():
    others = [p for a in range(2, 12) for p in flat(a, 0.15)]
    assert not [f for f in flat_day_findings(others + flat(1, 0.2), TODAY) if f.account_id == UUID(int=1)]
```

- [ ] **Step 2:** `python -m pytest tests/test_reach_findings.py -q` — новые FAIL.

- [ ] **Step 3: Реализация** (`reach_findings.py`)

```python
WAVE_MIN_POSTS = 10
WAVE_LATEST_SHARE = 0.8
WAVE_RESPONSE = 1 / 3
WAVE_PLATFORM_SHARE = 0.5      # час, общий для половины аккаунтов площадки, — событие площадки
WAVE_STRONG_VIEW_SHARE = 0.2
FLAT_MIN_VIEWS = 20_000
FLAT_AMPLITUDE = 0.5
FLAT_COHORT_FACTOR = 1.5
FLAT_WINDOW = 4


def wave_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]:
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account: dict[UUID, list[LedgerPost]] = {}
    for post in posts:
        if start <= post.published_at.date() < computed_for and not post.is_repost:
            by_account.setdefault(post.account_id, []).append(post)
    hours_by_account: dict[UUID, dict[int, list[tuple[LedgerPost, int, int]]]] = {}
    for account, items in by_account.items():
        table: dict[int, list[tuple[LedgerPost, int, int]]] = {}
        for post in items:
            for hour, views, reactions in post.ledger.surges:
                table.setdefault(hour, []).append((post, views, reactions))
        hours_by_account[account] = table
    platform_of = {account: items[0].platform for account, items in by_account.items()}
    accounts_per_platform: dict[str, int] = {}
    for platform in platform_of.values():
        accounts_per_platform[platform] = accounts_per_platform.get(platform, 0) + 1
    busy: dict[tuple[str, int], int] = {}
    for account, table in hours_by_account.items():
        for hour, hits in table.items():
            if len(hits) >= WAVE_MIN_POSTS:
                key = (platform_of[account], hour)
                busy[key] = busy.get(key, 0) + 1
    result = []
    for account, items in by_account.items():
        platform = platform_of[account]
        ordered = sorted(items, key=lambda post: post.published_at, reverse=True)
        late_views = sum((post.ledger.late or (0, 0))[0] for post in items)
        late_reactions = sum((post.ledger.late or (0, 0))[1] for post in items)
        late_rate = late_reactions / late_views if late_views else None
        wave_hours, members, views_in, reactions_in, latest = [], set(), 0, 0, 0
        for hour, hits in hours_by_account[account].items():
            if len(hits) < WAVE_MIN_POSTS:
                continue
            if busy[(platform, hour)] >= max(2, WAVE_PLATFORM_SHARE * accounts_per_platform[platform]):
                continue
            moment = datetime.fromtimestamp(hour * 3600, tz=timezone.utc)
            older = [post for post in ordered if post.published_at <= moment - timedelta(days=1)]
            hit_ids = {post.publication_id for post, _, _ in hits}
            depth = max((index for index, post in enumerate(older) if post.publication_id in hit_ids), default=-1) + 1
            if depth == 0 or len(hit_ids) < WAVE_LATEST_SHARE * depth:
                continue
            hour_views = sum(views for _, views, _ in hits)
            hour_reactions = sum(reactions for _, _, reactions in hits)
            if late_rate is not None and hour_reactions / max(hour_views, 1) > WAVE_RESPONSE * late_rate:
                continue
            wave_hours.append(hour)
            members |= hit_ids
            views_in += hour_views
            reactions_in += hour_reactions
            latest = max(latest, depth)
        if not wave_hours:
            continue
        days = sorted({datetime.fromtimestamp(h * 3600, tz=timezone.utc).date() for h in wave_hours})
        weeks = {day.isocalendar()[:2] for day in days}
        total_views = sum((post.ledger.end or post.ledger.early or Point(0, 0, 0)).views for post in items)
        share = views_in / total_views if total_views else 0.0
        status = 2 if len(weeks) >= 2 or share >= WAVE_STRONG_VIEW_SHARE else 1
        metrics = {"days": len(days), "hours": len(wave_hours), "views": views_in, "reactions": reactions_in,
                   "viewShare": round(share, 3), "latestN": latest, "posts": len(items)}
        result.append(AccountFinding(account, platform, "view_waves", status, start, computed_for, metrics,
                                     tuple(sorted(members, key=str))))
    return result


def _amplitude(items: Sequence[LedgerPost]) -> tuple[float, int, list[int]] | None:
    views = [0] * 24
    for post in items:
        if post.ledger.hours is not None:
            for hour in range(24):
                views[hour] += post.ledger.hours[0][hour]
    total = sum(views)
    if total < FLAT_MIN_VIEWS:
        return None
    windows = [sum(views[(start + k) % 24] for k in range(FLAT_WINDOW)) for start in range(24)]
    quiet = min(range(24), key=lambda start: windows[start])
    return windows[quiet] / max(max(windows), 1), quiet, views


def flat_day_findings(posts: Sequence[LedgerPost], computed_for: date) -> list[AccountFinding]:
    start = computed_for - timedelta(days=WINDOW_DAYS)
    by_account: dict[UUID, list[LedgerPost]] = {}
    for post in posts:
        if start <= post.published_at.date() < computed_for and not post.is_repost:
            by_account.setdefault(post.account_id, []).append(post)
    measured = {account: _amplitude(items) for account, items in by_account.items()}
    values = {account: item[0] for account, item in measured.items() if item is not None}
    platform_of = {account: items[0].platform for account, items in by_account.items()}
    result = []
    for account, item in measured.items():
        if item is None:
            continue
        amplitude, quiet, _ = item
        cohort = _p90_without(values, platform_of, account)
        if amplitude < max(FLAT_AMPLITUDE, FLAT_COHORT_FACTOR * cohort):
            continue
        halves = _halves_by_time(by_account[account], start, computed_for)
        parts = [_amplitude(half) for half in halves]
        steady = all(part is not None and part[0] >= FLAT_AMPLITUDE for part in parts)
        members = [post.publication_id for post in by_account[account] if post.ledger.hours is not None
                   and 2 * sum(post.ledger.hours[0][(quiet + k) % 24] for k in range(FLAT_WINDOW))
                   >= max(sum(post.ledger.hours[0][(s + k) % 24] for k in range(FLAT_WINDOW)) for s in range(24))]
        metrics = {"amplitude": round(amplitude, 3), "quietStartUtc": quiet, "cohortP90": round(cohort, 3),
                   "posts": len(by_account[account])}
        result.append(AccountFinding(account, platform_of[account], "flat_daily_views", 2 if steady else 1,
                                     start, computed_for, metrics, tuple(members)))
    return result
```

Импорты: `LedgerPost` из `.account_findings`, `Point` из `.tail_ledger`, `timezone` из `datetime`. Даты волны — по UTC.

- [ ] **Step 4:** `python -m pytest tests/test_reach_findings.py -q` — PASS.

- [ ] **Step 5: Commit**

```bash
git add anomaly_analysis/v2/reach_findings.py tests/test_reach_findings.py
git commit -m "feat(anomalies): account findings for view waves over the wall and views without a daily rhythm"
```

---

### Task 9: Тексты, ночное задание, миграция

**Files:**
- Modify: `anomaly_analysis/v2/reach_findings.py` (`summary`, `headline`, `figure`)
- Modify: `anomaly_analysis/v2/account_findings.py` (`METHOD_VERSION`, делегирование в `summary`/`headline`/`figure`/`with_texts`, `TITLES`/`ALTERNATIVES`)
- Modify: `anomaly_analysis/account_tail_job.py` (`run_findings`)
- Create: `db/migrations/0079_account_finding_reach_kinds.sql`
- Test: `tests/test_reach_findings.py`, `tests/test_account_tail.py`

**Interfaces:**
- Consumes: всё из Tasks 6–8; `store.read_post_levels`.
- Produces: `run_findings(...)` пишет и прежние, и новые виды одной записью `write_account_findings`.

- [ ] **Step 1: Тесты**

```python
# tests/test_reach_findings.py (добавить)
from anomaly_analysis.v2.account_findings import with_texts

def test_every_reach_kind_has_words_for_the_api():
    items = wall(1, waves=[(24 * 5 + h, 15, 1300) for h in range(10)] + [(24 * 20 + h, 15, 1300) for h in range(6)])
    others = [p for a in range(2, 12) for p in wall(a)]
    found = (wave_findings(items + others, TODAY)
             + level3_findings(cohort() + spread(1, 80, 40, level3=1), TODAY)
             + view_pack_findings(cohort() + spread(1, 80, 25, packs=1), TODAY)
             + flat_day_findings([p for a in range(2, 12) for p in flat(a, 0.15)] + flat(1, 0.9), TODAY))
    assert {f.kind for f in found} == {"view_waves", "level3_share", "view_packs", "flat_daily_views"}
    for finding in found:
        metrics = with_texts(finding).metrics
        assert metrics["title"] and metrics["summary"] and metrics["headline"] and metrics["alternatives"]
        assert "накрут" not in (metrics["summary"] + metrics["headline"]).lower()
```

- [ ] **Step 2:** FAIL (`KeyError` в `with_texts`).

- [ ] **Step 3: Реализация**

`reach_findings.py`:

```python
def summary(finding: AccountFinding) -> str:
    data = finding.metrics
    if finding.kind == "view_packs":
        return (f"У {data['packs']} из {data['posts']} постов за {WINDOW_DAYS} дней просмотры с публикации шли "
                f"ровным темпом и обрывались; у аккаунтов площадки такое бывает не чаще чем у "
                f"{round(100 * data['cohortP90'])} % постов (90-й перцентиль)")
    if finding.kind == "view_waves":
        return (f"В {data['days']} дн. ({data['hours']} ч) последние {data['latestN']} постов одновременно получали "
                f"просмотры почти без реакций: +{data['views']:,} просмотров, {data['reactions']} реакций; "
                f"это {round(100 * data['viewShare'])} % просмотров постов окна").replace(",", " ")
    if finding.kind == "level3_share":
        return (f"{data['level3']} из {data['posts']} постов за {WINDOW_DAYS} дней на уровне 3 "
                f"(признаки {', '.join(map(str, data['patterns']))}); у аккаунтов площадки — до "
                f"{round(100 * data['cohortP90'])} % (90-й перцентиль). Сводка признаков постов")
    return (f"Самые тихие 4 часа суток дают {round(100 * data['amplitude'])} % притока просмотров самых активных; "
            f"у аккаунтов площадки — до {round(100 * data['cohortP90'])} %: живая аудитория ночью спит")


def headline(finding: AccountFinding) -> str:
    data = finding.metrics
    if finding.kind == "view_packs":
        return f"Пакеты просмотров с публикации у {round(100 * data['share'])} % постов"
    if finding.kind == "view_waves":
        return f"Волны просмотров по последним {data['latestN']} постам"
    if finding.kind == "level3_share":
        return f"{round(100 * data['share'])} % постов на уровне 3"
    return "Просмотры идут круглые сутки"


def figure(finding: AccountFinding) -> dict[str, Any] | None:
    data = finding.metrics
    if finding.kind == "view_waves":
        return None
    value = data["amplitude"] if finding.kind == "flat_daily_views" else data["share"]
    label = {"view_packs": "постов с пакетом просмотров", "level3_share": "постов на уровне 3",
             "flat_daily_views": "ночной приток к дневному"}[finding.kind]
    unit = "percent"
    return {"value": value, "typical": data["cohortP90"], "unit": unit, "label": label, "direction": "higher"}
```

`account_findings.py`: `METHOD_VERSION = "account-findings-v4"`; в начале `summary`, `headline`, `figure`:

```python
    if finding.kind in _reach().REACH_KINDS:
        return _reach().summary(finding)        # соответственно headline / figure
```

где `def _reach(): from . import reach_findings; return reach_findings` (ленивый импорт — модули ссылаются друг на друга). Свойство `AccountFinding.title` и `with_texts` берут `TITLES[kind]` / `ALTERNATIVES[kind]`: заменить на `_title(kind)` / `_alternatives(kind)`, которые смотрят в `reach_findings.TITLES`/`ALTERNATIVES` для новых видов.

`account_tail_job.run_findings` — после существующих находок:

```python
    from .v2 import reach_findings
    levels = [reach_findings.PostLevel(row["publication_id"], row["account_id"], row["platform"],
                                       row["published_at"], int(row["level"]), frozenset(row["patterns"] or ()),
                                       bool(row["view_pack"]))
              for row in store.read_post_levels(start, end)]
    reach = (reach_findings.view_pack_findings(levels, computed_for)
             + reach_findings.level3_findings(levels, computed_for)
             + reach_findings.wave_findings(posts, computed_for)
             + reach_findings.flat_day_findings(posts, computed_for))
    result = [with_texts(item) for item in findings(...)] + [with_texts(item) for item in reach]
    store.write_account_findings(result, FINDINGS_VERSION)
```

(`posts` — уже собранный список `LedgerPost`; вызов `write_account_findings` один).

`db/migrations/0079_account_finding_reach_kinds.sql`:

```sql
-- 0079 — аккаунтные находки по охватам: пакеты и волны просмотров, много
-- постов уровня 3, просмотры без суточного ритма (account-findings-v4,
-- anomaly_analysis/v2/reach_findings.py). Таблица не меняется, расширяется
-- перечень видов. Волнам нужны сводки постов версии 5 (часы притока).
--
-- Откат: удалить строки видов и вернуть перечень 0075 —
--   DELETE FROM analytics.account_anomaly_finding
--    WHERE kind IN ('view_packs', 'view_waves', 'level3_share', 'flat_daily_views');
--   и ограничение из 0075.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE analytics.account_anomaly_finding DROP CONSTRAINT IF EXISTS account_anomaly_finding_kind_check;
ALTER TABLE analytics.account_anomaly_finding ADD CONSTRAINT account_anomaly_finding_kind_check
    CHECK (kind = ANY (ARRAY['early_pack'::text, 'regular_reactions'::text, 'late_growth'::text,
                             'late_engagement'::text, 'synchronous_waves'::text,
                             'engagement_shift'::text, 'night_reactions'::text,
                             'view_packs'::text, 'view_waves'::text, 'level3_share'::text,
                             'flat_daily_views'::text]));

COMMIT;
```

- [ ] **Step 4:** `python -m pytest tests -q -k "finding or tail or anomaly"` — PASS; если есть тест контракта API на перечень видов — он остаётся на прежнем перечне (API — этап 2), убедиться, что тест не читает `REACH_KINDS`.

- [ ] **Step 5: Commit**

```bash
git add anomaly_analysis/v2/reach_findings.py anomaly_analysis/v2/account_findings.py anomaly_analysis/account_tail_job.py db/migrations/0079_account_finding_reach_kinds.sql tests/test_reach_findings.py
git commit -m "feat(anomalies): reach findings in the nightly job, words for the API, migration 0079"
```

---

### Task 10: Прогон кандидата, сравнение «до/после», производительность

**Files:**
- Create: `research/reach-audit-2026-10/scripts/eval_diff.py`
- Modify: `research/reach-audit-2026-10/VALIDATION.md`

**Interfaces:**
- Consumes: копии `mranked_eval_base` (Task 1) и `mranked_eval_cand`.
- Produces: `research/reach-audit-2026-10/local_data/diff.csv` (в `.gitignore` уже `local_data/` — проверить; если нет, добавить строку в `research/reach-audit-2026-10/.gitignore`), раздел «До/после» в `VALIDATION.md`.

- [ ] **Step 1: Кандидат**

```bash
bash research/reach-audit-2026-10/scripts/eval_setup.sh cand
docker exec -i mranked-local-db psql -U mranked_bootstrap -d mranked_eval_cand -v ON_ERROR_STOP=1 < db/migrations/0079_account_finding_reach_kinds.sql
export ANOMALY_DATABASE_URL="postgresql://local_probe:<пароль>@127.0.0.1:55432/mranked_eval_cand"
time python -m anomaly_analysis.backfill --days 40 --as-of 2026-10-08T00:00:00+00:00 --redetect-synchrony
time python -m anomaly_analysis.account_tail_job --as-of 2026-10-08T00:00:00+00:00
```

- [ ] **Step 2: `eval_diff.py`** — читает обе БД (DSN из аргументов), пишет CSV и печатает сводку:

```python
"""«До/после»: уровни постов и аккаунтные находки двух прогонов на копиях БД.

usage: python -I eval_diff.py BASE_DSN CAND_DSN OUT_DIR
"""
import csv
import sys
from collections import Counter

import psycopg
from psycopg.rows import dict_row

POSTS = """
SELECT s.publication_id::text id, a.platform::text platform, a.current_username uname, a.id::text account_id,
       s.published_at, s.level,
       COALESCE((SELECT string_agg(DISTINCT (e->>'pattern') || ':' || COALESCE(e->'render'->>'mode', ''), ',')
                   FROM jsonb_array_elements(s.signals) e), '') signs
  FROM analytics.post_anomaly_state s
  JOIN ingest.visible_publication p ON p.id = s.publication_id
  JOIN catalog.visible_platform_account a ON a.id = p.primary_account_id
 WHERE s.published_at >= '2026-09-01' AND s.published_at < '2026-10-08'"""
FINDINGS = "SELECT account_id::text, platform, kind, status FROM analytics.account_anomaly_finding"


def load(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        return ({row["id"]: row for row in connection.execute(POSTS)},
                {(r["account_id"], r["kind"]): r for r in connection.execute(FINDINGS)})


def main(base_dsn, cand_dsn, out):
    base_posts, base_found = load(base_dsn)
    cand_posts, cand_found = load(cand_dsn)
    transitions = Counter()
    with open(f"{out}/diff.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "platform", "uname", "account_id", "published_at", "base", "cand", "base_signs", "cand_signs"])
        for key, cand in cand_posts.items():
            base = base_posts.get(key)
            if base is None:
                continue
            transitions[(cand["platform"], base["level"], cand["level"])] += 1
            if base["level"] != cand["level"] or base["signs"] != cand["signs"]:
                writer.writerow([key, cand["platform"], cand["uname"], cand["account_id"], cand["published_at"],
                                 base["level"], cand["level"], base["signs"], cand["signs"]])
    for (platform, before, after), count in sorted(transitions.items()):
        if before != after:
            print(f"{platform}: {before} -> {after}: {count}")
    print("findings added:", sorted(set(cand_found) - set(base_found)))
    print("findings removed:", sorted(set(base_found) - set(cand_found)))


if __name__ == "__main__":
    main(*sys.argv[1:4])
```

Запуск: `python -I research/reach-audit-2026-10/scripts/eval_diff.py "$BASE" "$CAND" research/reach-audit-2026-10/local_data`.

- [ ] **Step 3: Контрольная группа.** Аккаунты без находок в обоих прогонах с долей уровня 3 не выше медианы площадки (по базе): из `diff.csv` выбрать их посты с ростом уровня; каждый разобрать (график ряда из копии), причину записать в `VALIDATION.md`. Критерий: рост ≤ 0,5 % постов группы, каждый объяснён.

- [ ] **Step 4: Известные эпизоды.** Проверить в кандидате:
  - Косыгин ВК — признак `1:short_views` у большинства из 59 постов;
  - `view_waves` у МИФИ, Губкинского, ГУУ, МИСИС в ВК;
  - признак 1 с `bounded_views` у поста МИСИС TG от 01.10;
  - признак у роликов ГУАП RuTube;
  - `flat_daily_views` у Губкинского MAX.
  Невыполненное — в `VALIDATION.md` с причиной.

- [ ] **Step 5: Производительность.**
  - `python benchmarks/anomaly_throughput.py` на кандидате — p50/p95 против базы.
  - Время `account_tail_job` — против базы.
  - `avg(pg_column_size(tail_ledger))` — против базы.
  Всё в таблицу `VALIDATION.md`. Регрессия — стоп, разбор до продолжения.

- [ ] **Step 6: Commit**

```bash
git add research/reach-audit-2026-10/scripts/eval_diff.py research/reach-audit-2026-10/VALIDATION.md research/reach-audit-2026-10/.gitignore
git commit -m "research(anomalies): candidate run, before/after diff and performance on the local copy"
```

---

### Task 11: Синтетика

**Files:**
- Create: `research/reach-audit-2026-10/scripts/eval_synthetic.py`
- Modify: `research/reach-audit-2026-10/VALIDATION.md`

**Interfaces:**
- Consumes: `store.read_series` (копия кандидата), `levels.assess`, `tail_ledger.build_ledger`, `reach_findings.wave_findings`.
- Produces: таблица чувствительности (размер × темп × площадка) и доля ложных на исходных рядах.

- [ ] **Step 1: Скрипт.**
  - Выборка: 300 постов контрольной группы, по 75 на площадку, зерно 20261012, только посты 22.09–07.10.
  - Для каждого поста: исходный ряд → `assess`, тогда признак 1 `short_views` считается ложным. Затем вживление пакета: к просмотрам с минуты `onset` добавляется `size × min(1, (t − onset)/duration)`; размер {500, 1 000, 2 000, 5 000}, длительность {2, 4, 6} ч, начало {0, 3, 8} ч. Для Telegram после вживления — отображение «три значащие цифры» с `quality='rounded'` с тысячи.
  - Признак найден: есть `pattern=1, metric=views, mode=short_views, strength ≥ 0,7`, и интервал пересекает вживлённый.
  - Волны: 20 аккаунтов контрольной группы. В их сводки добавить `surges` на последние N ∈ {10, 20, 40} постов по 800 просмотров на 6 часов в двух неделях. `wave_findings` — доля найденных; исходные сводки — доля ложных.

  ```python
  def inject(series, onset_h, duration_h, size, rounded):
      published = series.published_at
      views = []
      for at, value in zip(series.observed_at, series.values[Metric.VIEWS]):
          hours = (at - published).total_seconds() / 3600
          add = 0 if hours < onset_h else size * min(1.0, (hours - onset_h) / duration_h)
          views.append(None if value is None else int(value + add))
      quality = series.qualities[Metric.VIEWS]
      if rounded:
          quality = tuple("rounded" if v is not None and v >= 1000 else q for v, q in zip(views, quality))
          views = [v if v is None or v < 1000 else v // 10 ** (len(str(v)) - 3) * 10 ** (len(str(v)) - 3) for v in views]
      return replace(series, values={**series.values, Metric.VIEWS: tuple(views)},
                     qualities={**series.qualities, Metric.VIEWS: tuple(quality)})
  ```

- [ ] **Step 2: Прогон и запись.** Критерии: ≥ 80 % для размера ≥ 1 000 при темпе ≥ 3 фонов; 0 ложных на исходных рядах (и пакетов, и волн).

- [ ] **Step 3: Commit**

```bash
git add research/reach-audit-2026-10/scripts/eval_synthetic.py research/reach-audit-2026-10/VALIDATION.md
git commit -m "research(anomalies): synthetic sensitivity and false-alarm rate for view packs and waves"
```

---

### Task 12: Слепые карточки, разметка, решение

**Files:**
- Create: `research/reach-audit-2026-10/scripts/eval_cards.py`
- Create: `research/reach-audit-2026-10/local_data/cards.html`, `labels.csv` (в git не входят)
- Modify: `research/reach-audit-2026-10/VALIDATION.md`

**Interfaces:**
- Consumes: `diff.csv` (Task 10), копия кандидата.

- [ ] **Step 1: Критерии разметки — в `VALIDATION.md` до генерации карточек** (дословно из спеки 3.4), закоммитить отдельно:

```bash
git add research/reach-audit-2026-10/VALIDATION.md
git commit -m "research(anomalies): labelling criteria fixed before the blind cards"
```

- [ ] **Step 2: `eval_cards.py`.**
  - Страты по спеке 3.5 только из постов 22.09–07.10, не больше 5 карточек с аккаунта, зерно 20261012.
  - Карточка — inline SVG двух кривых (просмотры, реакции) по возрасту, полосы признаков кандидата, числа (возраст, итоговые просмотры и реакции, тип записи, площадка). Без названия, ссылки и страты.
  - Порядок перемешан. Ключ «номер → id, страта» — отдельный `cards_key.csv`, при разметке не открывается.
  - Карточки аккаунтов — миниатюры 6 случайных участников и метрики находки.

- [ ] **Step 3: Разметка** по критериям в `labels.csv`: `card, verdict(заслуживает|не заслуживает|спорно), reason`.

- [ ] **Step 4: Подсчёт** с ключом: доли по стратам, сверка с критериями 3.7. Спорные и все «заслуживает» при статусе 2 — список владельцу.

- [ ] **Step 5: Решение по каждому признаку и находке.**
  - Принять в этап 2.
  - Одна правка: причина записывается до правки, повтор Tasks 10 и 12 на тех же карточках.
  - Опустить до уровня 1.
  Итог — в `VALIDATION.md`.

- [ ] **Step 6: Commit**

```bash
git add research/reach-audit-2026-10/scripts/eval_cards.py research/reach-audit-2026-10/VALIDATION.md
git commit -m "research(anomalies): blind cards, labels and per-sign decisions for stage 2"
```

- [ ] **Step 7: Уборка.** `DROP ROLE local_probe`. Копии `mranked_eval_*` оставить до решения владельца (по 15 ГБ), сообщить об их размере.
