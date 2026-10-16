# Вкладка «Рейтинг»: прогноз М-Рейтинга по соцсетям — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ночной снимок прогноза мест вузов в официальном М-Рейтинге по соцсетям (общий + MAX/VK/Rutube) и вкладка `/rating` с разделами «Прогноз М-Рейтинга» и «Наш рейтинг» (каркас).

**Architecture:** чистый модуль расчёта `api/rating_forecast.py` (без базы) считает баллы площадок, соцсети и места среди 233 вузов. Ночное задание `api.tools.rating_forecast` читает агрегаты публикаций пулом чтения, баллы официального базового месяца — функцией `SECURITY DEFINER`, и записывает снимок в `rating.rating_run`/`rating.rating_result` функцией `ops_and_admin.record_rating_forecast` (миграция 0084). Публичный API (`/api/v1/rating/...`) читает готовый снимок; страница Next.js рисует таблицу и разброс «прогноз против факта».

**Tech Stack:** Python 3.13, FastAPI, psycopg 3, PostgreSQL 18, systemd timers; Next.js 16 / React / TypeScript, openapi-fetch, recharts 3.8, Playwright, node:test.

**Spec:** `docs/superpowers/specs/2026-10-16-rating-forecast-design.md` (исполнитель читает спек и план вместе).

## Global Constraints

- Номер миграции — 0084: 0083 занят `0083_publication_uploaded_at.sql` из PR funpin/m-ranked#26 (дата загрузки Rutube). Если #26 сольют раньше, Rutube-порог можно перевести на `uploaded_at` отдельной версией формулы; в этой ветке — по `published_at`.
- Репозиторий публичный: адреса, порты, ключи и доступы серверов не записываются ни в один файл.
- Коммиты без строки соавторства Claude (`Co-Authored-By` не добавлять).
- Работа только в worktree `.claude/worktrees/rating-forecast`, ветка `feat/rating-forecast`; перед коммитом `git status` и `git branch --show-current`.
- Без регрессий скорости и ресурсов (AGENTS.md): замеры до/после на локальной копии прода `mranked_prod_20261013` (`jit = off`, `random_page_cost = 1.1`); ухудшение — стоп и цифры владельцу.
- Новых кэшей и буферов не добавлять.
- На прод не выкатывать без явного «делай» владельца; Сервер 1 и сборщики не трогать.
- Формула v1 (точные значения): веса MAX 0.4, VK 0.3, Rutube 0.3; публикации 20 → 100; просмотры/контингент VK 0.1 → 3, MAX 0.03 → 0.5; ERV VK 0.005 → 0.04, MAX 0.005 → 0.10; Rutube: меньше 5 видео — 0, иначе `min(100, 12·ln(видео))`, при официальном балле базового месяца > 0 — `0.5·формула + 0.5·официальный`.
- Типичные ошибки по умолчанию (до первого опубликованного месяца со снимком): соцсети 7, MAX 10, VK 9, Rutube 8.
- Месяц — по Москве (`Europe/Moscow`). Посты для просмотров/ERV — опубликованные не позже `as_of − 3 суток` (нет таких — все). Бегущий месяц: публикации × `дней в месяце / прошло дней`; до 7-го дня — `early = true`.
- Места — среди всех вузов официального базового месяца (233): наши 75 с прогнозом, прочие — с баллами последнего опубликованного месяца. Равные баллы — по названию (`casefold`), как в импорте.
- Статусы снимка: `running`, `final`, `published`, `retrospective`. Ретроспектива — только 2026-08 и 2026-09.
- Вкладка «Рейтинг» — после «Сравнения», путь `/rating`, без параметра площадки; раздел «Наш рейтинг» — `/rating/own`.
- Тег сброса кэша ответов — `rating-forecast`.

## Review Focus

1. Вуз, добавленный в каталог посреди месяца (Нижневартовский ГУ: VK создан 15.09, первая публикация 02.09) — площадка должна стать «нет полных данных» с официальным баллом базового месяца, а не 0. Тест — Task 5 (`test_platform_month_marks_accounts_added_mid_month_uncovered`) и Task 1 (`test_uncovered_platform_takes_the_base_official_score`).
2. Вуз без контингента (`students = None`) — подбалл просмотров 0, расчёт не падает. Тест — Task 1 (`test_missing_students_zeroes_only_the_views_subscore`).
3. Первый день месяца (бегущий снимок в 00:30 по Москве) — масштаб конечен, `early = true`, окно `window_end > window_start`. Тест — Task 2 (`test_running_scale_on_the_first_day`) и Task 4 (`test_record_accepts_a_running_snapshot_minutes_after_month_start`).
4. Повторный запуск задания в те же сутки — снимок заменяется, а не дублируется; итоговый снимок опубликованного месяца не трогается. Тест — Task 4 (`test_record_replaces_the_same_moscow_day`, `test_record_never_touches_a_published_run`).
5. Официальный источник без базового месяца (первый месяц года, пустой импорт) — задание пропускает месяц с записью в журнал, не падает целиком и не пишет пустой снимок. Тест — Task 6 (`test_job_skips_a_month_without_a_published_base`).

---

## Файлы

| Файл | Ответственность |
|---|---|
| `api/rating_forecast.py` (новый) | Формула v1, баллы площадок, места, диапазоны, типичные ошибки, месяцы — чистые функции |
| `api/official_rating.py` | + сводный балл в `evidence` |
| `db/migrations/0084_rating_forecast.sql` (новый) | Формула v1, `rating_run.parameters`, функции чтения официальных баллов и записи/финализации снимков |
| `api/sql/rating.py` (новый) | SQL агрегатов задания и читателей API |
| `api/tools/rating_forecast.py` (новый) | Ночное задание и ретроспектива |
| `operations/systemd/m-ranked-target-rating-forecast.{service,timer}` (новые) | Расписание |
| `operations/install/install.py`, `operations/systemd/m-ranked-target.target`, `operations/systemd/m-ranked-target-profile-b-server2.target` | Регистрация таймера |
| `api/routes/rating.py` (новый), `api/app.py` | Публичные маршруты |
| `contracts/openapi/m-ranked-v1.yaml`, `contracts/openapi/m-ranked-v1-client.ts` | Контракт и сгенерированный клиент |
| `frontend/lib/rating.ts` (новый), `frontend/lib/api.ts`, `frontend/lib/types.ts`, `frontend/lib/nav-links.ts`, `frontend/lib/methodology.ts` | Данные и навигация фронта |
| `frontend/app/rating/page.tsx`, `frontend/app/rating/own/page.tsx` (новые) | Страницы |
| `frontend/components/rating/*.tsx` (новые) | Вкладки, таблица, разброс, блок методики |
| `frontend/content/methodology/rating-forecast.mdx` (новый) | Статья методики |
| `research/m-rating-forecast/backtest.py`, `research/m-rating-forecast/README.md` (новые) | Бэктест |
| `docs/OPERATIONS.md` | Таймер и ретроспектива |
| Тесты: `tests/test_rating_forecast.py`, `tests/test_rating_forecast_postgres.py`, `tests/test_rating_routes.py`, `tests/test_operations_profiles.py`, `tests/test_rating_coverage.py`, `frontend/tests/rating.test.ts`, `frontend/tests/browser/rating.spec.ts`, `frontend/tests/browser/parity.spec.ts`, `frontend/tests/api-fixture.mts` | |

## Подготовка окружения (один раз)

- Python: `.venv` основной копии — `/Users/funpin/Documents/ChatGPT/TG-monitoring/.venv/bin/python` (в worktree своей `.venv` нет; запускать из корня worktree, `PYTHONPATH=.`). Ниже `PY` — этот путь.
- Postgres для тестов: по памяти `local-pytest-postgres` — `docker compose -p mranked-pytest -f infra/compose.yaml up -d --wait postgres` с одноразовыми паролями и `POSTGRES_PORT=55439`; база `findings_it` со всеми `db/migrations/*.sql` (включая 0084 после Task 4). `MRANKED_FINDINGS_TEST_DSN` — суперпользователь на `findings_it`.
- Фронт: `cd frontend && npx -y pnpm@11.19.0 install --frozen-lockfile` (pnpm нет в PATH).

---

### Task 1: Чистый расчёт прогноза

**Files:**
- Create: `api/rating_forecast.py`
- Test: `tests/test_rating_forecast.py`

**Interfaces:**
- Produces:
  - `FORMULA_KEY: str = "m-rating-social-forecast"`, `FORMULA_V1: dict[str, Any]`, `PLATFORMS = ("max", "vk", "rutube")`, `CATEGORIES = ("social", "max", "vk", "rutube")`
  - `@dataclass(frozen=True) PlatformMonth(posts: int, viewed_posts: int, views: int, interactions: int, covered: bool)`
  - `@dataclass(frozen=True) InstitutionMonth(institution_id: str, code: str, name: str, students: int | None, platforms: Mapping[str, PlatformMonth])` — нет ключа площадки = нет аккаунта
  - `@dataclass(frozen=True) BaseMonth(period: str, scores: Mapping[str, Mapping[str, float | None]], names: Mapping[str, str])` — `scores[code]` по ключам `social/max/vk/rutube/consolidated`
  - `@dataclass(frozen=True) PlatformScore(score: float, source: str, subscores: dict[str, float], metrics: dict[str, Any])`; `source ∈ {"formula", "fallback", "no_account"}`
  - `subscore(value: float | None, low: float, high: float) -> float`
  - `platform_score(platform: str, month: PlatformMonth | None, students: int | None, official: float | None, *, scale: float = 1.0, formula: Mapping = FORMULA_V1) -> PlatformScore`
  - `rank_in_pool(pool: Mapping[str, float], names: Mapping[str, str]) -> dict[str, int]`
  - `rank_range(code: str, score: float, error: float, pool: Mapping[str, float]) -> tuple[int, int]` — (лучшее, худшее)
  - `forecast(institutions: Iterable[InstitutionMonth], base: BaseMonth, errors: Mapping[str, float], *, scale: float = 1.0, formula: Mapping = FORMULA_V1) -> list[dict]` — строки `{"institutionId", "score", "rank", "explanation"}`, `explanation = {"code", "baseConsolidatedRank", "categories": {cat: {"score", "rank", "rankBest", "rankWorst", "baseRank", "source"}}, "platforms": {p: {"source", "subscores", "metrics"}}}`; `source` категории соцсетей — `"partial"`, если хоть одна площадка `fallback`, иначе `"formula"`
  - `typical_errors(predicted: Mapping[str, Mapping[str, float]], actual: Mapping[str, Mapping[str, float | None]], fallback: Mapping[str, float]) -> dict[str, float]`
  - `evaluate(predicted: Mapping[str, float], actual: Mapping[str, float], predicted_ranks: Mapping[str, int], actual_ranks: Mapping[str, int]) -> dict[str, float]` — `mae`, `rankMedian`, `rankP80`, `spearman`, `top20Hits`, `top20Total`

- [ ] **Step 1: Write the failing tests**

```python
"""Прогноз М-Рейтинга по соцсетям: чистый расчёт без базы."""
from __future__ import annotations

import math

import pytest

from api import rating_forecast as rf


def month(posts=50, viewed=None, views=None, interactions=None, covered=True):
    viewed = posts if viewed is None else viewed
    views = viewed * 1000 if views is None else views
    interactions = views // 50 if interactions is None else interactions
    return rf.PlatformMonth(posts=posts, viewed_posts=viewed, views=views,
                            interactions=interactions, covered=covered)


def test_subscore_is_a_clipped_log_scale():
    assert rf.subscore(20, 20, 100) == 0
    assert rf.subscore(100, 20, 100) == 100
    assert rf.subscore(500, 20, 100) == 100
    assert rf.subscore(0, 20, 100) == 0 and rf.subscore(None, 20, 100) == 0
    assert rf.subscore(math.sqrt(20 * 100), 20, 100) == pytest.approx(50)


def test_vk_score_is_the_mean_of_three_subscores():
    # 100 постов → 100; 3 просмотра на студента → 100; ERV 4 % → 100.
    full = rf.platform_score("vk", month(100, views=100 * 3000, interactions=12000), 1000, None)
    assert full.score == pytest.approx(100) and full.source == "formula"
    # Те же посты и ERV, просмотры на нижней границе → (100 + 0 + 100) / 3.
    low_views = rf.platform_score("vk", month(100, views=100 * 100, interactions=400), 1000, None)
    assert low_views.score == pytest.approx(200 / 3)
    assert set(low_views.subscores) == {"posts", "views", "erv"}


def test_max_uses_its_own_thresholds():
    # 0.5 просмотра на студента — верх шкалы MAX, но середина шкалы VK.
    max_score = rf.platform_score("max", month(100, views=100 * 500, interactions=5000), 1000, None)
    vk_score = rf.platform_score("vk", month(100, views=100 * 500, interactions=5000), 1000, None)
    assert max_score.subscores["views"] == pytest.approx(100)
    assert vk_score.subscores["views"] < 60


def test_missing_students_zeroes_only_the_views_subscore():
    score = rf.platform_score("vk", month(100, views=100 * 3000, interactions=12000), None, None)
    assert score.subscores["views"] == 0
    assert score.subscores["posts"] == pytest.approx(100) and score.subscores["erv"] == pytest.approx(100)
    assert score.metrics["students"] is None


def test_rutube_threshold_and_official_blend():
    assert rf.platform_score("rutube", month(4), None, 60).score == 0
    own = min(100, 12 * math.log(10))
    assert rf.platform_score("rutube", month(10), None, None).score == pytest.approx(own)
    assert rf.platform_score("rutube", month(10), None, 0).score == pytest.approx(own)
    assert rf.platform_score("rutube", month(10), None, 60).score == pytest.approx(0.5 * own + 30)


def test_scale_extrapolates_posts_but_not_views_or_erv():
    plain = rf.platform_score("vk", month(30), 1000, None)
    scaled = rf.platform_score("vk", month(30), 1000, None, scale=2.0)
    assert scaled.subscores["posts"] > plain.subscores["posts"]
    assert scaled.subscores["views"] == plain.subscores["views"]
    assert scaled.subscores["erv"] == plain.subscores["erv"]
    assert scaled.metrics["posts"] == 30 and scaled.metrics["postsExtrapolated"] == 60
    # Порог Rutube проверяется по экстраполированному числу видео.
    assert rf.platform_score("rutube", month(3), None, None, scale=2.0).score > 0


def test_uncovered_platform_takes_the_base_official_score():
    score = rf.platform_score("vk", month(5, covered=False), 1000, 64.1)
    assert (score.score, score.source) == (64.1, "fallback")
    assert rf.platform_score("vk", month(5, covered=False), 1000, None).score == 0


def test_missing_account_scores_zero():
    score = rf.platform_score("max", None, 1000, 80)
    assert (score.score, score.source) == (0, "no_account")


def test_rank_in_pool_breaks_ties_by_name():
    ranks = rf.rank_in_pool({"a": 50, "b": 70, "c": 50}, {"a": "Яблоко", "b": "Б", "c": "Арбуз"})
    assert ranks == {"b": 1, "c": 2, "a": 3}


def test_rank_range_brackets_the_rank():
    pool = {"x": 60.0, "a": 70.0, "b": 64.0, "c": 58.0, "d": 40.0}
    assert rf.rank_range("x", 60.0, 5.0, pool) == (2, 4)
    assert rf.rank_range("x", 60.0, 0.0, pool) == (3, 3)


def base(scores, names=None):
    return rf.BaseMonth(period="Сентябрь 2026", scores=scores,
                        names=names or {code: f"Вуз {code}" for code in scores})


def institution(code, platforms, students=1000):
    return rf.InstitutionMonth(institution_id=f"id-{code}", code=code, name=f"Вуз {code}",
                               students=students, platforms=platforms)


ERRORS = {"social": 7, "max": 10, "vk": 9, "rutube": 8}


def test_balanced_institution_ranks_above_single_platform_leaders():
    """Пункт A: СКФУ — 8-й по соцсетям при 27/38/13 местах на площадках.

    Соцсети — взвешенная сумма баллов: ровно сильный вуз обходит лидеров
    одной площадки. Места не выводятся из мест на площадках.
    """
    others = {
        "max-leader": {"social": 0.4 * 95 + 0.3 * 40 + 0.3 * 0, "max": 95, "vk": 40, "rutube": 0},
        "vk-leader": {"social": 0.4 * 50 + 0.3 * 95 + 0.3 * 0, "max": 50, "vk": 95, "rutube": 0},
        "rt-leader": {"social": 0.4 * 40 + 0.3 * 40 + 0.3 * 95, "max": 40, "vk": 40, "rutube": 95},
    }
    balanced = institution("balanced", {
        "max": month(70, views=70 * 300, interactions=70 * 300 // 25),
        "vk": month(70, views=70 * 1500, interactions=70 * 1500 // 40),
        "rutube": month(40)})
    rows = rf.forecast([balanced], base({**others, "balanced": {"social": 50, "max": 70, "vk": 70, "rutube": 50}}), ERRORS)
    categories = rows[0]["explanation"]["categories"]
    assert categories["social"]["rank"] == 1
    assert all(categories[p]["rank"] > 1 for p in ("max", "vk", "rutube"))
    assert rows[0]["rank"] == categories["social"]["rank"]
    assert rows[0]["score"] == pytest.approx(0.4 * categories["max"]["score"] + 0.3 * categories["vk"]["score"]
                                             + 0.3 * categories["rutube"]["score"], abs=0.01)


def test_forecast_ranks_among_the_whole_official_pool():
    pool = {f"o{i}": {"social": 90 - i, "max": 90 - i, "vk": 90 - i, "rutube": 90 - i} for i in range(10)}
    ours = institution("us", {"max": month(1), "vk": month(1), "rutube": month(0)})
    rows = rf.forecast([ours], base({**pool, "us": {"social": 99, "max": 99, "vk": 99, "rutube": 99}}), ERRORS)
    # Наш прогноз заменяет наш же официальный балл; прочие 10 вузов — выше.
    assert rows[0]["rank"] == 11
    assert rows[0]["explanation"]["categories"]["social"]["baseRank"] == 1


def test_fallback_marks_social_as_partial_and_keeps_platform_source():
    ours = institution("us", {"max": month(60), "vk": month(60, covered=False), "rutube": month(10)})
    rows = rf.forecast([ours], base({"us": {"social": 50, "max": 60, "vk": 64.1, "rutube": 20}}), ERRORS)
    explanation = rows[0]["explanation"]
    assert explanation["categories"]["social"]["source"] == "partial"
    assert explanation["categories"]["vk"]["source"] == "fallback"
    assert explanation["categories"]["vk"]["score"] == pytest.approx(64.1)
    assert explanation["platforms"]["vk"]["source"] == "fallback"


def test_base_consolidated_rank_is_kept_when_present():
    scores = {"a": {"social": 1, "max": 1, "vk": 1, "rutube": 1, "consolidated": 30},
              "us": {"social": 1, "max": 1, "vk": 1, "rutube": 1, "consolidated": 40}}
    rows = rf.forecast([institution("us", {})], base(scores), ERRORS)
    assert rows[0]["explanation"]["baseConsolidatedRank"] == 1
    rows = rf.forecast([institution("us", {})], base({"us": {"social": 1, "max": 1, "vk": 1, "rutube": 1}}), ERRORS)
    assert rows[0]["explanation"]["baseConsolidatedRank"] is None


def test_typical_errors_need_twenty_pairs():
    predicted = {str(i): {"social": 50.0, "max": 50.0, "vk": 50.0, "rutube": 50.0} for i in range(20)}
    actual = {str(i): {"social": 54.0, "max": 40.0, "vk": None, "rutube": 50.0} for i in range(20)}
    errors = rf.typical_errors(predicted, actual, ERRORS)
    assert errors == {"social": 4.0, "max": 10.0, "vk": 9, "rutube": 0.0}
    assert rf.typical_errors(dict(list(predicted.items())[:5]), actual, ERRORS) == ERRORS


def test_evaluate_reports_errors_and_top20():
    predicted = {str(i): float(100 - i) for i in range(30)}
    actual = dict(predicted)
    ranks = {str(i): i + 1 for i in range(30)}
    result = rf.evaluate(predicted, actual, ranks, ranks)
    assert result["mae"] == 0 and result["rankMedian"] == 0 and result["spearman"] == pytest.approx(1)
    assert (result["top20Hits"], result["top20Total"]) == (20, 20)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest tests/test_rating_forecast.py -q`
Expected: FAIL — `ImportError: cannot import name 'rating_forecast' from 'api'`.

- [ ] **Step 3: Write the implementation**

```python
"""Прогноз места вуза в официальном М-Рейтинге по соцсетям.

Модуль считает без базы: на входе метрики площадок наших вузов за месяц и
баллы последнего опубликованного месяца, на выходе — баллы и места.
Формула подобрана 15.10.2026 на сентябре (спек
docs/superpowers/specs/2026-10-16-rating-forecast-design.md): балл площадки —
среднее трёх лог-шкал, соцсети — взвешенная сумма баллов площадок. Места
считаются по сумме баллов, а не по местам на площадках: поэтому ровно сильный
вуз бывает в топ-10 соцсетей, не входя в топ-10 ни одной площадки (СКФУ в
сентябре — 8-й при 27/38/13).
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

FORMULA_KEY = "m-rating-social-forecast"
PLATFORMS = ("max", "vk", "rutube")
CATEGORIES = ("social", "max", "vk", "rutube")

# Совпадает с definition строки rating.formula_definition версии 1 (миграция
# 0084); тест сверяет их. Правка порогов — новая версия, а не правка этой.
FORMULA_V1: dict[str, Any] = {
    "formulaKey": FORMULA_KEY,
    "version": 1,
    "timezone": "Europe/Moscow",
    "weights": {"max": 0.4, "vk": 0.3, "rutube": 0.3},
    "posts": {"low": 20, "high": 100},
    "viewsPerStudent": {"vk": {"low": 0.1, "high": 3}, "max": {"low": 0.03, "high": 0.5}},
    "erv": {"vk": {"low": 0.005, "high": 0.04}, "max": {"low": 0.005, "high": 0.10}},
    "rutube": {"minVideos": 5, "logCoefficient": 12, "officialBlend": 0.5},
    "matureAfterDays": 3,
    "earlyBeforeDay": 7,
    "defaultErrors": {"social": 7, "max": 10, "vk": 9, "rutube": 8},
}


@dataclass(frozen=True)
class PlatformMonth:
    """Площадка вуза за месяц: сумма по всем его аккаунтам на ней."""
    posts: int
    viewed_posts: int
    views: int
    interactions: int
    covered: bool


@dataclass(frozen=True)
class InstitutionMonth:
    institution_id: str
    code: str
    name: str
    students: int | None
    platforms: Mapping[str, PlatformMonth]


@dataclass(frozen=True)
class BaseMonth:
    """Последний опубликованный месяц: баллы всех вузов официального рейтинга."""
    period: str
    scores: Mapping[str, Mapping[str, float | None]]
    names: Mapping[str, str]


@dataclass(frozen=True)
class PlatformScore:
    score: float
    source: str
    subscores: dict[str, float]
    metrics: dict[str, Any]


def subscore(value: float | None, low: float, high: float) -> float:
    if value is None or value <= 0:
        return 0.0
    return min(100.0, max(0.0, 100.0 * math.log(value / low) / math.log(high / low)))


def platform_score(platform: str, month: PlatformMonth | None, students: int | None,
                   official: float | None, *, scale: float = 1.0,
                   formula: Mapping[str, Any] = FORMULA_V1) -> PlatformScore:
    if month is None:
        return PlatformScore(0.0, "no_account", {}, {})
    if not month.covered:
        # Истории за месяц у нас нет целиком — берём официальный балл
        # базового месяца, а не ноль (Нижневартовский ГУ, август 2026).
        return PlatformScore(float(official or 0.0), "fallback", {}, {"posts": month.posts})
    posts = month.posts * scale
    average = month.views / month.viewed_posts if month.viewed_posts else None
    erv = month.interactions / month.views if month.views else None
    metrics = {"posts": month.posts, "postsExtrapolated": round(posts, 1),
               "avgViews": round(average, 1) if average is not None else None,
               "students": students, "erv": round(erv, 5) if erv is not None else None}
    if platform == "rutube":
        rule = formula["rutube"]
        if posts < rule["minVideos"]:
            return PlatformScore(0.0, "formula", {"videos": 0.0}, metrics)
        own = min(100.0, rule["logCoefficient"] * math.log(posts))
        blend = rule["officialBlend"]
        score = blend * own + (1 - blend) * official if official is not None and official > 0 else own
        return PlatformScore(score, "formula", {"videos": own}, metrics)
    views_rule, erv_rule = formula["viewsPerStudent"][platform], formula["erv"][platform]
    per_student = average / students if average is not None and students else None
    subscores = {"posts": subscore(posts, formula["posts"]["low"], formula["posts"]["high"]),
                 "views": subscore(per_student, views_rule["low"], views_rule["high"]),
                 "erv": subscore(erv, erv_rule["low"], erv_rule["high"])}
    return PlatformScore(sum(subscores.values()) / 3, "formula", subscores, metrics)


def rank_in_pool(pool: Mapping[str, float], names: Mapping[str, str]) -> dict[str, int]:
    order = sorted(pool, key=lambda code: (-pool[code], names.get(code, "").casefold()))
    return {code: index for index, code in enumerate(order, 1)}


def rank_range(code: str, score: float, error: float, pool: Mapping[str, float]) -> tuple[int, int]:
    """Места при балле ± типичная ошибка, баллы прочих неизменны."""
    others = [value for other, value in pool.items() if other != code]
    high, low = min(100.0, score + error), max(0.0, score - error)
    return 1 + sum(value > high for value in others), 1 + sum(value >= low for value in others)


def forecast(institutions: Iterable[InstitutionMonth], base: BaseMonth, errors: Mapping[str, float], *,
             scale: float = 1.0, formula: Mapping[str, Any] = FORMULA_V1) -> list[dict[str, Any]]:
    weights = formula["weights"]
    computed = []
    for institution in institutions:
        official = base.scores.get(institution.code, {})
        platforms = {platform: platform_score(platform, institution.platforms.get(platform),
                                              institution.students, official.get(platform),
                                              scale=scale, formula=formula)
                     for platform in PLATFORMS}
        scores = {platform: platforms[platform].score for platform in PLATFORMS}
        scores["social"] = sum(weights[platform] * scores[platform] for platform in PLATFORMS)
        computed.append((institution, platforms, scores))
    ours = {institution.code for institution, _, _ in computed}
    # Официальные названия первыми: так равные баллы упорядочены как в источнике.
    names = {**{institution.code: institution.name for institution, _, _ in computed}, **base.names}
    pools: dict[str, dict[str, float]] = {}
    ranks: dict[str, dict[str, int]] = {}
    base_ranks: dict[str, dict[str, int]] = {}
    for category in (*CATEGORIES, "consolidated"):
        official_pool = {code: float(value[category]) for code, value in base.scores.items()
                         if value.get(category) is not None}
        base_ranks[category] = rank_in_pool(official_pool, base.names)
        if category == "consolidated":
            continue
        pool = {code: score for code, score in official_pool.items() if code not in ours}
        pool.update({institution.code: scores[category] for institution, _, scores in computed})
        pools[category], ranks[category] = pool, rank_in_pool(pool, names)
    rows = []
    for institution, platforms, scores in computed:
        categories = {}
        for category in CATEGORIES:
            best, worst = rank_range(institution.code, scores[category], errors[category], pools[category])
            if category == "social":
                source = "partial" if any(item.source == "fallback" for item in platforms.values()) else "formula"
            else:
                source = platforms[category].source
            categories[category] = {"score": round(scores[category], 2), "rank": ranks[category][institution.code],
                                    "rankBest": best, "rankWorst": worst,
                                    "baseRank": base_ranks[category].get(institution.code), "source": source}
        rows.append({
            "institutionId": institution.institution_id,
            "score": categories["social"]["score"], "rank": categories["social"]["rank"],
            "explanation": {
                "code": institution.code,
                "baseConsolidatedRank": base_ranks["consolidated"].get(institution.code),
                "categories": categories,
                "platforms": {platform: {"source": item.source,
                                         "subscores": {key: round(value, 2) for key, value in item.subscores.items()},
                                         "metrics": item.metrics}
                              for platform, item in platforms.items()},
            },
        })
    return rows


def typical_errors(predicted: Mapping[str, Mapping[str, float]],
                   actual: Mapping[str, Mapping[str, float | None]],
                   fallback: Mapping[str, float]) -> dict[str, float]:
    """MAE балла по категории; меньше 20 пар — значение по умолчанию."""
    result: dict[str, float] = {}
    for category in CATEGORIES:
        pairs = [(scores[category], actual[key][category]) for key, scores in predicted.items()
                 if category in scores and actual.get(key, {}).get(category) is not None]
        result[category] = (round(sum(abs(left - right) for left, right in pairs) / len(pairs), 2)
                            if len(pairs) >= 20 else fallback[category])
    return result


def _spearman(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = list(left)
    order_left = {key: index for index, key in enumerate(sorted(keys, key=lambda key: left[key]))}
    order_right = {key: index for index, key in enumerate(sorted(keys, key=lambda key: right[key]))}
    count = len(keys)
    if count < 2:
        return float("nan")
    squared = sum((order_left[key] - order_right[key]) ** 2 for key in keys)
    return 1 - 6 * squared / (count * (count * count - 1))


def evaluate(predicted: Mapping[str, float], actual: Mapping[str, float],
             predicted_ranks: Mapping[str, int], actual_ranks: Mapping[str, int]) -> dict[str, float]:
    """Метрики бэктеста по общим ключам: ошибка балла, ошибка места, ρ, топ-20."""
    keys = [key for key in predicted if key in actual and key in predicted_ranks and key in actual_ranks]
    rank_errors = sorted(abs(predicted_ranks[key] - actual_ranks[key]) for key in keys)
    top_actual = {key for key in keys if actual_ranks[key] <= 20}
    top_predicted = {key for key in keys if predicted_ranks[key] <= 20}
    return {
        "mae": round(statistics.fmean(abs(predicted[key] - actual[key]) for key in keys), 2),
        "rankMedian": statistics.median(rank_errors),
        "rankP80": rank_errors[int(0.8 * len(rank_errors))] if rank_errors else 0,
        "spearman": round(_spearman({key: predicted[key] for key in keys}, {key: actual[key] for key in keys}), 3),
        "top20Hits": len(top_actual & top_predicted), "top20Total": len(top_actual),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_rating_forecast.py -q`
Expected: PASS (16 passed). Если `test_balanced_institution_ranks_above_single_platform_leaders` не проходит из-за значений фикстуры — подобрать фикстуру (посты/просмотры), не формулу: формула — Global Constraints.

- [ ] **Step 5: Commit**

```bash
git add api/rating_forecast.py tests/test_rating_forecast.py
git commit -m "feat(rating): pure M-Rating social forecast — platform scores, places among 233, ranges"
```

### Task 2: Месяцы прогноза

**Files:**
- Modify: `api/rating_forecast.py` (добавить раздел в конец)
- Test: `tests/test_rating_forecast.py` (добавить тесты)

**Interfaces:**
- Consumes: `FORMULA_V1` из Task 1.
- Produces:
  - `MOSCOW: ZoneInfo`
  - `period_month(period: str) -> date` — «Сентябрь 2026» → `date(2026, 9, 1)`; иначе `ValueError`
  - `period_label(month: date) -> str` — обратное
  - `month_window(month: date) -> tuple[datetime, datetime]` — начало и конец месяца по Москве (aware)
  - `running_scale(month: date, as_of: datetime, formula=FORMULA_V1) -> tuple[float, bool]` — (масштаб публикаций, early)
  - `months_to_forecast(as_of: datetime, published: Collection[date]) -> list[tuple[date, str]]`
  - `base_month_for(month: date, published: Collection[date]) -> date | None` — последний опубликованный раньше `month`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date, datetime, timezone


def test_period_month_round_trip():
    assert rf.period_month("Сентябрь 2026") == date(2026, 9, 1)
    assert rf.period_label(date(2026, 1, 1)) == "Январь 2026"
    with pytest.raises(ValueError):
        rf.period_month("September 2026")


def test_month_window_is_moscow_time():
    start, end = rf.month_window(date(2026, 9, 1))
    assert start == datetime(2026, 8, 31, 21, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 30, 21, tzinfo=timezone.utc)


def test_running_scale_mid_month_and_after_the_end():
    assert rf.running_scale(date(2026, 10, 1), datetime(2026, 10, 15, 9, tzinfo=timezone.utc)) == (31 / 15, False)
    assert rf.running_scale(date(2026, 9, 1), datetime(2026, 10, 2, tzinfo=timezone.utc)) == (1.0, False)


def test_running_scale_on_the_first_day():
    # 00:30 по Москве 1-го числа: прошли первые сутки, оценка «слишком рано».
    scale, early = rf.running_scale(date(2026, 11, 1), datetime(2026, 10, 31, 21, 30, tzinfo=timezone.utc))
    assert (scale, early) == (30.0, True)
    assert rf.running_scale(date(2026, 11, 1), datetime(2026, 11, 7, 9, tzinfo=timezone.utc))[1] is False


def test_months_to_forecast_adds_the_unpublished_previous_month():
    as_of = datetime(2026, 11, 3, 22, 50, tzinfo=timezone.utc)  # 4 ноября по Москве
    published = {date(2026, 9, 1)}
    assert rf.months_to_forecast(as_of, published) == [(date(2026, 10, 1), "final"), (date(2026, 11, 1), "running")]
    published.add(date(2026, 10, 1))
    assert rf.months_to_forecast(as_of, published) == [(date(2026, 11, 1), "running")]


def test_base_month_is_the_latest_published_before():
    published = {date(2026, 8, 1), date(2026, 9, 1)}
    assert rf.base_month_for(date(2026, 11, 1), published) == date(2026, 9, 1)
    assert rf.base_month_for(date(2026, 9, 1), published) == date(2026, 8, 1)
    assert rf.base_month_for(date(2026, 8, 1), published) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest tests/test_rating_forecast.py -q -k "period or window or scale or months_to or base_month"`
Expected: FAIL — `AttributeError: module 'api.rating_forecast' has no attribute 'period_month'`.

- [ ] **Step 3: Write the implementation** (импорты — в начало модуля: `import calendar`, `from collections.abc import Collection`, `from datetime import date, datetime, time`, `from zoneinfo import ZoneInfo`)

```python
MOSCOW = ZoneInfo("Europe/Moscow")
MONTH_NAMES = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
               "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")


def period_month(period: str) -> date:
    """Период импорта официального рейтинга («Сентябрь 2026») — первое число месяца."""
    parts = period.split()
    if len(parts) != 2 or parts[0] not in MONTH_NAMES or not parts[1].isdigit():
        raise ValueError(f"unknown official period: {period!r}")
    return date(int(parts[1]), MONTH_NAMES.index(parts[0]) + 1, 1)


def period_label(month: date) -> str:
    return f"{MONTH_NAMES[month.month - 1]} {month.year}"


def _next_month(month: date) -> date:
    return date(month.year + month.month // 12, month.month % 12 + 1, 1)


def month_window(month: date) -> tuple[datetime, datetime]:
    return (datetime.combine(month, time(), MOSCOW), datetime.combine(_next_month(month), time(), MOSCOW))


def running_scale(month: date, as_of: datetime, formula: Mapping[str, Any] = FORMULA_V1) -> tuple[float, bool]:
    """Во сколько раз досчитать публикации незаконченного месяца и рано ли судить."""
    _, end = month_window(month)
    if as_of >= end:
        return 1.0, False
    days = calendar.monthrange(month.year, month.month)[1]
    elapsed = (as_of.astimezone(MOSCOW).date() - month).days + 1
    return days / elapsed, elapsed < formula["earlyBeforeDay"]


def months_to_forecast(as_of: datetime, published: Collection[date]) -> list[tuple[date, str]]:
    current = as_of.astimezone(MOSCOW).date().replace(day=1)
    previous = (current.replace(day=1) - timedelta(days=1)).replace(day=1)
    months = [] if previous in published else [(previous, "final")]
    return months + [(current, "running")]


def base_month_for(month: date, published: Collection[date]) -> date | None:
    earlier = [item for item in published if item < month]
    return max(earlier) if earlier else None
```

(`timedelta` — добавить к импорту `datetime`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_rating_forecast.py -q`
Expected: PASS (22 passed).

- [ ] **Step 5: Commit**

```bash
git add api/rating_forecast.py tests/test_rating_forecast.py
git commit -m "feat(rating): forecast months — Moscow windows, running-month scale, base month"
```

### Task 3: Импорт официального рейтинга хранит сводный балл

**Files:**
- Modify: `api/official_rating.py:96-101` (сборка `evidence`)
- Test: `tests/test_rating_coverage.py` (добавить тест)

**Interfaces:**
- Produces: `evidence.items[].scores.consolidated` (float) для периодов, импортированных после этой правки; функция `rating.official_period_scores` (Task 4) читает его как `consolidated_score`.

- [ ] **Step 1: Write the failing test**

```python
def test_evidence_keeps_the_consolidated_score():
    import json
    source = json.dumps({"months": [{"name": "Сентябрь", "items": [
        {"code": "37", "name": "Вуз", "scores": {"consolidated": 22.0, "social": 46.9, "vk": 56.7,
                                                "tg": None, "ok": 60.4, "rt": 19.2}}]}]}).encode()
    month = official_rating._filled_months(source)[0]
    parsed = official_rating._parse_month("year: 2026", month, source, "https://www.m-rating.ru/data/r.json")
    assert parsed["evidence"]["items"][0]["scores"] == {"consolidated": 22.0, "social": 46.9, "vk": 56.7,
                                                         "ok": 60.4, "rt": 19.2}
    # Сводный балл — справка, в места категорий он не входит.
    assert set(parsed["rankings"]) == {"social", "telegram", "vk", "max", "rutube"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `$PY -m pytest tests/test_rating_coverage.py::test_evidence_keeps_the_consolidated_score -q`
Expected: FAIL — в `scores` нет `consolidated`.

- [ ] **Step 3: Write the implementation** — в `api/official_rating.py` рядом с `CATEGORIES`:

```python
# Сводный балл в места категорий не входит; хранится в evidence справкой для
# прогноза (сводное место прошлого месяца под таблицей «Рейтинга»).
EVIDENCE_EXTRA = ("consolidated",)
```

и в `_parse_month` заменить сборку `scores`:

```python
        scores = {key: float(item["scores"][key]) for key in (*EVIDENCE_EXTRA, *CATEGORIES.values())
                  if (item.get("scores") or {}).get(key) is not None}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_rating_coverage.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/official_rating.py tests/test_rating_coverage.py
git commit -m "feat(official-rating): keep the consolidated score in import evidence"
```

### Task 4: Миграция 0084 — формула, снимки, функции записи

**Files:**
- Create: `db/migrations/0084_rating_forecast.sql`
- Test: `tests/test_rating_forecast_postgres.py`

**Interfaces:**
- Consumes: `FORMULA_V1`, `FORMULA_KEY` (Task 1).
- Produces (SQL):
  - `rating.rating_run.parameters jsonb NOT NULL DEFAULT '{}'`
  - `rating.official_periods() RETURNS TABLE(period text, fetched_at timestamptz)` — `EXECUTE` у `api_write_admin`
  - `rating.official_period_scores(p_period text) RETURNS TABLE(code text, name text, social_score numeric, max_score numeric, vk_score numeric, rutube_score numeric, consolidated_score numeric)` — `EXECUTE` у `api_write_admin`
  - `ops_and_admin.record_rating_forecast(p_payload jsonb) RETURNS jsonb` — `{"runId", "replaced"}`; payload: `formulaKey, version, windowStart, windowEnd, asOf, startedAt, inputHash, parameters{status,...}, results[{institutionId, score, rank, explanation}]`
  - `ops_and_admin.finalize_rating_forecast(p_formula_key text, p_window_start timestamptz) RETURNS jsonb` — `{"runId", "removed"}`
  - Индекс `rating_run_formula_window_idx (formula_definition_id, window_start, as_of DESC)`
  - Событие outbox `rating_forecast.recorded` / `rating_forecast.finalized` с тегом `rating-forecast`

- [ ] **Step 1: Write the failing tests**

```python
"""Снимки прогноза М-Рейтинга на одноразовой базе «Находок»; без неё пропускается.

Применить 0084 к базе перед запуском: psql -f db/migrations/0084_rating_forecast.sql.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from api import rating_forecast as rf
from test_findings_postgres import World, _connect, dsn  # noqa: F401 — фикстура dsn

START = datetime(2026, 9, 30, 21, tzinfo=timezone.utc)   # 1 октября по Москве
END = datetime(2026, 10, 31, 21, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def clean(dsn):
    # Тесты и повторные прогоны не видят чужих снимков и официальных импортов.
    with _connect(dsn) as connection:
        connection.execute("DELETE FROM rating.rating_run")
        connection.execute("DELETE FROM rating.official_import WHERE actor = 'test'")
        connection.execute("DELETE FROM rating.official_rating_observation "
                           "WHERE source_url = 'https://www.m-rating.ru/r.json'")
        if connection.execute("SELECT max(id) AS id FROM analytics.dataset_revision").fetchone()["id"] is None:
            connection.execute("INSERT INTO analytics.dataset_revision(cause,correlation_id) "
                               "VALUES ('ingestion',gen_random_uuid())")


def payload(institution, as_of, status="running", window_start=START, window_end=None, score=50.0):
    window_end = window_end or min(END, as_of)
    return {"formulaKey": rf.FORMULA_KEY, "version": 1, "windowStart": window_start.isoformat(),
            "windowEnd": window_end.isoformat(), "asOf": as_of.isoformat(), "startedAt": as_of.isoformat(),
            "inputHash": hashlib.sha256(f"{status}{as_of}{window_start}".encode()).hexdigest(),
            "parameters": {"status": status, "basePeriod": "Сентябрь 2026"},
            "results": [{"institutionId": str(institution), "score": score, "rank": 8,
                         "explanation": {"code": "37", "categories": {}}}]}


def record(dsn, body):
    with _connect(dsn) as connection:
        return connection.execute("SELECT ops_and_admin.record_rating_forecast(%s) AS result",
                                  (Jsonb(body),)).fetchone()["result"]


def runs(dsn):
    with _connect(dsn) as connection:
        return connection.execute("SELECT id, as_of, parameters->>'status' AS status, window_start FROM rating.rating_run "
                                  "ORDER BY as_of").fetchall()


def test_formula_v1_matches_the_python_definition(dsn):
    with _connect(dsn) as connection:
        row = connection.execute("SELECT definition, status, source_hash FROM rating.formula_definition "
                                 "WHERE formula_key=%s AND version=1", (rf.FORMULA_KEY,)).fetchone()
    assert row["status"] == "published"
    assert row["definition"] == rf.FORMULA_V1
    canonical = json.dumps(rf.FORMULA_V1, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert row["source_hash"] == hashlib.sha256(canonical.encode()).hexdigest()


def test_record_accepts_a_running_snapshot_minutes_after_month_start(dsn):
    world = World(dsn, "vk")
    result = record(dsn, payload(world.institution, START + timedelta(minutes=30)))
    assert result["replaced"] == 0 and result["runId"]
    with _connect(dsn) as connection:
        stored = connection.execute("SELECT r.score, r.rank, r.quality::text AS quality, run.window_end, run.as_of "
                                    "FROM rating.rating_result r JOIN rating.rating_run run ON run.id=r.rating_run_id").fetchone()
    assert (float(stored["score"]), stored["rank"], stored["quality"]) == (50.0, 8, "estimated")
    assert stored["window_end"] == stored["as_of"]


def test_record_replaces_the_same_moscow_day(dsn):
    world = World(dsn, "vk")
    record(dsn, payload(world.institution, datetime(2026, 10, 15, 22, 10, tzinfo=timezone.utc)))  # 16.10 01:10 МСК
    second = record(dsn, payload(world.institution, datetime(2026, 10, 16, 20, 0, tzinfo=timezone.utc), score=51))
    assert second["replaced"] == 1 and len(runs(dsn)) == 1
    record(dsn, payload(world.institution, datetime(2026, 10, 16, 22, 10, tzinfo=timezone.utc)))  # 17.10 МСК
    assert len(runs(dsn)) == 2


def test_record_never_touches_a_published_run(dsn):
    world = World(dsn, "vk")
    as_of = datetime(2026, 10, 16, 22, 10, tzinfo=timezone.utc)
    record(dsn, payload(world.institution, as_of))
    with _connect(dsn) as connection:
        connection.execute("SELECT ops_and_admin.finalize_rating_forecast(%s, %s)", (rf.FORMULA_KEY, START))
    assert record(dsn, payload(world.institution, as_of + timedelta(hours=1)))["replaced"] == 0
    assert [row["status"] for row in runs(dsn)] == ["published", "running"]


def test_finalize_keeps_the_latest_snapshot_and_removes_the_rest(dsn):
    world = World(dsn, "vk")
    for day in (10, 11, 12):
        record(dsn, payload(world.institution, datetime(2026, 11, day, 22, tzinfo=timezone.utc), status="final"))
    with _connect(dsn) as connection:
        result = connection.execute("SELECT ops_and_admin.finalize_rating_forecast(%s, %s) AS result",
                                    (rf.FORMULA_KEY, START)).fetchone()["result"]
        events = connection.execute("SELECT affected_tags FROM ops_and_admin.outbox_event "
                                    "WHERE event_type='rating_forecast.finalized' ORDER BY id DESC LIMIT 1").fetchone()
    assert result["removed"] == 2
    assert [(row["as_of"].day, row["status"]) for row in runs(dsn)] == [(12, "published")]
    assert events["affected_tags"] == ["rating-forecast"]


def test_retrospective_is_one_per_month_and_survives_finalize(dsn):
    world = World(dsn, "vk")
    september = datetime(2026, 8, 31, 21, tzinfo=timezone.utc)
    october_end = datetime(2026, 9, 30, 21, tzinfo=timezone.utc)
    as_of = datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
    for _ in range(2):
        record(dsn, payload(world.institution, as_of, status="retrospective", window_start=september,
                            window_end=october_end))
    with _connect(dsn) as connection:
        connection.execute("SELECT ops_and_admin.finalize_rating_forecast(%s, %s)", (rf.FORMULA_KEY, september))
    assert [row["status"] for row in runs(dsn)] == ["retrospective"]


def test_record_rejects_unknown_status_and_formula(dsn):
    world = World(dsn, "vk")
    body = payload(world.institution, START + timedelta(hours=1), status="published")
    with pytest.raises(Exception, match="invalid rating forecast"):
        record(dsn, body)
    body = payload(world.institution, START + timedelta(hours=1))
    body["version"] = 99
    with pytest.raises(Exception, match="unknown rating formula"):
        record(dsn, body)


def test_official_period_scores_read_the_latest_import(dsn):
    world = World(dsn, "vk")
    with _connect(dsn) as connection:
        for fetched, social in (("2026-10-10T00:00:00Z", 40.0), ("2026-10-12T00:00:00Z", 46.9)):
            evidence = {"year": 2026, "month": "Сентябрь", "items": [
                {"code": "37", "name": "Вуз 37", "scores": {"social": social, "ok": 60.4, "vk": 56.7, "rt": 19.2,
                                                         "consolidated": 22.0}},
                {"code": "", "name": "без кода", "scores": {"social": 1.0}}]}
            connection.execute("""
                INSERT INTO rating.official_import(actor,correlation_id,period,source_url,source_hash,fetched_at,
                  evidence,evidence_sha256)
                VALUES ('test',gen_random_uuid(),'Сентябрь 2026','https://www.m-rating.ru/r.json',%s,%s,%s,%s)""",
                (hashlib.sha256(fetched.encode()).hexdigest(), fetched, Jsonb(evidence),
                 hashlib.sha256(fetched.encode()).hexdigest()))
        rows = connection.execute("SELECT * FROM rating.official_period_scores('Сентябрь 2026')").fetchall()
        periods = connection.execute("SELECT period FROM rating.official_periods()").fetchall()
    assert [(row["code"], float(row["social_score"]), float(row["max_score"]), float(row["rutube_score"]),
             float(row["consolidated_score"])) for row in rows] == [("37", 46.9, 60.4, 19.2, 22.0)]
    assert {"period": "Сентябрь 2026"} in periods


def test_grants_follow_the_roles(dsn):
    with _connect(dsn) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='api_write_admin'").fetchone():
            pytest.skip("роли не созданы")
        check = connection.execute("""
            SELECT has_function_privilege('api_write_admin','ops_and_admin.record_rating_forecast(jsonb)','EXECUTE') AS writer,
                   has_function_privilege('api_read','ops_and_admin.record_rating_forecast(jsonb)','EXECUTE') AS reader,
                   has_function_privilege('api_write_admin','rating.official_period_scores(text)','EXECUTE') AS scores,
                   has_table_privilege('api_write_admin','rating.rating_run','DELETE') AS direct_delete,
                   has_table_privilege('api_read','rating.rating_run','SELECT') AS read_runs""").fetchone()
    assert check == {"writer": True, "reader": False, "scores": True, "direct_delete": False, "read_runs": True}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `MRANKED_FINDINGS_TEST_DSN=... $PY -m pytest tests/test_rating_forecast_postgres.py -q`
Expected: FAIL — `function ops_and_admin.record_rating_forecast(jsonb) does not exist` (0084 ещё нет).

- [ ] **Step 3: Write the migration** `db/migrations/0084_rating_forecast.sql`. JSON и хеш ниже посчитаны от `FORMULA_V1` из Task 1 (`sha256` канонического `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`); тест `test_formula_v1_matches_the_python_definition` сверяет оба — при любой правке `FORMULA_V1` пересчитать.

```sql
-- 0084 — прогноз М-Рейтинга по соцсетям: формула v1 и ночные снимки.
-- Спек: docs/superpowers/specs/2026-10-16-rating-forecast-design.md.
--
-- Таблицы rating.rating_run/rating_result были в схеме с самого начала и
-- пустовали; прогноз — их первый потребитель. Запись — только через функции
-- SECURITY DEFINER (как import_official_rating): прямых прав на DELETE никому
-- не добавляется. Баллы всех 233 вузов базового месяца лежат в
-- rating.official_import.evidence, которую читает только maintenance, поэтому
-- заданию даётся узкая функция чтения.
--
-- Откат:
--   DROP FUNCTION ops_and_admin.finalize_rating_forecast(text, timestamptz);
--   DROP FUNCTION ops_and_admin.record_rating_forecast(jsonb);
--   DROP FUNCTION rating.official_period_scores(text); DROP FUNCTION rating.official_periods();
--   DELETE FROM rating.rating_run WHERE formula_definition_id IN (SELECT id FROM rating.formula_definition
--     WHERE formula_key='m-rating-social-forecast');
--   DROP INDEX rating.rating_run_formula_window_idx; ALTER TABLE rating.rating_run DROP COLUMN parameters;
--   (строку формулы удаляет только владелец: опубликованная формула неизменна, см. 0014.)
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE rating.rating_run ADD COLUMN parameters jsonb NOT NULL DEFAULT '{}'::jsonb
    CONSTRAINT rating_run_parameters_check CHECK (jsonb_typeof(parameters) = 'object');
CREATE INDEX rating_run_formula_window_idx ON rating.rating_run (formula_definition_id, window_start, as_of DESC);

INSERT INTO rating.formula_definition(formula_key, version, status, effective_from, definition, source_hash, published_at)
VALUES ('m-rating-social-forecast', 1, 'published', '2026-08-01T00:00:00+03:00',
        '{"formulaKey": "m-rating-social-forecast", "version": 1, "timezone": "Europe/Moscow", "weights": {"max": 0.4, "vk": 0.3, "rutube": 0.3}, "posts": {"low": 20, "high": 100}, "viewsPerStudent": {"vk": {"low": 0.1, "high": 3}, "max": {"low": 0.03, "high": 0.5}}, "erv": {"vk": {"low": 0.005, "high": 0.04}, "max": {"low": 0.005, "high": 0.1}}, "rutube": {"minVideos": 5, "logCoefficient": 12, "officialBlend": 0.5}, "matureAfterDays": 3, "earlyBeforeDay": 7, "defaultErrors": {"social": 7, "max": 10, "vk": 9, "rutube": 8}}'::jsonb,
        '86b5a8d3035c9353afe3f166642641694f5d3b379d49e9b765006b740127a5c5', transaction_timestamp());

CREATE FUNCTION rating.official_periods() RETURNS TABLE(period text, fetched_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'rating'
    AS $$ SELECT period, max(fetched_at) FROM rating.official_import GROUP BY period $$;

CREATE FUNCTION rating.official_period_scores(p_period text)
    RETURNS TABLE(code text, name text, social_score numeric, max_score numeric, vk_score numeric,
                  rutube_score numeric, consolidated_score numeric)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'rating'
    AS $$
    SELECT item->>'code', item->>'name',
           (item->'scores'->>'social')::numeric, (item->'scores'->>'ok')::numeric,
           (item->'scores'->>'vk')::numeric, (item->'scores'->>'rt')::numeric,
           (item->'scores'->>'consolidated')::numeric
      FROM (SELECT evidence FROM rating.official_import WHERE period = p_period
             ORDER BY fetched_at DESC, id DESC LIMIT 1) latest,
           jsonb_array_elements(latest.evidence->'items') item
     WHERE coalesce(item->>'code', '') <> ''
    $$;

CREATE FUNCTION ops_and_admin.record_rating_forecast(p_payload jsonb) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'rating', 'analytics', 'ops_and_admin'
    SET lock_timeout TO '10s'
    SET statement_timeout TO '5min'
    AS $$
DECLARE formula uuid; revision bigint; run uuid; replaced integer;
    snapshot_status text := p_payload->'parameters'->>'status';
    window_start timestamptz; moscow_day date;
BEGIN
    IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object' OR jsonb_typeof(p_payload->'results') IS DISTINCT FROM 'array'
        OR jsonb_array_length(p_payload->'results') > 1000
        OR snapshot_status IS NULL OR snapshot_status NOT IN ('running', 'final', 'retrospective') THEN
        RAISE EXCEPTION 'invalid rating forecast' USING ERRCODE = '22023';
    END IF;
    window_start := (p_payload->>'windowStart')::timestamptz;
    moscow_day := ((p_payload->>'asOf')::timestamptz AT TIME ZONE 'Europe/Moscow')::date;
    PERFORM pg_advisory_xact_lock(782194602);
    SELECT id INTO formula FROM rating.formula_definition
     WHERE formula_key = p_payload->>'formulaKey' AND version = (p_payload->>'version')::integer
       AND status = 'published';
    IF formula IS NULL THEN RAISE EXCEPTION 'unknown rating formula' USING ERRCODE = '22023'; END IF;
    SELECT id INTO revision FROM analytics.latest_dataset_revision();
    IF revision IS NULL THEN RAISE EXCEPTION 'no dataset revision' USING ERRCODE = '55000'; END IF;
    -- Снимок суток один: повторный запуск задания заменяет его. Ретроспектива
    -- месяца тоже одна. Итоговый снимок опубликованного месяца неприкосновенен.
    DELETE FROM rating.rating_run old
     WHERE old.formula_definition_id = formula AND old.window_start = record_rating_forecast.window_start
       AND old.parameters->>'status' IS DISTINCT FROM 'published'
       AND CASE WHEN snapshot_status = 'retrospective'
                THEN old.parameters->>'status' = 'retrospective'
                ELSE old.parameters->>'status' IN ('running', 'final')
                     AND (old.as_of AT TIME ZONE 'Europe/Moscow')::date = moscow_day END;
    GET DIAGNOSTICS replaced = ROW_COUNT;
    INSERT INTO rating.rating_run(formula_definition_id, dataset_revision_id, as_of, window_start, window_end,
                                  status, started_at, completed_at, input_hash, parameters)
    VALUES (formula, revision, (p_payload->>'asOf')::timestamptz, window_start,
            (p_payload->>'windowEnd')::timestamptz, 'succeeded', (p_payload->>'startedAt')::timestamptz,
            greatest(transaction_timestamp(), (p_payload->>'startedAt')::timestamptz),
            p_payload->>'inputHash', p_payload->'parameters')
    RETURNING id INTO run;
    INSERT INTO rating.rating_result(rating_run_id, institution_id, score, rank, quality, explanation)
    SELECT run, (item->>'institutionId')::uuid, (item->>'score')::numeric, (item->>'rank')::integer,
           'estimated', item->'explanation'
      FROM jsonb_array_elements(p_payload->'results') item;
    INSERT INTO ops_and_admin.outbox_event(dataset_revision_id, event_type, aggregate_type, aggregate_id,
                                           affected_tags, payload)
    VALUES (revision, 'rating_forecast.recorded', 'rating_run', run::text, ARRAY['rating-forecast'],
            jsonb_build_object('runId', run, 'status', snapshot_status));
    RETURN jsonb_build_object('runId', run, 'replaced', replaced);
END $$;

CREATE FUNCTION ops_and_admin.finalize_rating_forecast(p_formula_key text, p_window_start timestamptz)
    RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'rating', 'analytics', 'ops_and_admin'
    SET lock_timeout TO '10s'
    AS $$
DECLARE keep uuid; removed integer; revision bigint;
BEGIN
    PERFORM pg_advisory_xact_lock(782194602);
    SELECT run.id INTO keep FROM rating.rating_run run
      JOIN rating.formula_definition formula ON formula.id = run.formula_definition_id
     WHERE formula.formula_key = p_formula_key AND run.window_start = p_window_start
       AND run.parameters->>'status' IN ('running', 'final')
     ORDER BY run.as_of DESC LIMIT 1;
    IF keep IS NULL THEN RETURN jsonb_build_object('runId', NULL, 'removed', 0); END IF;
    UPDATE rating.rating_run SET parameters = parameters || '{"status": "published"}'::jsonb WHERE id = keep;
    DELETE FROM rating.rating_run run USING rating.formula_definition formula
     WHERE formula.id = run.formula_definition_id AND formula.formula_key = p_formula_key
       AND run.window_start = p_window_start AND run.id <> keep
       AND run.parameters->>'status' IN ('running', 'final');
    GET DIAGNOSTICS removed = ROW_COUNT;
    SELECT id INTO revision FROM analytics.latest_dataset_revision();
    INSERT INTO ops_and_admin.outbox_event(dataset_revision_id, event_type, aggregate_type, aggregate_id,
                                           affected_tags, payload)
    VALUES (revision, 'rating_forecast.finalized', 'rating_run', keep::text, ARRAY['rating-forecast'],
            jsonb_build_object('runId', keep, 'removed', removed));
    RETURN jsonb_build_object('runId', keep, 'removed', removed);
END $$;

REVOKE ALL ON FUNCTION rating.official_periods() FROM PUBLIC;
REVOKE ALL ON FUNCTION rating.official_period_scores(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.record_rating_forecast(jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION ops_and_admin.finalize_rating_forecast(text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rating.official_periods() TO api_write_admin;
GRANT EXECUTE ON FUNCTION rating.official_period_scores(text) TO api_write_admin;
GRANT EXECUTE ON FUNCTION ops_and_admin.record_rating_forecast(jsonb) TO api_write_admin;
GRANT EXECUTE ON FUNCTION ops_and_admin.finalize_rating_forecast(text, timestamptz) TO api_write_admin;

COMMIT;
```

Замечания исполнителю: (1) локальная переменная `window_start` совпадает с именем столбца — в `DELETE` она квалифицирована именем функции, в `INSERT ... VALUES` конфликта нет; если plpgsql всё же ругается на неоднозначность, переименовать переменную в `v_window_start`. (2) `USAGE` на схему `rating` у `api_write_admin` уже есть (`0017_grants.sql:92`). (3) Миграция содержит свои `BEGIN/COMMIT`: для сухого прогона на локальной копии вырезать их (память `local-db-copy`).

- [ ] **Step 4: Apply and run the tests**

Run: `psql "$MRANKED_FINDINGS_TEST_DSN" -v ON_ERROR_STOP=1 -f db/migrations/0084_rating_forecast.sql && $PY -m pytest tests/test_rating_forecast_postgres.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add db/migrations/0084_rating_forecast.sql tests/test_rating_forecast_postgres.py
git commit -m "feat(db): 0084 — forecast formula v1, snapshot parameters, definer write/finalize functions"
```

### Task 5: SQL агрегатов и читателей

**Files:**
- Create: `api/sql/rating.py`
- Test: `tests/test_rating_forecast_postgres.py` (добавить тесты)

**Interfaces:**
- Consumes: 0084 (Task 4).
- Produces (строки SQL; параметры — именованные):
  - `PLATFORM_MONTH(window_start, window_end, mature_before)` → строки `institution_id, code, name, platform (NULL если нет аккаунтов), posts, mature_posts, mature_views, mature_interactions, viewed_posts, views, interactions, covered`
  - `FORECAST_MONTHS(formula_key)` → `month (YYYY-MM), status, as_of`, новые первыми
  - `FORECAST_RUN(formula_key, window_start)` → одна строка `id, as_of, window_start, parameters, version` (не ретроспектива первой)
  - `FORECAST_ROWS(run_id, period)` → `institution_id, legacy_id, name, short_name, score, rank, explanation, actual (jsonb {category: {rank, score}} | NULL)`
  - `PUBLISHED_SNAPSHOT_SCORES(formula_key, window_start, period)` → `institution_id, category, predicted, actual` для типичных ошибок

- [ ] **Step 1: Write the failing tests** (в `tests/test_rating_forecast_postgres.py`)

```python
from api.sql import rating as sql


def _platform_month(dsn, window_start, window_end, mature_before, role=None):
    with _connect(dsn) as connection:
        if role:
            connection.execute(f"SET ROLE {role}")
        return connection.execute(sql.PLATFORM_MONTH, {"window_start": window_start, "window_end": window_end,
                                                       "mature_before": mature_before}).fetchall()


def coded(dsn, world, code):
    with _connect(dsn) as connection:
        connection.execute("INSERT INTO catalog.institution_external_id(institution_id,namespace,external_id,valid_from) "
                           "VALUES (%s,'m-rating',%s,'2026-01-01')", (world.institution, code))


def latest(dsn, publication, views, reactions, comments=0, shares=0):
    with _connect(dsn) as connection:
        connection.execute("""
            INSERT INTO analytics.publication_latest(publication_id,institution_id,platform_account_id,platform,observed_at,
              views_count,views_observed_at,views_quality,reactions_count,reactions_observed_at,reactions_quality,
              comments_count,comments_observed_at,comments_quality,shares_count,shares_observed_at,shares_quality,
              quality,history_completeness,dataset_revision_id)
            SELECT p.id,a.institution_id,a.id,a.platform,now(),%s,now(),'exact',%s,now(),'exact',%s,now(),'exact',%s,now(),'exact',
                   'exact','complete',(SELECT max(id) FROM analytics.dataset_revision)
              FROM ingest.publication p JOIN catalog.platform_account a ON a.id=p.primary_account_id WHERE p.id=%s""",
            (views, reactions, comments, shares, publication))


SEPT = (datetime(2026, 8, 31, 21, tzinfo=timezone.utc), datetime(2026, 9, 30, 21, tzinfo=timezone.utc))


def test_platform_month_sums_moscow_month_and_mature_posts(dsn):
    world = World(dsn, "vk")
    code = f"t{world.legacy_id}"
    coded(dsn, world, code)
    with _connect(dsn) as connection:
        connection.execute("UPDATE catalog.platform_account SET created_at='2026-08-01' WHERE id=%s", (world.account,))
    inside = world.post(datetime(2026, 8, 31, 21, 30, tzinfo=timezone.utc), {})   # 1 сентября 00:30 МСК
    young = world.post(datetime(2026, 9, 29, 12, tzinfo=timezone.utc), {})
    world.post(datetime(2026, 8, 31, 20, 59, tzinfo=timezone.utc), {})            # 31 августа МСК
    latest(dsn, inside, 1000, 30, 5, 5)
    latest(dsn, young, 10, 1)
    rows = [row for row in _platform_month(dsn, *SEPT, datetime(2026, 9, 27, tzinfo=timezone.utc))
            if row["code"] == code]
    assert len(rows) == 1
    row = rows[0]
    assert (row["platform"], row["posts"], row["mature_posts"], row["mature_views"], row["mature_interactions"]) == \
        ("vk", 2, 1, 1000, 40)
    assert (row["viewed_posts"], row["views"], row["interactions"], row["covered"]) == (2, 1010, 41, True)


def test_platform_month_marks_accounts_added_mid_month_uncovered(dsn):
    """Нижневартовский ГУ: VK добавлен 15.09, самая ранняя публикация 02.09."""
    world = World(dsn, "vk")
    code = f"t{world.legacy_id}"
    coded(dsn, world, code)
    with _connect(dsn) as connection:
        connection.execute("UPDATE catalog.platform_account SET created_at='2026-09-15' WHERE id=%s", (world.account,))
    world.post(datetime(2026, 9, 2, 9, tzinfo=timezone.utc), {})
    row = next(row for row in _platform_month(dsn, *SEPT, SEPT[1]) if row["code"] == code)
    assert row["covered"] is False
    # История, догруженная до начала месяца, делает месяц покрытым.
    world.post(datetime(2026, 7, 1, 9, tzinfo=timezone.utc), {})
    row = next(row for row in _platform_month(dsn, *SEPT, SEPT[1]) if row["code"] == code)
    assert row["covered"] is True


def test_platform_month_lists_coded_institutions_without_accounts_and_runs_as_api_read(dsn):
    world = World(dsn, "telegram")       # Telegram в прогноз не входит
    code = f"t{world.legacy_id}"
    coded(dsn, world, code)
    with _connect(dsn) as connection:
        if not connection.execute("SELECT 1 FROM pg_roles WHERE rolname='api_read'").fetchone():
            pytest.skip("роль api_read не создана")
    rows = [row for row in _platform_month(dsn, *SEPT, SEPT[1], role="api_read") if row["code"] == code]
    assert [(row["platform"], row["posts"]) for row in rows] == [(None, None)]


def test_months_and_rows_prefer_the_real_forecast_over_retrospective(dsn):
    world = World(dsn, "vk")
    as_of = datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
    record(dsn, payload(world.institution, as_of, status="retrospective", window_start=SEPT[0], window_end=SEPT[1]))
    record(dsn, payload(world.institution, as_of, status="final", window_start=SEPT[0], window_end=SEPT[1], score=60))
    with _connect(dsn) as connection:
        months = connection.execute(sql.FORECAST_MONTHS, {"formula_key": rf.FORMULA_KEY}).fetchall()
        run = connection.execute(sql.FORECAST_RUN, {"formula_key": rf.FORMULA_KEY, "window_start": SEPT[0]}).fetchone()
        rows = connection.execute(sql.FORECAST_ROWS, {"run_id": run["id"], "period": "Сентябрь 2026"}).fetchall()
    assert [(item["month"], item["status"]) for item in months] == [("2026-09", "final")]
    assert run["parameters"]["status"] == "final" and run["version"] == 1
    assert (float(rows[0]["score"]), rows[0]["legacy_id"], rows[0]["actual"]) == (60.0, world.legacy_id, None)


def test_rows_join_the_official_actual_for_the_period(dsn):
    world = World(dsn, "vk")
    as_of = datetime(2026, 10, 16, 22, tzinfo=timezone.utc)
    record(dsn, payload(world.institution, as_of, status="retrospective", window_start=SEPT[0], window_end=SEPT[1]))
    with _connect(dsn) as connection:
        for category, rank, score in (("social", 8, 65.9), ("vk", 38, 70.2)):
            connection.execute("""
                INSERT INTO rating.official_rating_observation(institution_id,category,period,rank,score,source_url,
                  source_hash,fetched_at) VALUES (%s,%s,'Сентябрь 2026',%s,%s,'https://www.m-rating.ru/r.json',%s,now())""",
                (world.institution, category, rank, score, hashlib.sha256(category.encode()).hexdigest()))
        run = connection.execute(sql.FORECAST_RUN, {"formula_key": rf.FORMULA_KEY, "window_start": SEPT[0]}).fetchone()
        connection.execute("SET ROLE api_read")
        row = connection.execute(sql.FORECAST_ROWS, {"run_id": run["id"], "period": "Сентябрь 2026"}).fetchone()
    assert row["actual"]["social"] == {"rank": 8, "score": 65.9}
    assert row["actual"]["vk"]["rank"] == 38
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest tests/test_rating_forecast_postgres.py -q -k "platform_month or months_and_rows or official_actual"`
Expected: FAIL — `ImportError: cannot import name 'rating' from 'api.sql'`.

- [ ] **Step 3: Write `api/sql/rating.py`**

```python
"""SQL прогноза М-Рейтинга: агрегаты ночного задания и чтение снимков."""

# Площадки наших вузов (с действующим кодом m-rating) за месяц по Москве.
# Аккаунт покрывает месяц, если включён и либо был в каталоге с начала месяца,
# либо его догруженная история начинается раньше месяца. Вуз без аккаунтов на
# VK/MAX/Rutube остаётся одной строкой с platform IS NULL.
PLATFORM_MONTH = """
WITH coded AS (
    SELECT code.institution_id, code.external_id AS code, institution.canonical_name AS name
      FROM catalog.institution_external_id code
      JOIN catalog.visible_institution institution ON institution.id = code.institution_id
     WHERE code.namespace = 'm-rating' AND code.valid_to IS NULL
), account AS (
    SELECT account.id, account.institution_id, account.platform::text AS platform,
           account.enabled AND (account.created_at <= %(window_start)s OR EXISTS (
               SELECT 1 FROM ingest.publication earliest
                WHERE earliest.primary_account_id = account.id
                  AND earliest.published_at < %(window_start)s)) AS covered
      FROM catalog.visible_platform_account account
      JOIN coded ON coded.institution_id = account.institution_id
     WHERE account.platform IN ('vk', 'max', 'rutube')
), platform_month AS (
    SELECT account.institution_id, account.platform, bool_and(account.covered) AS covered,
           count(publication.id) AS posts,
           count(latest.views_count) FILTER (WHERE publication.published_at <= %(mature_before)s) AS mature_posts,
           coalesce(sum(latest.views_count) FILTER (WHERE publication.published_at <= %(mature_before)s), 0) AS mature_views,
           coalesce(sum(coalesce(latest.reactions_count, 0) + coalesce(latest.comments_count, 0)
                        + coalesce(latest.shares_count, 0))
                    FILTER (WHERE publication.published_at <= %(mature_before)s
                              AND latest.views_count IS NOT NULL), 0) AS mature_interactions,
           count(latest.views_count) AS viewed_posts,
           coalesce(sum(latest.views_count), 0) AS views,
           coalesce(sum(coalesce(latest.reactions_count, 0) + coalesce(latest.comments_count, 0)
                        + coalesce(latest.shares_count, 0)) FILTER (WHERE latest.views_count IS NOT NULL), 0)
               AS interactions
      FROM account
      LEFT JOIN ingest.publication publication
        ON publication.primary_account_id = account.id AND publication.deleted_at IS NULL
       AND publication.published_at >= %(window_start)s AND publication.published_at < %(window_end)s
      LEFT JOIN analytics.publication_latest latest ON latest.publication_id = publication.id
     GROUP BY account.institution_id, account.platform
)
SELECT coded.institution_id::text AS institution_id, coded.code, coded.name, platform_month.platform,
       platform_month.posts, platform_month.mature_posts, platform_month.mature_views,
       platform_month.mature_interactions, platform_month.viewed_posts, platform_month.views,
       platform_month.interactions, platform_month.covered
  FROM coded LEFT JOIN platform_month ON platform_month.institution_id = coded.institution_id
 ORDER BY coded.code, platform_month.platform
"""

# Месяц — один снимок: настоящий прогноз (итоговый, бегущий) важнее ретроспективы.
_BEST_RUN = """
    SELECT DISTINCT ON (run.window_start) run.id, run.as_of, run.window_start, run.parameters, formula.version
      FROM rating.rating_run run
      JOIN rating.formula_definition formula ON formula.id = run.formula_definition_id
     WHERE formula.formula_key = %(formula_key)s {filter}
     ORDER BY run.window_start, (run.parameters->>'status' = 'retrospective'), run.as_of DESC
"""

FORECAST_MONTHS = f"""
SELECT to_char(best.window_start AT TIME ZONE 'Europe/Moscow', 'YYYY-MM') AS month,
       best.parameters->>'status' AS status, best.as_of
  FROM ({_BEST_RUN.format(filter="")}) best
 ORDER BY best.window_start DESC
"""

FORECAST_RUN = _BEST_RUN.format(filter="AND run.window_start = %(window_start)s")

FORECAST_ROWS = """
WITH actual AS (
    SELECT DISTINCT ON (observation.institution_id, observation.category)
           observation.institution_id, observation.category, observation.rank, observation.score
      FROM rating.official_institution_rating_observation observation
     WHERE observation.period = %(period)s AND observation.category IN ('social', 'max', 'vk', 'rutube')
     ORDER BY observation.institution_id, observation.category, observation.fetched_at DESC
)
SELECT result.institution_id::text AS institution_id, alias.legacy_id, institution.canonical_name AS name,
       institution.short_name, result.score, result.rank, result.explanation,
       (SELECT jsonb_object_agg(actual.category, jsonb_build_object('rank', actual.rank, 'score', actual.score))
          FROM actual WHERE actual.institution_id = result.institution_id) AS actual
  FROM rating.rating_result result
  JOIN catalog.institution institution ON institution.id = result.institution_id
  LEFT JOIN catalog.legacy_entity_alias alias
    ON alias.entity_type = 'institutions' AND alias.target_uuid = result.institution_id
 WHERE result.rating_run_id = %(run_id)s
 ORDER BY result.rank, institution.canonical_name
"""

# Прогноз опубликованного месяца против факта — для типичных ошибок следующих снимков.
PUBLISHED_SNAPSHOT_SCORES = f"""
WITH best AS ({_BEST_RUN.format(filter="AND run.window_start = %(window_start)s")})
SELECT result.institution_id::text AS institution_id, category.key AS category,
       (result.explanation->'categories'->category.key->>'score')::float8 AS predicted,
       (SELECT observation.score::float8 FROM rating.official_institution_rating_observation observation
         WHERE observation.institution_id = result.institution_id AND observation.category = category.key
           AND observation.period = %(period)s
         ORDER BY observation.fetched_at DESC LIMIT 1) AS actual
  FROM best
  JOIN rating.rating_result result ON result.rating_run_id = best.id
 CROSS JOIN (VALUES ('social'), ('max'), ('vk'), ('rutube')) AS category(key)
"""
```

Замечание: `alias.legacy_id` может давать несколько строк, если у вуза несколько алиасов; проверить `catalog.legacy_entity_alias` на уникальность `(entity_type, target_uuid)` и при её отсутствии заменить `LEFT JOIN` на `LEFT JOIN LATERAL (SELECT min(legacy_id) AS legacy_id ...) alias ON true`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_rating_forecast_postgres.py -q`
Expected: PASS (14 passed).

- [ ] **Step 5: Commit**

```bash
git add api/sql/rating.py tests/test_rating_forecast_postgres.py
git commit -m "feat(rating): SQL for monthly platform aggregates and forecast snapshot readers"
```

### Task 6: Ночное задание и таймер

**Files:**
- Create: `api/tools/rating_forecast.py`
- Create: `operations/systemd/m-ranked-target-rating-forecast.service`, `operations/systemd/m-ranked-target-rating-forecast.timer`
- Modify: `operations/install/install.py:214-215`, `operations/systemd/m-ranked-target.target:19`, `operations/systemd/m-ranked-target-profile-b-server2.target:16`
- Test: `tests/test_rating_forecast_job.py` (новый), `tests/test_operations_profiles.py`, `tests/test_rating_forecast_postgres.py`

**Interfaces:**
- Consumes: `api.rating_forecast` (Tasks 1–2), `api.sql.rating` (Task 5), функции 0084 (Task 4), `api.institution_profile._students_by_institution`.
- Produces:
  - `async def run(database, as_of: datetime, *, retrospective: list[date] | None = None) -> list[dict]` — ответы `record_rating_forecast` по месяцам
  - `def parse_retrospective(value: str) -> list[date]` — `"2026-08..2026-09"` → `[date(2026,8,1), date(2026,9,1)]`
  - CLI: `python -m api.tools.rating_forecast [--retrospective 2026-08..2026-09]`

- [ ] **Step 1: Write the failing unit tests** `tests/test_rating_forecast_job.py`

```python
"""Ночное задание прогноза: выбор месяцев, пропуск без базы, финализация."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone

import pytest

from api.tools import rating_forecast as job


class FakeDatabase:
    def __init__(self, periods, scores=None, months=None):
        self.periods, self.scores, self.months = periods, scores or {}, months or []
        self.recorded, self.finalized = [], []

    async def admin_fetch_all(self, query, params=None):
        if "official_periods" in query:
            return [{"period": period} for period in self.periods]
        if "official_period_scores" in query:
            return self.scores.get(params["period"], [])
        raise AssertionError(query)

    async def admin_fetch_one(self, query, params=None):
        if "record_rating_forecast" in query:
            body = json.loads(params["payload"])
            self.recorded.append(body)
            return {"result": {"runId": "r", "replaced": 0}}
        if "finalize_rating_forecast" in query:
            self.finalized.append(params["window_start"])
            return {"result": {"runId": None, "removed": 0}}
        raise AssertionError(query)

    async def fetch_all(self, query, params=None):
        if "WITH coded" in query:
            return self.months
        return []


SCORES = [{"code": "37", "name": "Вуз 37", "social_score": 46.9, "max_score": 60.4, "vk_score": 56.7,
           "rutube_score": 19.2, "consolidated_score": None}]
MONTH_ROWS = [{"institution_id": "00000000-0000-0000-0000-000000000037", "code": "37", "name": "Вуз 37",
               "platform": "vk", "posts": 80, "mature_posts": 70, "mature_views": 70000, "mature_interactions": 1400,
               "viewed_posts": 80, "views": 80000, "interactions": 1600, "covered": True}]


def test_parse_retrospective():
    assert job.parse_retrospective("2026-08..2026-09") == [date(2026, 8, 1), date(2026, 9, 1)]
    with pytest.raises(ValueError):
        job.parse_retrospective("2026-09..2026-08")


def test_job_records_current_month_with_extrapolation_and_finalizes_published():
    database = FakeDatabase(["Август 2026", "Сентябрь 2026"], {"Сентябрь 2026": SCORES}, MONTH_ROWS)
    asyncio.run(job.run(database, datetime(2026, 10, 15, 22, 10, tzinfo=timezone.utc)))
    [body] = database.recorded
    assert body["parameters"]["status"] == "running" and body["parameters"]["basePeriod"] == "Сентябрь 2026"
    assert body["parameters"]["early"] is False and body["parameters"]["postsScale"] == pytest.approx(31 / 16)
    assert body["windowEnd"] == "2026-10-15T22:10:00+00:00"
    vk = body["results"][0]["explanation"]["platforms"]["vk"]
    # Просмотры — по зрелым постам: 70 000 / 70.
    assert vk["metrics"]["avgViews"] == 1000.0 and vk["metrics"]["postsExtrapolated"] == pytest.approx(155.0)
    assert len(database.finalized) == 2


def test_job_skips_a_month_without_a_published_base(caplog):
    database = FakeDatabase([], {}, MONTH_ROWS)
    assert asyncio.run(job.run(database, datetime(2026, 1, 10, tzinfo=timezone.utc))) == []
    assert database.recorded == []
    assert "нет опубликованного базового месяца" in caplog.text


def test_job_retrospective_uses_the_previous_published_month():
    database = FakeDatabase(["Июль 2026", "Август 2026", "Сентябрь 2026"],
                            {"Июль 2026": SCORES, "Август 2026": SCORES}, MONTH_ROWS)
    asyncio.run(job.run(database, datetime(2026, 10, 16, 22, tzinfo=timezone.utc),
                        retrospective=[date(2026, 8, 1), date(2026, 9, 1)]))
    assert [(body["parameters"]["status"], body["parameters"]["basePeriod"]) for body in database.recorded] == \
        [("retrospective", "Июль 2026"), ("retrospective", "Август 2026")]
    assert all(body["parameters"]["postsScale"] == 1.0 for body in database.recorded)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest tests/test_rating_forecast_job.py -q`
Expected: FAIL — `ImportError: cannot import name 'rating_forecast' from 'api.tools'`.

- [ ] **Step 3: Write `api/tools/rating_forecast.py`**

```python
"""Ночной снимок прогноза М-Рейтинга по соцсетям.

Каждую ночь считает текущий месяц (бегущая оценка) и прошлый, если
официального за него ещё нет (итоговый прогноз), и помечает итоговыми снимки
месяцев, которые источник уже опубликовал. Ретроспектива (--retrospective)
считается разово при выкатке: по месяцу, со статусом retrospective.

Агрегаты читает пул чтения; баллы базового месяца и запись снимка — через
функции миграции 0084 под api_write_admin. Задание фоновое (CPUWeight=10):
агрегация месяца по 75 вузам на копии прода — меньше секунды.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .. import rating_forecast as rf
from ..config import Settings
from ..db import Database
from ..institution_profile import _students_by_institution
from ..sql import rating as sql

logger = logging.getLogger("rating-forecast")


def parse_retrospective(value: str) -> list[date]:
    first, _, last = value.partition("..")
    start, end = (date.fromisoformat(f"{item}-01") for item in (first, last or first))
    if end < start:
        raise ValueError("retrospective range is reversed")
    months, current = [], start
    while current <= end:
        months.append(current)
        current = (current + timedelta(days=32)).replace(day=1)
    return months


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


async def _published(database: Any) -> dict[date, str]:
    published: dict[date, str] = {}
    for row in await database.admin_fetch_all("SELECT period FROM rating.official_periods()"):
        try:
            published[rf.period_month(row["period"])] = row["period"]
        except ValueError:
            logger.warning("неизвестный период официального рейтинга: %r", row["period"])
    return published


async def _base(database: Any, period: str) -> rf.BaseMonth:
    rows = await database.admin_fetch_all(
        "SELECT code,name,social_score,max_score,vk_score,rutube_score,consolidated_score"
        " FROM rating.official_period_scores(%(period)s)", {"period": period})
    return rf.BaseMonth(period=period, names={row["code"]: row["name"] for row in rows}, scores={
        row["code"]: {"social": _number(row["social_score"]), "max": _number(row["max_score"]),
                      "vk": _number(row["vk_score"]), "rutube": _number(row["rutube_score"]),
                      "consolidated": _number(row["consolidated_score"])} for row in rows})


async def _institutions(database: Any, month: date, as_of: datetime) -> list[rf.InstitutionMonth]:
    start, end = rf.month_window(month)
    rows = await database.fetch_all(sql.PLATFORM_MONTH, {
        "window_start": start, "window_end": min(end, as_of),
        "mature_before": as_of - timedelta(days=rf.FORMULA_V1["matureAfterDays"])})
    students = _students_by_institution()
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {"platforms": {}})
    for row in rows:
        entry = grouped[row["institution_id"]]
        entry.update(code=row["code"], name=row["name"])
        if row["platform"] is None:
            continue
        # Зрелые посты — если они есть; иначе все (начало месяца).
        mature = row["mature_posts"] > 0
        entry["platforms"][row["platform"]] = rf.PlatformMonth(
            posts=row["posts"],
            viewed_posts=row["mature_posts"] if mature else row["viewed_posts"],
            views=int(row["mature_views"] if mature else row["views"]),
            interactions=int(row["mature_interactions"] if mature else row["interactions"]),
            covered=bool(row["covered"]))
    return [rf.InstitutionMonth(institution_id=key, code=value["code"], name=value["name"],
                                students=(students.get(key) or {}).get("value"), platforms=value["platforms"])
            for key, value in sorted(grouped.items(), key=lambda item: item[1]["code"])]


async def _errors(database: Any, month: date, published: dict[date, str]) -> dict[str, float]:
    """Типичные ошибки — по последнему опубликованному месяцу, где есть снимок."""
    defaults = dict(rf.FORMULA_V1["defaultErrors"])
    for candidate in sorted((item for item in published if item < month), reverse=True)[:3]:
        rows = await database.fetch_all(sql.PUBLISHED_SNAPSHOT_SCORES, {
            "formula_key": rf.FORMULA_KEY, "window_start": rf.month_window(candidate)[0],
            "period": published[candidate]})
        if not rows:
            continue
        predicted: dict[str, dict[str, float]] = defaultdict(dict)
        actual: dict[str, dict[str, float | None]] = defaultdict(dict)
        for row in rows:
            if row["predicted"] is not None:
                predicted[row["institution_id"]][row["category"]] = row["predicted"]
            actual[row["institution_id"]][row["category"]] = row["actual"]
        return rf.typical_errors(predicted, actual, defaults)
    return defaults


async def _forecast_month(database: Any, month: date, status: str, as_of: datetime,
                          published: dict[date, str]) -> dict | None:
    base_month = rf.base_month_for(month, published)
    if base_month is None:
        logger.warning("нет опубликованного базового месяца для %s — пропуск", month.isoformat())
        return None
    base = await _base(database, published[base_month])
    if not base.scores:
        logger.warning("базовый месяц %s пуст — пропуск", base.period)
        return None
    scale, early = (1.0, False) if status == "retrospective" else rf.running_scale(month, as_of)
    institutions = await _institutions(database, month, as_of)
    errors = await _errors(database, month, published)
    results = rf.forecast(institutions, base, errors, scale=scale)
    start, end = rf.month_window(month)
    window_end = min(end, as_of)
    parameters = {"status": status, "basePeriod": base.period, "period": rf.period_label(month),
                  "errors": errors, "postsScale": round(scale, 4), "early": early,
                  "formulaVersion": rf.FORMULA_V1["version"]}
    digest = hashlib.sha256(json.dumps({"month": month.isoformat(), "parameters": parameters,
                                        "results": results}, sort_keys=True, default=str).encode()).hexdigest()
    body = {"formulaKey": rf.FORMULA_KEY, "version": rf.FORMULA_V1["version"],
            "windowStart": start.astimezone(timezone.utc).isoformat(),
            "windowEnd": window_end.astimezone(timezone.utc).isoformat(),
            "asOf": as_of.astimezone(timezone.utc).isoformat(),
            "startedAt": as_of.astimezone(timezone.utc).isoformat(),
            "inputHash": digest, "parameters": parameters, "results": results}
    row = await database.admin_fetch_one("SELECT ops_and_admin.record_rating_forecast(%(payload)s::jsonb) AS result",
                                         {"payload": json.dumps(body, ensure_ascii=False)})
    logger.info("снимок %s (%s): %d вузов, заменено %s", month.isoformat(), status, len(results),
                row["result"]["replaced"])
    return row["result"]


async def run(database: Any, as_of: datetime, *, retrospective: list[date] | None = None) -> list[dict]:
    published = await _published(database)
    targets = ([(month, "retrospective") for month in retrospective] if retrospective
               else rf.months_to_forecast(as_of, published))
    recorded = []
    for month, status in targets:
        result = await _forecast_month(database, month, status, as_of, published)
        if result is not None:
            recorded.append(result)
    if not retrospective:
        for month in sorted(published)[-2:]:
            await database.admin_fetch_one(
                "SELECT ops_and_admin.finalize_rating_forecast(%(formula_key)s, %(window_start)s) AS result",
                {"formula_key": rf.FORMULA_KEY, "window_start": rf.month_window(month)[0]})
    return recorded


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="rating_forecast")
    parser.add_argument("--retrospective", type=parse_retrospective, default=None)
    arguments = parser.parse_args(argv)
    database = Database(Settings())
    await database.open()
    try:
        await run(database, datetime.now(timezone.utc), retrospective=arguments.retrospective)
        return 0
    except Exception as error:
        logger.error("прогноз М-Рейтинга не посчитан: %s", type(error).__name__)
        return 1
    finally:
        await database.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return asyncio.run(_main(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
```

Проверить в `FakeDatabase`: тест ждёт `params["payload"]` и `params["window_start"]` — ключи совпадают с кодом выше. Проверить, что `admin_fetch_one` в `api/db.py` выполняет запрос в транзакции с автокоммитом (иначе снимок не сохранится): прочитать `api/db.py:97-103`; если соединение не коммитит, обернуть запись в `async with database.admin() as connection: async with connection.transaction(): ...`, как `_import_month` в `api/official_rating.py`, и поменять фейк.

- [ ] **Step 4: Systemd units**

`operations/systemd/m-ranked-target-rating-forecast.service` — копия `m-ranked-target-official-rating.service` с тремя отличиями: `Description=M-Ranked M-Rating social forecast nightly snapshot`, `After=network-online.target m-ranked-target-api.service m-ranked-target-official-rating.service`, `ExecStart=/opt/m-ranked/current/.venv/bin/python -m api.tools.rating_forecast`; комментарий у `CPUWeight` — «Снимок фоновый: уступает и сбору, и отдаче страниц».

`operations/systemd/m-ranked-target-rating-forecast.timer`:

```ini
[Unit]
Description=Snapshot the M-Rating social forecast once a day

[Timer]
# После ежедневной проверки официального рейтинга (01:17 + до 20 мин) и до
# ночного дампа: новый официальный месяц финализирует прогноз в ту же ночь.
OnCalendar=*-*-* 01:47:00
RandomizedDelaySec=10min
Persistent=true
AccuracySec=5min
Unit=m-ranked-target-rating-forecast.service

[Install]
WantedBy=timers.target
```

Регистрация: в `operations/install/install.py` после `"m-ranked-target-official-rating.timer",` добавить `"m-ranked-target-rating-forecast.service",` и `"m-ranked-target-rating-forecast.timer",`; в обоих target-файлах после строки `Wants=m-ranked-target-official-rating.timer` — `Wants=m-ranked-target-rating-forecast.timer`. В `tests/test_operations_profiles.py` добавить `"m-ranked-target-rating-forecast.timer",` в оба множества (строки 39 и 68).

- [ ] **Step 5: End-to-end Postgres test** (в `tests/test_rating_forecast_postgres.py`)

```python
def test_job_end_to_end_on_postgres(dsn):
    import asyncio
    from types import SimpleNamespace
    import psycopg
    from psycopg.rows import dict_row
    from api.tools import rating_forecast as job

    class Direct:
        """Оба пула — одно соединение суперпользователя: права проверяют тесты выше."""
        async def _rows(self, query, params):
            async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row, autocommit=True) as connection:
                return await (await connection.execute(query, params)).fetchall()
        async def fetch_all(self, query, params=None): return await self._rows(query, params)
        async def admin_fetch_all(self, query, params=None): return await self._rows(query, params)
        async def admin_fetch_one(self, query, params=None): return (await self._rows(query, params))[0]

    world = World(dsn, "vk")
    code = f"t{world.legacy_id}"
    coded(dsn, world, code)
    with _connect(dsn) as connection:
        connection.execute("UPDATE catalog.platform_account SET created_at='2026-08-01' WHERE id=%s", (world.account,))
        evidence = {"items": [{"code": code, "name": f"Вуз {world.legacy_id}",
                               "scores": {"social": 50.0, "ok": 60.0, "vk": 55.0, "rt": 20.0}}]}
        connection.execute("""
            INSERT INTO rating.official_import(actor,correlation_id,period,source_url,source_hash,fetched_at,evidence,evidence_sha256)
            VALUES ('test',gen_random_uuid(),'Сентябрь 2026','https://www.m-rating.ru/r.json',%s,now(),%s,%s)""",
            ("a" * 64, Jsonb(evidence), "b" * 64))
    for day in range(1, 12):
        latest(dsn, world.post(datetime(2026, 10, day, 9, tzinfo=timezone.utc), {}), 1000, 20)
    asyncio.run(job.run(Direct(), datetime(2026, 10, 15, 22, 10, tzinfo=timezone.utc)))
    with _connect(dsn) as connection:
        run = connection.execute(sql.FORECAST_RUN, {"formula_key": rf.FORMULA_KEY, "window_start": START}).fetchone()
        rows = connection.execute(sql.FORECAST_ROWS, {"run_id": run["id"], "period": "Октябрь 2026"}).fetchall()
    assert run["parameters"]["status"] == "running"
    mine = next(row for row in rows if row["institution_id"] == str(world.institution))
    assert mine["explanation"]["platforms"]["vk"]["metrics"]["posts"] == 11
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_rating_forecast_job.py tests/test_operations_profiles.py tests/test_rating_forecast_postgres.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/tools/rating_forecast.py operations/systemd/m-ranked-target-rating-forecast.* operations/install/install.py \
  operations/systemd/m-ranked-target.target operations/systemd/m-ranked-target-profile-b-server2.target \
  tests/test_rating_forecast_job.py tests/test_operations_profiles.py tests/test_rating_forecast_postgres.py
git commit -m "feat(rating): nightly forecast snapshot job, retrospective mode and timer"
```

### Task 7: Публичный API и контракт

**Files:**
- Create: `api/routes/rating.py`
- Modify: `api/app.py:130` (подключить `rating`), `contracts/openapi/m-ranked-v1.yaml` (пути и схемы), `contracts/openapi/m-ranked-v1-client.ts` (генерация)
- Test: `tests/test_rating_routes.py` (новый), `tests/test_api_contract.py` (группа)

**Interfaces:**
- Consumes: `api.sql.rating.FORECAST_MONTHS/FORECAST_RUN/FORECAST_ROWS` (Task 5), `rf.month_window`, `rf.period_label`.
- Produces:
  - `GET /api/v1/rating/forecast/months` → `RatingForecastMonths {months: [{month: "YYYY-MM", status, asOf}]}`
  - `GET /api/v1/rating/forecast?month=YYYY-MM` → `RatingForecast` (без `month` — самый новый месяц со снимком); нет снимка → 404
  - `GET /api/v1/rating/own` → `OwnRating {status: "no_methodology", questions: [string]}`
  - `forecast_body(run: dict, rows: list[dict]) -> dict` — чистая сборка ответа
  - Схемы: `RatingForecastMonths`, `RatingForecast`, `RatingForecastRow`, `RatingForecastCell`, `RatingPlatformMetrics`, `OwnRating`

- [ ] **Step 1: Write the failing tests** `tests/test_rating_routes.py`

```python
"""Маршруты «Рейтинга»: сборка ответа по контракту, 404, заглушка."""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from api.errors import NotFound
from api.routes import rating

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "contracts/openapi/m-ranked-v1.yaml"


def validate(body, schema):
    registry = Registry().with_resource("urn:contract", Resource.from_contents(
        yaml.safe_load(CONTRACT.read_text(encoding="utf-8")), default_specification=DRAFT202012))
    errors = list(Draft202012Validator({"$ref": f"urn:contract#/components/schemas/{schema}"},
                                       registry=registry).iter_errors(json.loads(json.dumps(body, default=str))))
    assert not errors, [f"{list(error.path)}: {error.message}" for error in errors]


CELL = {"score": 65.9, "rank": 8, "rankBest": 5, "rankWorst": 14, "baseRank": 11, "source": "formula"}
RUN = {"id": "run", "as_of": datetime(2026, 10, 16, 22, tzinfo=timezone.utc),
       "window_start": datetime(2026, 8, 31, 21, tzinfo=timezone.utc), "version": 1,
       "parameters": {"status": "retrospective", "basePeriod": "Август 2026", "period": "Сентябрь 2026",
                      "errors": {"social": 7, "max": 10, "vk": 9, "rutube": 8}, "postsScale": 1.0, "early": False}}
ROW = {"institution_id": "aac11cf4-9cf6-5b88-b474-9691b38b8235", "legacy_id": 12, "name": "СКФУ",
       "short_name": None, "score": 65.9, "rank": 8,
       "explanation": {"code": "61", "baseConsolidatedRank": None,
                       "categories": {key: dict(CELL) for key in ("social", "max", "vk", "rutube")},
                       "platforms": {"vk": {"source": "formula", "subscores": {"posts": 100.0},
                                            "metrics": {"posts": 120, "postsExtrapolated": 120.0, "avgViews": 950.0,
                                                        "students": 20000, "erv": 0.021}},
                                     "max": {"source": "fallback", "subscores": {}, "metrics": {"posts": 3}},
                                     "rutube": {"source": "no_account", "subscores": {}, "metrics": {}}}},
       "actual": {"social": {"rank": 8, "score": 65.9}, "vk": {"rank": 38, "score": 70.2}}}


def test_forecast_body_matches_the_contract():
    body = rating.forecast_body(RUN, [ROW])
    validate(body, "RatingForecast")
    assert (body["month"], body["status"], body["basePeriod"]) == ("2026-09", "retrospective", "Август 2026")
    row = body["rows"][0]
    assert row["categories"]["social"]["actualRank"] == 8 and row["categories"]["max"]["actualRank"] is None
    assert row["categories"]["vk"]["metrics"]["avgViews"] == 950.0
    assert row["categories"]["max"]["metrics"] is None and "metrics" not in row["categories"]["social"]


def test_months_body_matches_the_contract():
    body = rating.months_body([{"month": "2026-10", "status": "running", "as_of": RUN["as_of"]}])
    validate(body, "RatingForecastMonths")


def test_own_rating_matches_the_contract():
    validate(rating.OWN_RATING, "OwnRating")
    assert rating.OWN_RATING["status"] == "no_methodology" and rating.OWN_RATING["questions"]


@pytest.mark.parametrize("value", ["2026-13", "26-10", "2026-1", "x"])
def test_month_parameter_is_validated(value):
    from api.errors import BadRequest
    with pytest.raises(BadRequest):
        rating.parse_month(value)


def test_missing_snapshot_is_404(monkeypatch):
    class Read:
        async def fetch_all(self, query, params=None): return []
        async def fetch_one(self, query, params=None): return None
    async def serve(_request, _namespace, _query, _tags, build):
        return await build(1, None)
    monkeypatch.setattr(rating, "serve", serve)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(db=Read())))
    with pytest.raises(NotFound):
        asyncio.run(rating.forecast(request, "2026-10"))
```

И в `tests/test_api_contract.py` добавить:

```python
def test_rating_group_is_implemented(contract: dict, app) -> None:
    expected = {"/api/v1/rating/forecast/months", "/api/v1/rating/forecast", "/api/v1/rating/own"}
    assert expected <= set(contract["paths"]) and expected <= implemented_paths(app)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$PY -m pytest tests/test_rating_routes.py tests/test_api_contract.py -q`
Expected: FAIL — `ImportError: cannot import name 'rating' from 'api.routes'`.

- [ ] **Step 3: Write `api/routes/rating.py`**

```python
"""Вкладка «Рейтинг»: снимки прогноза М-Рейтинга и каркас «Нашего рейтинга»."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import dto, rating_forecast as rf
from ..cached import serve
from ..db import Database
from ..errors import BadRequest, NotFound
from ..sql import rating as sql

router = APIRouter(tags=["Query"])

# Снимок пишет ночное задание (событие outbox с этим тегом); каталог даёт
# названия и legacy id; официальный импорт — факт опубликованного месяца.
RATING_TAGS = frozenset({"rating-forecast", "rating", "catalog"})
MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

OWN_RATING = {
    "status": "no_methodology",
    "questions": [
        "Какие площадки входят и с какими весами.",
        "Какие метрики считаются и как нормируются.",
        "На что делим: подписчики, контингент или ничего.",
        "Как учитываются аномальные посты.",
        "За какой период и как часто пересчитывается.",
    ],
}


def parse_month(value: str) -> date:
    match = MONTH.fullmatch(value)
    if not match:
        raise BadRequest("month должен иметь вид ГГГГ-ММ")
    return date(int(match.group(1)), int(match.group(2)), 1)


def months_body(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"months": [{"month": row["month"], "status": row["status"], "asOf": dto.iso(row["as_of"])}
                       for row in rows]}


def _cell(category: str, cell: dict[str, Any], platform: dict[str, Any] | None,
          actual: dict[str, Any] | None) -> dict[str, Any]:
    body = {"score": cell["score"], "rank": cell["rank"], "rankBest": cell["rankBest"],
            "rankWorst": cell["rankWorst"], "baseRank": cell.get("baseRank"), "source": cell["source"],
            "actualRank": (actual or {}).get("rank"),
            "actualScore": float(actual["score"]) if actual and actual.get("score") is not None else None}
    if category != "social":
        metrics = (platform or {}).get("metrics") or {}
        body["metrics"] = ({key: metrics.get(key) for key in ("posts", "postsExtrapolated", "avgViews", "students", "erv")}
                           if (platform or {}).get("source") == "formula" else None)
    return body


def forecast_body(run: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    parameters = run["parameters"]
    items = []
    for row in rows:
        explanation = row["explanation"]
        actual = row.get("actual") or {}
        items.append({
            "institutionId": row["institution_id"], "legacyId": row["legacy_id"], "name": row["name"],
            "shortName": row["short_name"], "baseConsolidatedRank": explanation.get("baseConsolidatedRank"),
            "categories": {category: _cell(category, explanation["categories"][category],
                                           explanation["platforms"].get(category), actual.get(category))
                           for category in rf.CATEGORIES},
        })
    window = run["window_start"].astimezone(rf.MOSCOW)
    return {"month": f"{window.year:04d}-{window.month:02d}", "status": parameters["status"],
            "period": parameters["period"], "basePeriod": parameters["basePeriod"],
            "asOf": dto.iso(run["as_of"]), "early": bool(parameters.get("early")),
            "formulaVersion": run["version"], "errors": parameters["errors"], "rows": items}


@router.get("/api/v1/rating/forecast/months")
async def forecast_months(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        return months_body(await db.fetch_all(sql.FORECAST_MONTHS, {"formula_key": rf.FORMULA_KEY}))

    return await serve(request, "rating-forecast-months", {}, RATING_TAGS, build)


@router.get("/api/v1/rating/forecast")
async def forecast(request: Request, month: str | None = Query(None)) -> Response:
    selected = parse_month(month) if month is not None else None

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        target = selected
        if target is None:
            months = await db.fetch_all(sql.FORECAST_MONTHS, {"formula_key": rf.FORMULA_KEY})
            if not months:
                raise NotFound("снимков прогноза ещё нет")
            target = parse_month(months[0]["month"])
        run = await db.fetch_one(sql.FORECAST_RUN, {"formula_key": rf.FORMULA_KEY,
                                                    "window_start": rf.month_window(target)[0]})
        if run is None:
            raise NotFound("за этот месяц снимка прогноза нет")
        rows = await db.fetch_all(sql.FORECAST_ROWS, {"run_id": run["id"], "period": rf.period_label(target)})
        return forecast_body(run, rows)

    return await serve(request, "rating-forecast", {"month": month}, RATING_TAGS, build)


@router.get("/api/v1/rating/own")
async def own_rating(request: Request) -> Response:
    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        return OWN_RATING

    return await serve(request, "rating-own", {}, frozenset({"rating-own"}), build)
```

Проверить: (1) `dto.iso` существует (используется в `api/routes/site.py`); (2) `NotFound` принимает строку (см. `api/errors.py`); (3) исключение внутри `build` превращается в 404 через `serve` — посмотреть `_build_or_wait` в `api/cached.py`; если `serve` глотает исключение, поднять `NotFound` до вызова `serve` отдельным `fetch_one` (тогда поправить тест). В `api/app.py` добавить `rating` в импорт роутеров и в кортеж `for module in (...)`.

- [ ] **Step 4: Contract** — в `contracts/openapi/m-ranked-v1.yaml` после `/api/v1/site/summary` добавить три пути по образцу `getSiteSummary` (`tags: [Query]`, `security: []`, параметр `IfNoneMatch`, ответы `200` с `ETag`/`PublicCache`, `304`, `500`; у `getRatingForecast` — query-параметр `month` `{type: string, pattern: '^\d{4}-(0[1-9]|1[0-2])$'}`, ответы `400` (`$ref: '#/components/responses/InvalidRequest'`) и `404` (`$ref: '#/components/responses/NotFound'`)). `operationId`: `getRatingForecastMonths`, `getRatingForecast`, `getOwnRating`. Схемы:

```yaml
    RatingForecastStatus:
      type: string
      enum: [running, final, published, retrospective]
    RatingForecastMonths:
      type: object
      additionalProperties: false
      required: [months]
      properties:
        months:
          type: array
          items:
            type: object
            additionalProperties: false
            required: [month, status, asOf]
            properties:
              month: { type: string, pattern: '^\d{4}-(0[1-9]|1[0-2])$' }
              status: { $ref: '#/components/schemas/RatingForecastStatus' }
              asOf: { type: string, format: date-time }
    RatingPlatformMetrics:
      type: object
      additionalProperties: false
      required: [posts, postsExtrapolated, avgViews, students, erv]
      properties:
        posts: { type: integer, minimum: 0 }
        postsExtrapolated: { type: number, minimum: 0 }
        avgViews: { type: ['number', 'null'], minimum: 0 }
        students: { type: ['integer', 'null'], minimum: 0 }
        erv: { type: ['number', 'null'], minimum: 0 }
    RatingForecastCell:
      type: object
      additionalProperties: false
      required: [score, rank, rankBest, rankWorst, baseRank, source, actualRank, actualScore]
      properties:
        score: { type: number, minimum: 0, maximum: 100 }
        rank: { type: integer, minimum: 1 }
        rankBest: { type: integer, minimum: 1 }
        rankWorst: { type: integer, minimum: 1 }
        baseRank: { type: ['integer', 'null'], minimum: 1, description: 'Official place in the base (last published) month.' }
        source: { type: string, enum: [formula, fallback, no_account, partial], description: 'fallback — our data does not cover the month, the base official score is used; partial — the social score includes a fallback platform.' }
        actualRank: { type: ['integer', 'null'], minimum: 1 }
        actualScore: { type: ['number', 'null'] }
        metrics:
          oneOf:
            - { $ref: '#/components/schemas/RatingPlatformMetrics' }
            - { type: 'null' }
    RatingForecastRow:
      type: object
      additionalProperties: false
      required: [institutionId, legacyId, name, shortName, baseConsolidatedRank, categories]
      properties:
        institutionId: { type: string, format: uuid }
        legacyId: { type: ['integer', 'null'], minimum: 1 }
        name: { type: string }
        shortName: { type: ['string', 'null'] }
        baseConsolidatedRank: { type: ['integer', 'null'], minimum: 1 }
        categories:
          type: object
          additionalProperties: false
          required: [social, max, vk, rutube]
          properties:
            social: { $ref: '#/components/schemas/RatingForecastCell' }
            max: { $ref: '#/components/schemas/RatingForecastCell' }
            vk: { $ref: '#/components/schemas/RatingForecastCell' }
            rutube: { $ref: '#/components/schemas/RatingForecastCell' }
    RatingForecast:
      type: object
      additionalProperties: false
      required: [month, status, period, basePeriod, asOf, early, formulaVersion, errors, rows]
      properties:
        month: { type: string, pattern: '^\d{4}-(0[1-9]|1[0-2])$' }
        status: { $ref: '#/components/schemas/RatingForecastStatus' }
        period: { type: string }
        basePeriod: { type: string, description: 'Last published official month; supplies the scores of untracked institutions and fallbacks.' }
        asOf: { type: string, format: date-time }
        early: { type: boolean, description: 'Running month before its 7th day.' }
        formulaVersion: { type: integer, minimum: 1 }
        errors:
          type: object
          additionalProperties: false
          required: [social, max, vk, rutube]
          properties:
            social: { type: number, minimum: 0 }
            max: { type: number, minimum: 0 }
            vk: { type: number, minimum: 0 }
            rutube: { type: number, minimum: 0 }
        rows: { type: array, items: { $ref: '#/components/schemas/RatingForecastRow' } }
    OwnRating:
      type: object
      additionalProperties: false
      required: [status, questions]
      properties:
        status: { type: string, enum: [no_methodology] }
        questions: { type: array, items: { type: string } }
```

Затем: `cd frontend && npx -y pnpm@11.19.0 generate:api` (обновит `contracts/openapi/m-ranked-v1-client.ts`).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_rating_routes.py tests/test_api_contract.py tests/test_api_responses.py -q && (cd frontend && npx -y pnpm@11.19.0 check:api)`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/routes/rating.py api/app.py contracts/openapi tests/test_rating_routes.py tests/test_api_contract.py
git commit -m "feat(api): /api/v1/rating forecast months, snapshot and own-rating placeholder"
```

### Task 8: Данные фронта

**Files:**
- Create: `frontend/lib/rating.ts`
- Modify: `frontend/lib/api.ts:137` (методы), `frontend/lib/types.ts` (типы), `frontend/tests/api-fixture.mts` (ответы фикстуры)
- Test: `frontend/tests/rating.test.ts`

**Interfaces:**
- Consumes: схемы контракта (Task 7).
- Produces:
  - типы `RatingForecast`, `RatingForecastRow`, `RatingForecastCell`, `RatingForecastMonths`, `OwnRating`, `RatingCategory = "social" | "max" | "vk" | "rutube"`
  - `api.ratingForecastMonths()`, `api.ratingForecast(month?: string)`, `api.ownRating()`
  - `RATING_CATEGORIES: readonly {value: RatingCategory; label: string}[]` — Соцсети, MAX, VK, Rutube
  - `normalizeCategory(raw: string | string[] | undefined): RatingCategory`
  - `normalizeMonth(raw: string | string[] | undefined): string | null`
  - `statusLine(forecast: Pick<RatingForecast, "status" | "asOf" | "early">): string`
  - `rankLabel(cell: RatingForecastCell): string` — `"8"` или `"8 (5–14)"`
  - `rankDelta(cell: RatingForecastCell): number | null` — `baseRank − rank`
  - `rowsFor(rows: RatingForecastRow[], category: RatingCategory): RatingForecastRow[]` — по месту категории
  - `scatterPoints(rows, category): {name: string; predicted: number; actual: number}[]`
  - `hasActual(forecast): boolean` — `published` или `retrospective`

- [ ] **Step 1: Write the failing tests** `frontend/tests/rating.test.ts`

```ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { hasActual, normalizeCategory, normalizeMonth, rankDelta, rankLabel, rowsFor, scatterPoints, statusLine } from "../lib/rating";
import type { RatingForecastCell, RatingForecastRow } from "../lib/types";

const cell = (rank: number, extra: Partial<RatingForecastCell> = {}): RatingForecastCell => ({
  score: 60, rank, rankBest: rank, rankWorst: rank, baseRank: null, source: "formula", actualRank: null, actualScore: null, ...extra,
});
const row = (name: string, social: number, vk: number, actual: number | null = null): RatingForecastRow => ({
  institutionId: "00000000-0000-0000-0000-000000000001", legacyId: 1, name, shortName: null, baseConsolidatedRank: null,
  categories: { social: cell(social, { actualRank: actual }), max: cell(1), vk: cell(vk), rutube: cell(1) },
});

test("category and month parameters fall back safely", () => {
  assert.equal(normalizeCategory("vk"), "vk");
  assert.equal(normalizeCategory(["rutube", "vk"]), "rutube");
  assert.equal(normalizeCategory("telegram"), "social");
  assert.equal(normalizeMonth("2026-10"), "2026-10");
  assert.equal(normalizeMonth("2026-13"), null);
  assert.equal(normalizeMonth(undefined), null);
});

test("rank label shows the range only when it is wider than the rank", () => {
  assert.equal(rankLabel(cell(8)), "8");
  assert.equal(rankLabel(cell(8, { rankBest: 5, rankWorst: 14 })), "8 (5–14)");
});

test("delta is positive when the institution climbs", () => {
  assert.equal(rankDelta(cell(8, { baseRank: 11 })), 3);
  assert.equal(rankDelta(cell(8)), null);
});

test("rows are ordered by the selected category", () => {
  const rows = [row("А", 2, 9), row("Б", 1, 3)];
  assert.deepEqual(rowsFor(rows, "social").map((item) => item.name), ["Б", "А"]);
  assert.deepEqual(rowsFor(rows, "vk").map((item) => item.name), ["Б", "А"]);
  assert.deepEqual(rowsFor([row("А", 2, 1), row("Б", 1, 3)], "vk").map((item) => item.name), ["А", "Б"]);
});

test("scatter keeps only rows with an actual place", () => {
  assert.deepEqual(scatterPoints([row("А", 2, 1, 4), row("Б", 1, 3)], "social"), [{ name: "А", predicted: 2, actual: 4 }]);
});

test("status line speaks plain Russian", () => {
  assert.equal(statusLine({ status: "running", asOf: "2026-10-15T22:10:00Z", early: false }), "Месяц не закончен, данные на 16.10");
  assert.equal(statusLine({ status: "running", asOf: "2026-11-02T22:10:00Z", early: true }),
    "Месяц не закончен, данные на 03.11 — слишком рано для уверенной оценки");
  assert.equal(statusLine({ status: "final", asOf: "2026-11-05T22:10:00Z", early: false }), "Итоговый прогноз: месяц закончен, официального списка ещё нет");
  assert.equal(statusLine({ status: "published", asOf: "2026-11-12T22:10:00Z", early: false }), "Опубликовано — прогноз против факта");
  assert.equal(statusLine({ status: "retrospective", asOf: "2026-10-16T22:10:00Z", early: false }),
    "Ретроспективный расчёт, не прогноз до публикации");
  assert.equal(hasActual({ status: "retrospective" }), true);
  assert.equal(hasActual({ status: "final" }), false);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && node --import tsx --test tests/rating.test.ts`
Expected: FAIL — `Cannot find module '../lib/rating'`.

- [ ] **Step 3: Write the implementation**

`frontend/lib/types.ts` — добавить:

```ts
export type RatingForecast = components["schemas"]["RatingForecast"];
export type RatingForecastRow = components["schemas"]["RatingForecastRow"];
export type RatingForecastCell = components["schemas"]["RatingForecastCell"];
export type RatingForecastMonths = components["schemas"]["RatingForecastMonths"];
export type OwnRating = components["schemas"]["OwnRating"];
export type RatingCategory = keyof RatingForecastRow["categories"];
```

`frontend/lib/api.ts` — после `siteSummary()`:

```ts
    ratingForecastMonths() {
      return client.GET("/api/v1/rating/forecast/months", {}).then(unwrap);
    },
    ratingForecast(month?: string) {
      return client.GET("/api/v1/rating/forecast", { params: { query: month ? { month } : {} } }).then(unwrap);
    },
    ownRating() {
      return client.GET("/api/v1/rating/own", {}).then(unwrap);
    },
```

`frontend/lib/rating.ts`:

```ts
/** «Рейтинг»: параметры адреса, подписи и порядок строк прогноза. Без React,
 *  чтобы страница и тесты считали одинаково. */
import type { RatingCategory, RatingForecast, RatingForecastCell, RatingForecastRow } from "./types";

export const RATING_CATEGORIES = [
  { value: "social", label: "Соцсети" },
  { value: "max", label: "MAX" },
  { value: "vk", label: "VK" },
  { value: "rutube", label: "Rutube" },
] as const satisfies readonly { value: RatingCategory; label: string }[];

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;

function single(raw: string | string[] | undefined): string | undefined {
  return Array.isArray(raw) ? raw[0] : raw;
}

export function normalizeCategory(raw: string | string[] | undefined): RatingCategory {
  const value = single(raw);
  return RATING_CATEGORIES.find((item) => item.value === value)?.value ?? "social";
}

export function normalizeMonth(raw: string | string[] | undefined): string | null {
  const value = single(raw);
  return value && MONTH.test(value) ? value : null;
}

function moscowDay(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "2-digit", timeZone: "Europe/Moscow" }).format(new Date(iso));
}

export function statusLine(forecast: Pick<RatingForecast, "status" | "asOf" | "early">): string {
  switch (forecast.status) {
    case "running":
      return `Месяц не закончен, данные на ${moscowDay(forecast.asOf)}${forecast.early ? " — слишком рано для уверенной оценки" : ""}`;
    case "final":
      return "Итоговый прогноз: месяц закончен, официального списка ещё нет";
    case "published":
      return "Опубликовано — прогноз против факта";
    case "retrospective":
      return "Ретроспективный расчёт, не прогноз до публикации";
  }
}

export function hasActual(forecast: Pick<RatingForecast, "status">): boolean {
  return forecast.status === "published" || forecast.status === "retrospective";
}

export function rankLabel(cell: RatingForecastCell): string {
  return cell.rankBest === cell.rankWorst ? String(cell.rank) : `${cell.rank} (${cell.rankBest}–${cell.rankWorst})`;
}

export function rankDelta(cell: RatingForecastCell): number | null {
  return cell.baseRank === null ? null : cell.baseRank - cell.rank;
}

export function rowsFor(rows: RatingForecastRow[], category: RatingCategory): RatingForecastRow[] {
  return [...rows].sort((left, right) => left.categories[category].rank - right.categories[category].rank
    || left.name.localeCompare(right.name, "ru"));
}

export function scatterPoints(rows: RatingForecastRow[], category: RatingCategory) {
  return rows.flatMap((row) => {
    const cell = row.categories[category];
    return cell.actualRank === null ? [] : [{ name: row.shortName ?? row.name, predicted: cell.rank, actual: cell.actualRank }];
  });
}
```

`frontend/tests/api-fixture.mts` — перед `/api/v1/sitemap` добавить ответы (типы `Schema[...]` — как у соседних):

```ts
  if (url.pathname === "/api/v1/rating/forecast/months") return json({ months: [
    { month: "2026-10", status: "running", asOf: "2026-10-15T22:10:00Z" },
    { month: "2026-09", status: "retrospective", asOf: "2026-10-16T22:10:00Z" },
  ] } satisfies Schema["RatingForecastMonths"]);
  if (url.pathname === "/api/v1/rating/forecast") return json(ratingForecast(url.searchParams.get("month") ?? "2026-10"));
  if (url.pathname === "/api/v1/rating/own") return json({ status: "no_methodology",
    questions: ["Какие площадки входят и с какими весами."] } satisfies Schema["OwnRating"]);
```

и функцию рядом с `dashboard(...)`:

```ts
function ratingForecast(month: string): Schema["RatingForecast"] {
  const retrospective = month === "2026-09";
  const cell = (rank: number, source: Schema["RatingForecastCell"]["source"] = "formula", actual: number | null = null) => ({
    score: 70 - rank, rank, rankBest: Math.max(1, rank - 3), rankWorst: rank + 6, baseRank: rank + 2, source,
    actualRank: retrospective ? (actual ?? rank + 1) : null, actualScore: retrospective ? 69 - rank : null,
    metrics: { posts: 90, postsExtrapolated: 120, avgViews: 800, students: 12000, erv: 0.02 },
  });
  const social = (rank: number, source: Schema["RatingForecastCell"]["source"] = "formula") => {
    const { metrics: _metrics, ...rest } = cell(rank, source);
    return rest;
  };
  const rows = [
    { institutionId: uuid(9, 1), legacyId: 1, name: "Северо-Кавказский федеральный университет", shortName: "СКФУ", baseConsolidatedRank: null,
      categories: { social: social(8), max: cell(27), vk: cell(38), rutube: cell(13) } },
    { institutionId: uuid(9, 2), legacyId: 2, name: "Нижневартовский государственный университет", shortName: null, baseConsolidatedRank: 40,
      categories: { social: social(20, "partial"), max: cell(30), vk: { ...cell(25, "fallback"), metrics: null }, rutube: cell(60) } },
  ];
  return { month, status: retrospective ? "retrospective" : "running", period: retrospective ? "Сентябрь 2026" : "Октябрь 2026",
    basePeriod: retrospective ? "Август 2026" : "Сентябрь 2026", asOf: "2026-10-15T22:10:00Z", early: false, formulaVersion: 1,
    errors: { social: 7, max: 10, vk: 9, rutube: 8 }, rows };
}
```

(`uuid(a, b)` — существующий помощник фикстуры; если сигнатура другая — использовать её.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && node --import tsx --test tests/rating.test.ts && npx -y pnpm@11.19.0 typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/rating.ts frontend/lib/api.ts frontend/lib/types.ts frontend/tests/rating.test.ts frontend/tests/api-fixture.mts
git commit -m "feat(frontend): rating forecast data layer — client, labels, ordering, fixture"
```

### Task 9: Страницы «Рейтинга»

Перед этой задачей вызвать скилы `frontend-design` (внешний вид таблицы, вкладок, пометок) и `dataviz` (разброс «прогноз против факта»): код ниже — каркас поведения и разметки, стиль доводится по их указаниям в рамках существующих токенов (`globals.css`), без новых зависимостей.

**Files:**
- Modify: `frontend/lib/nav-links.ts`, `frontend/lib/methodology.ts`, `frontend/tests/browser/parity.spec.ts:12`
- Create: `frontend/app/rating/page.tsx`, `frontend/app/rating/own/page.tsx`, `frontend/components/rating/rating-tabs.tsx`, `frontend/components/rating/forecast-table.tsx`, `frontend/components/rating/forecast-scatter.tsx`, `frontend/components/rating/method-block.tsx`, `frontend/content/methodology/rating-forecast.mdx`
- Test: `frontend/tests/browser/rating.spec.ts`

**Interfaces:**
- Consumes: `api.ratingForecastMonths/ratingForecast/ownRating`, `frontend/lib/rating.ts` (Task 8).
- Produces: маршруты `/rating`, `/rating/own`; статья `/methodology/rating-forecast`; пункт меню «Рейтинг».

- [ ] **Step 1: Write the failing e2e tests** `frontend/tests/browser/rating.spec.ts`

```ts
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("меню ведёт на «Рейтинг» после «Сравнения», без параметра площадки", async ({ page }) => {
  await page.goto("/review?platform=vk");
  const links = page.getByTestId("main-nav").locator("a");
  const labels = await links.allTextContents();
  expect(labels.indexOf("Рейтинг")).toBe(labels.indexOf("Сравнение") + 1);
  await expect(page.getByTestId("main-nav").getByRole("link", { name: "Рейтинг" })).toHaveAttribute("href", "/rating");
});

test("прогноз: статус, категории, диапазон места и пометка неполных данных", async ({ page }) => {
  await page.goto("/rating");
  await expect(page.getByRole("heading", { level: 1, name: "Рейтинг" })).toBeVisible();
  await expect(page.getByTestId("rating-status")).toContainText("Месяц не закончен");
  await expect(page.getByTestId("rating-row").first()).toContainText("СКФУ");
  await expect(page.getByTestId("rating-row").first()).toContainText("8 (5–14)");
  await page.getByTestId("rating-category").getByRole("link", { name: "VK" }).click();
  await expect(page).toHaveURL(/category=vk/);
  await expect(page.getByTestId("rating-row").filter({ hasText: "Нижневартовский" })).toContainText("нет полных данных");
  await expect(page.getByTestId("rating-scatter")).toHaveCount(0);
  const axe = await new AxeBuilder({ page }).include("main").analyze();
  expect(axe.violations).toEqual([]);
});

test("ретроспективный месяц показывает факт, ошибку и разброс", async ({ page }) => {
  await page.goto("/rating?month=2026-09");
  await expect(page.getByTestId("rating-status")).toContainText("Ретроспективный расчёт");
  await expect(page.getByRole("columnheader", { name: "Факт" })).toBeVisible();
  await expect(page.getByTestId("rating-scatter")).toBeVisible();
});

test("«Наш рейтинг» — каркас с открытыми вопросами", async ({ page }) => {
  await page.goto("/rating/own");
  await expect(page.getByTestId("rating-tabs").getByRole("link", { name: "Наш рейтинг" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("Методика в разработке")).toBeVisible();
  await expect(page.getByText("Какие площадки входят и с какими весами.")).toBeVisible();
});
```

И в `frontend/tests/browser/parity.spec.ts` строку проверки заменить на:

```ts
      // Методология и «Рейтинг» одни на все площадки и параметра не несут.
      expect(href.searchParams.get("platform")).toBe(["/methodology", "/rating"].includes(href.pathname) ? null : platform);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx -y pnpm@11.19.0 exec playwright test tests/browser/rating.spec.ts`
Expected: FAIL — нет пункта меню «Рейтинг», `/rating` — 404.

- [ ] **Step 3: Navigation and methodology entry**

`frontend/lib/nav-links.ts` — после строки `/compare`:

```ts
  // Прогноз М-Рейтинга и наш рейтинг — по всем площадкам сразу: параметр площадки не передаётся.
  { href: "/rating", label: "Рейтинг", platformless: true },
```

`frontend/lib/methodology.ts` — в `ARTICLES` после `comparison`:

```ts
  { slug: "rating-forecast", title: "Прогноз М-Рейтинга", description: "Как мы оцениваем место вуза в официальном рейтинге по соцсетям до публикации и чего не знаем." },
```

- [ ] **Step 4: Components**

`frontend/components/rating/rating-tabs.tsx`:

```tsx
import Link from "@/components/native-link";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { href: "/rating", label: "Прогноз М-Рейтинга" },
  { href: "/rating/own", label: "Наш рейтинг" },
] as const;

/** Два раздела «Рейтинга» — два адреса, как разделы «Находок». */
export function RatingTabs({ active }: { active: "/rating" | "/rating/own" }) {
  return <nav aria-label="Раздел рейтинга" data-testid="rating-tabs"
    className="bg-muted text-muted-foreground mb-5 inline-grid w-full grid-cols-2 rounded-lg p-[3px] sm:w-auto">
    {SECTIONS.map((section) => <Link key={section.href} href={section.href} prefetch={false}
      aria-current={section.href === active ? "page" : undefined}
      className={cn("rounded-md px-3 py-1 text-center text-sm font-medium whitespace-nowrap transition-colors",
        section.href === active ? "bg-background text-foreground shadow-sm" : "hover:text-foreground")}>
      {section.label}
    </Link>)}
  </nav>;
}
```

`frontend/components/rating/forecast-table.tsx`:

```tsx
import Link from "@/components/native-link";
import { hasActual, rankDelta, rankLabel, rowsFor } from "@/lib/rating";
import type { RatingCategory, RatingForecast, RatingForecastCell } from "@/lib/types";

const PLATFORM_COLUMNS = [["max", "MAX"], ["vk", "VK"], ["rutube", "Rutube"]] as const;

function sourceNote(cell: RatingForecastCell, basePeriod: string): string | null {
  if (cell.source === "fallback") return `нет полных данных — взят балл за ${basePeriod.toLowerCase()}`;
  if (cell.source === "partial") return "часть площадок — по баллу прошлого месяца";
  if (cell.source === "no_account") return "аккаунта нет — 0, как в официальном рейтинге";
  return null;
}

function Delta({ value }: { value: number | null }) {
  if (value === null || value === 0) return <span className="text-muted-foreground">—</span>;
  return <span className={value > 0 ? "text-emerald-700 dark:text-emerald-400" : "text-rose-700 dark:text-rose-400"}>
    {value > 0 ? `↑${value}` : `↓${-value}`}</span>;
}

export function ForecastTable({ forecast, category }: { forecast: RatingForecast; category: RatingCategory }) {
  const actual = hasActual(forecast);
  // Сводное место прошлого месяца — справка, не прогноз; есть с первого импорта после выкатки.
  const consolidated = category === "social" && forecast.rows.some((row) => row.baseConsolidatedRank !== null);
  return <div className="overflow-x-auto">
    <table className="w-full min-w-[640px] text-sm tabular-nums">
      <caption className="sr-only">Прогноз мест: {forecast.period}</caption>
      <thead className="text-muted-foreground text-left text-xs">
        <tr>
          <th scope="col" className="py-2 pr-3">Прогноз места</th>
          <th scope="col" className="py-2 pr-3">Вуз</th>
          <th scope="col" className="py-2 pr-3 text-right">Балл</th>
          <th scope="col" className="py-2 pr-3 text-right" title={`Против места за ${forecast.basePeriod.toLowerCase()}`}>Δ</th>
          {category === "social" ? PLATFORM_COLUMNS.map(([key, label]) =>
            <th key={key} scope="col" className="py-2 pr-3 text-right">{label}</th>) : null}
          {consolidated ? <th scope="col" className="py-2 pr-3 text-right" title="Справка: сводный рейтинг не прогнозируется">
            Сводное, {forecast.basePeriod.toLowerCase()}</th> : null}
          {actual ? <><th scope="col" className="py-2 pr-3 text-right">Факт</th><th scope="col" className="py-2 text-right">Ошибка</th></> : null}
        </tr>
      </thead>
      <tbody>
        {rowsFor(forecast.rows, category).map((row) => {
          const cell = row.categories[category];
          const note = sourceNote(cell, forecast.basePeriod);
          return <tr key={row.institutionId} data-testid="rating-row" className="border-t">
            <td className="py-2 pr-3 font-semibold whitespace-nowrap">{rankLabel(cell)}</td>
            <td className="py-2 pr-3">
              {row.legacyId ? <Link href={`/institutions/${row.legacyId}`} prefetch={false} className="hover:underline">{row.shortName ?? row.name}</Link>
                : row.shortName ?? row.name}
              {note ? <span className="text-muted-foreground block text-xs">{note}</span> : null}
            </td>
            <td className="py-2 pr-3 text-right">{cell.score.toFixed(1)}</td>
            <td className="py-2 pr-3 text-right"><Delta value={rankDelta(cell)} /></td>
            {category === "social" ? PLATFORM_COLUMNS.map(([key]) =>
              <td key={key} className="py-2 pr-3 text-right">{row.categories[key].score.toFixed(1)}</td>) : null}
            {consolidated ? <td className="text-muted-foreground py-2 pr-3 text-right">{row.baseConsolidatedRank ?? "—"}</td> : null}
            {actual ? <>
              <td className="py-2 pr-3 text-right">{cell.actualRank ?? "—"}</td>
              <td className="py-2 text-right">{cell.actualRank === null ? "—" : cell.actualRank - cell.rank}</td>
            </> : null}
          </tr>;
        })}
      </tbody>
    </table>
  </div>;
}
```

`frontend/components/rating/forecast-scatter.tsx`:

```tsx
"use client";

import { CartesianGrid, ReferenceLine, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";

const config = { place: { label: "Вуз", color: "var(--chart-1)" } } satisfies ChartConfig;

/** Прогнозное место против фактического: на диагонали — точный прогноз. */
export function ForecastScatter({ points, total = 233 }: { points: { name: string; predicted: number; actual: number }[]; total?: number }) {
  const limit = Math.min(total, Math.max(20, ...points.map((point) => Math.max(point.predicted, point.actual))) + 5);
  return <figure data-testid="rating-scatter" className="mt-6">
    <figcaption className="text-muted-foreground mb-2 text-sm">Прогноз против факта: точка — вуз, на диагонали — точный прогноз</figcaption>
    <ChartContainer config={config} className="aspect-square h-[320px] w-full max-w-[420px]">
      <ScatterChart margin={{ top: 8, right: 8, bottom: 24, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" dataKey="predicted" name="Прогноз" domain={[1, limit]} reversed={false}
          label={{ value: "Прогноз места", position: "insideBottom", offset: -12 }} />
        <YAxis type="number" dataKey="actual" name="Факт" domain={[1, limit]} reversed
          label={{ value: "Факт", angle: -90, position: "insideLeft" }} />
        <ReferenceLine segment={[{ x: 1, y: 1 }, { x: limit, y: limit }]} stroke="var(--muted-foreground)" strokeDasharray="4 4" />
        <Tooltip cursor={false} formatter={(value: number, key: string) => [value, key === "predicted" ? "Прогноз" : "Факт"]}
          labelFormatter={() => ""} />
        <Scatter data={points} fill="var(--color-place)" />
      </ScatterChart>
    </ChartContainer>
  </figure>;
}
```

`frontend/components/rating/method-block.tsx`:

```tsx
import Link from "@/components/native-link";
import type { RatingForecast } from "@/lib/types";

export function ForecastMethod({ forecast }: { forecast: RatingForecast }) {
  return <section aria-labelledby="rating-method" className="bg-muted/40 mt-8 rounded-lg p-4 text-sm">
    <h2 id="rating-method" className="font-heading mb-2 text-base font-semibold">Как считается прогноз</h2>
    <p>Соцсети = 0.4 · MAX + 0.3 · VK + 0.3 · Rutube. Балл VK и MAX — среднее трёх шкал: число публикаций за месяц,
      средние просмотры публикации на одного студента и вовлечённость (реакции, комментарии и репосты к просмотрам).
      Rutube: меньше 5 видео — 0. Места — среди всех вузов официального рейтинга; вузы, которых мы не отслеживаем,
      стоят с баллами за {forecast.basePeriod.toLowerCase()}.</p>
    <p className="mt-2">Типичная ошибка балла: соцсети ±{forecast.errors.social}, MAX ±{forecast.errors.max},
      VK ±{forecast.errors.vk}, Rutube ±{forecast.errors.rutube}; в скобках — места при такой ошибке.
      СМИ, сайт и повестка МОН не прогнозируются. Формула, версия {forecast.formulaVersion}.</p>
    <p className="mt-2"><Link href="/methodology/rating-forecast" className="underline">Методика и ограничения</Link></p>
  </section>;
}
```

- [ ] **Step 5: Pages**

`frontend/app/rating/page.tsx`:

```tsx
import type { Metadata } from "next";
import Link from "@/components/native-link";
import { ForecastMethod } from "@/components/rating/method-block";
import { ForecastScatter } from "@/components/rating/forecast-scatter";
import { ForecastTable } from "@/components/rating/forecast-table";
import { RatingTabs } from "@/components/rating/rating-tabs";
import { ApiFailureState, EmptyState, PageHeader } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { hasActual, normalizeCategory, normalizeMonth, RATING_CATEGORIES, scatterPoints, statusLine } from "@/lib/rating";
import { queryHref, type SearchParams } from "@/lib/params";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Рейтинг: прогноз М-Рейтинга",
  description: "Какое место вуз получит в официальном М-Рейтинге по соцсетям — оценка по нашим данным до публикации.",
};

export default async function RatingPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const raw = await searchParams;
  const category = normalizeCategory(raw.category);
  const month = normalizeMonth(raw.month);
  let months, forecast, total;
  try {
    const [summary, list] = await Promise.all([api.siteSummary(), api.ratingForecastMonths()]);
    months = list;
    total = summary.ratingInstitutions ?? 233;
    forecast = months.months.length ? await api.ratingForecast(month ?? undefined) : null;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) forecast = null;
    else return <ApiFailureState retryHref="/rating" />;
  }
  return <>
    <PageHeader title="Рейтинг" description="Оценка места вуза в официальном М-Рейтинге Минобрнауки по соцсетям — по нашим данным, до публикации официального списка." />
    <RatingTabs active="/rating" />
    {!forecast ? <EmptyState title="Снимков прогноза ещё нет" description="Первый снимок появится после ночного расчёта." /> : <>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <nav aria-label="Месяц" className="flex flex-wrap gap-2 text-sm">
          {(months?.months ?? []).map((item) => <Link key={item.month} href={queryHref("/rating", { month: item.month, category })}
            prefetch={false} aria-current={item.month === forecast.month ? "page" : undefined}
            className={cn("rounded-md border px-2 py-1", item.month === forecast.month && "bg-foreground text-background")}>
            {item.month}</Link>)}
        </nav>
        <p data-testid="rating-status" className="text-muted-foreground text-sm">{statusLine(forecast)}</p>
      </div>
      <nav aria-label="Категория" data-testid="rating-category" className="mb-4 flex gap-2 text-sm">
        {RATING_CATEGORIES.map((item) => <Link key={item.value} href={queryHref("/rating", { month: forecast.month, category: item.value })}
          prefetch={false} aria-current={item.value === category ? "page" : undefined}
          className={cn("rounded-md px-3 py-1", item.value === category ? "bg-muted text-foreground font-medium" : "text-muted-foreground")}>
          {item.label}</Link>)}
      </nav>
      <p className="text-muted-foreground mb-3 text-xs">Только соцсети: СМИ, сайт и повестка МОН не прогнозируются.
        Места — из {total} вузов официального рейтинга.</p>
      <ForecastTable forecast={forecast} category={category} />
      {hasActual(forecast) ? <ForecastScatter points={scatterPoints(forecast.rows, category)} total={total ?? 233} /> : null}
      <ForecastMethod forecast={forecast} />
    </>}
  </>;
}
```

`EmptyState({title, description})` и `queryHref(path, values)` — существующие (`components/ui.tsx:129`, `lib/params.ts:104`). Сводное место прошлого месяца — справочный столбец во вкладке «Соцсети» (появляется, когда импорт начнёт хранить сводный балл, Task 3).

`frontend/app/rating/own/page.tsx`:

```tsx
import type { Metadata } from "next";
import { RatingTabs } from "@/components/rating/rating-tabs";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Рейтинг: наш рейтинг",
  description: "Собственный рейтинг вузов по соцсетям — методика в разработке.",
};

export default async function OwnRatingPage() {
  let own;
  try { own = await api.ownRating(); } catch { return <ApiFailureState retryHref="/rating/own" />; }
  return <>
    <PageHeader title="Рейтинг" description="Собственный вариант расчёта по нашим данным отслеживания." />
    <RatingTabs active="/rating/own" />
    <section aria-labelledby="own-method" className="bg-muted/40 rounded-lg p-4 text-sm">
      <h2 id="own-method" className="font-heading mb-2 text-base font-semibold">Методика в разработке</h2>
      <p className="mb-2">Здесь появится наш рейтинг, когда будет выбрана методика. Открытые вопросы:</p>
      <ul className="list-disc pl-5">{own.questions.map((question) => <li key={question}>{question}</li>)}</ul>
    </section>
    <div className="mt-6 overflow-x-auto" aria-hidden="true">
      <table className="text-muted-foreground w-full min-w-[480px] text-sm">
        <thead><tr className="text-left text-xs"><th className="py-2">Место</th><th className="py-2">Вуз</th><th className="py-2 text-right">Балл</th></tr></thead>
        <tbody><tr className="border-t"><td className="py-6 text-center" colSpan={3}>Таблица появится вместе с методикой</td></tr></tbody>
      </table>
    </div>
  </>;
}
```

`frontend/content/methodology/rating-forecast.mdx` (оформление заголовков — как в `comparison.mdx`):

```mdx
Прогноз — наша оценка места вуза в официальном М-Рейтинге Минобрнауки (m-rating.ru) по соцсетям до
публикации официального списка. Источник публикует только итоговые баллы, без исходных метрик, поэтому
формула подобрана по опубликованным месяцам и может расходиться с официальной.

## Что прогнозируем

Только соцсети: общий балл и баллы MAX, VK и Rutube. Сводный рейтинг включает ещё СМИ, сайт и повестку
Минобрнауки — их мы не собираем и не прогнозируем. Telegram с августа 2026 года в рейтинг не входит.

## Формула

Соцсети = 0.4 · MAX + 0.3 · VK + 0.3 · Rutube. Балл VK и MAX — среднее трёх шкал от 0 до 100, каждая
логарифмическая:

- число публикаций за месяц: от 20 до 100;
- средние просмотры публикации на одного студента: VK от 0.1 до 3, MAX от 0.03 до 0.5;
- вовлечённость — реакции, комментарии и репосты к просмотрам: VK от 0.5 % до 4 %, MAX от 0.5 % до 10 %.

Rutube: меньше 5 видео за месяц — 0. Выше порога балл растёт с числом видео; «глубину просмотров»,
которую учитывает источник, мы не собираем, поэтому берём среднее своей оценки и официального балла
прошлого месяца.

## Места

Место считается среди всех вузов официального рейтинга. Вузы, которых мы не отслеживаем, стоят с баллами
последнего опубликованного месяца. Соцсети — сумма баллов, а не мест: вуз, ровно сильный на трёх площадках,
обходит лидеров одной площадки. Так, СКФУ в сентябре 2026 года — 8-й по соцсетям при 27-м месте в MAX,
38-м в VK и 13-м в Rutube.

Баллы вузов плотные: ошибка в 4 балла сдвигает место примерно на 15. Поэтому рядом с местом в скобках —
диапазон мест при типичной ошибке прогноза.

## Когда данных не хватает

Если аккаунт вуза появился у нас посреди месяца и его история не доходит до начала месяца, площадка
помечается «нет полных данных» и берёт официальный балл прошлого месяца. Пока месяц идёт, число публикаций
досчитывается до полного месяца, а просмотры и вовлечённость берутся по постам старше трёх суток; до 7-го
числа оценка помечена «слишком рано».

## Точность

Проверка на опубликованных месяцах: в августе 2026 года ошибка общего балла — 7.2, медианная ошибка места —
17 из 233; в сентябре — 4.2 и 14.5. Август и сентябрь посчитаны задним числом и помечены «ретроспективный
расчёт»: просмотры к этому времени уже накопились, а пороги подбирались на сентябре.

## Ограничения

- Наш контингент студентов не совпадает с «приведённым контингентом без филиалов» источника.
- Минимумы и максимумы по всем вузам рейтинга нам неизвестны: пороги подобраны на наших вузах и могут
  меняться от месяца к месяцу.
- Просмотры растут и после конца месяца, а дата официального среза неизвестна.
- Источник иногда не учитывает канал вуза (MAX = 0 при активном канале); прогноз этого не предсказывает.
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx -y pnpm@11.19.0 exec playwright test tests/browser/rating.spec.ts tests/browser/parity.spec.ts tests/browser/methodology.spec.ts && npx -y pnpm@11.19.0 lint && npx -y pnpm@11.19.0 typecheck && node --import tsx --test tests/*.test.ts`
Expected: PASS (включая `tests/methodology.test.ts` и `tests/sitemap.test.ts` — новая статья попадает в карту сайта; если тест карты сайта перечисляет статьи явно, добавить `rating-forecast`).

- [ ] **Step 7: Screenshot check** — поднять локальный стенд (память `local-web-stand`: `next build` + `next start` с `MRANKED_API_REWRITE=1`, API на копии прода после ретроспективы из Task 11) или e2e-фикстуру; открыть `/rating`, `/rating?month=2026-09`, `/rating/own` на 1280 px и 375 px, светлая и тёмная тема; снять скриншоты для владельца.

- [ ] **Step 8: Commit**

```bash
git add frontend/lib/nav-links.ts frontend/lib/methodology.ts frontend/app/rating frontend/components/rating \
  frontend/content/methodology/rating-forecast.mdx frontend/tests/browser/rating.spec.ts frontend/tests/browser/parity.spec.ts
git commit -m "feat(frontend): «Рейтинг» tab — M-Rating forecast table, forecast-vs-actual scatter, our-rating scaffold"
```

### Task 10: Бэктест в репозитории

**Files:**
- Create: `research/m-rating-forecast/backtest.py`, `research/m-rating-forecast/README.md`

**Interfaces:**
- Consumes: `api.rating_forecast` (`forecast`, `evaluate`, `rank_in_pool`, `month_window`, `period_label`, `FORMULA_V1`), `api.sql.rating.PLATFORM_MONTH`, `api.tools.rating_forecast._institutions`/`_base` логика (повторить без async-пула: прямое psycopg-соединение).
- Produces: `python research/m-rating-forecast/backtest.py --dsn <DSN> --source <ratings-2026.json> --months 2026-08,2026-09` — таблица по месяцам: MAE по категориям, медиана/p80 ошибки места, ρ, топ-20.

- [ ] **Step 1: Write the script**

```python
"""Бэктест прогноза М-Рейтинга: прогноз опубликованных месяцев против факта.

Читает наши агрегаты из базы (копия прода, только чтение) и официальный
JSON источника (скачанный файл ratings-2026.json), считает прогноз тем же
модулем, что и ночное задание, и печатает ошибки. Нужен, чтобы видеть, когда
пороги формулы уехали и пора выпускать новую версию.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api import rating_forecast as rf  # noqa: E402
from api.institution_profile import _students_by_institution  # noqa: E402
from api.sql import rating as sql  # noqa: E402

KEYS = {"social": "social", "max": "ok", "vk": "vk", "rutube": "rt"}


def official(source: dict, month: date) -> rf.BaseMonth:
    item = source["months"][month.month - 1]
    return rf.BaseMonth(period=rf.period_label(month), names={row["code"]: row["name"] for row in item["items"]},
                        scores={row["code"]: {category: row["scores"].get(key) for category, key in KEYS.items()}
                                for row in item["items"] if row.get("code")})


def institutions(connection, month: date, as_of: datetime) -> list[rf.InstitutionMonth]:
    start, end = rf.month_window(month)
    rows = connection.execute(sql.PLATFORM_MONTH, {"window_start": start, "window_end": end,
                                                   "mature_before": as_of - timedelta(days=3)}).fetchall()
    students, grouped = _students_by_institution(), {}
    for row in rows:
        entry = grouped.setdefault(row["institution_id"], {"code": row["code"], "name": row["name"], "platforms": {}})
        if row["platform"] is not None:
            entry["platforms"][row["platform"]] = rf.PlatformMonth(
                posts=row["posts"], viewed_posts=row["viewed_posts"], views=int(row["views"]),
                interactions=int(row["interactions"]), covered=bool(row["covered"]))
    return [rf.InstitutionMonth(key, value["code"], value["name"], (students.get(key) or {}).get("value"),
                                value["platforms"]) for key, value in grouped.items()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--months", required=True)
    arguments = parser.parse_args()
    source = json.loads(arguments.source.read_text(encoding="utf-8"))
    as_of = datetime.now(timezone.utc)
    with psycopg.connect(arguments.dsn, row_factory=dict_row) as connection:
        connection.execute("SET jit = off")
        for text in arguments.months.split(","):
            month = date.fromisoformat(f"{text}-01")
            previous = (month - timedelta(days=1)).replace(day=1)
            base, fact = official(source, previous), official(source, month)
            rows = rf.forecast(institutions(connection, month, as_of), base, rf.FORMULA_V1["defaultErrors"])
            print(f"== {fact.period} (база {base.period}), вузов {len(rows)}")
            for category in rf.CATEGORIES:
                predicted = {row["explanation"]["code"]: row["explanation"]["categories"][category]["score"] for row in rows}
                ranks = {row["explanation"]["code"]: row["explanation"]["categories"][category]["rank"] for row in rows}
                actual_pool = {code: score[category] for code, score in fact.scores.items() if score.get(category) is not None}
                actual_ranks = rf.rank_in_pool(actual_pool, fact.names)
                result = rf.evaluate(predicted, actual_pool, ranks, actual_ranks)
                print(f"  {category:7s} MAE {result['mae']:5.1f} | место: медиана {result['rankMedian']:5.1f}, "
                      f"p80 {result['rankP80']:3d} | ρ {result['spearman']:.2f} | топ-20 {result['top20Hits']}/{result['top20Total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run on the local prod copy**

Сохранить источник в отдельный каталог скретчпада (`curl -s https://www.m-rating.ru/data/ratings-2026.json -o <scratch>/src/r.json`), создать временного `local_probe` (память `local-db-copy`), затем:
Run: `$PY -I research/m-rating-forecast/backtest.py --dsn "postgresql://local_probe:<pw>@127.0.0.1:55432/mranked_prod_20261013" --source <scratch>/src/r.json --months 2026-08,2026-09`
Expected: соцсети MAE около 7 (август) и 4–5 (сентябрь), медиана ошибки места 14–17 — как в спеке; заметно хуже — остановиться и разобрать расхождение до продолжения. После прогона удалить `local_probe`.

- [ ] **Step 3: README** — `research/m-rating-forecast/README.md`: назначение, команда запуска, таблица результатов прогона из Step 2 с датой, когда выпускать версию 2 (MAE соцсетей опубликованного месяца > 9 или ρ < 0.7).

- [ ] **Step 4: Commit**

```bash
git add research/m-rating-forecast
git commit -m "research(rating): reproducible forecast backtest against published months"
```

### Task 11: Замеры, ретроспектива на копии, документация

**Files:**
- Modify: `docs/OPERATIONS.md` (раздел таймеров), `docs/superpowers/plans/2026-10-16-rating-forecast.md` (раздел «Замеры» внизу — дописать цифры)

- [ ] **Step 1: Baseline «до»** — на `main` (основная копия, не трогая её файлы: собрать отдельный worktree `main` только для чтения или использовать текущий прод-релиз фронта) снять p50/p95 холодный/тёплый `/review` и `/compare` на локальном стенде с копией `mranked_prod_20261013` (20 запросов, первый — холодный после перезапуска API). Записать в план.

- [ ] **Step 2: Apply 0084 to the local copy** — сухой прогон (вырезать `BEGIN;`/`COMMIT;`, обернуть в `BEGIN … ROLLBACK`), затем настоящий: `docker exec -i mranked-local-db psql -U mranked_bootstrap -d mranked_prod_20261013 -v ON_ERROR_STOP=1 -c "SET ROLE migration_owner" -f - < db/migrations/0084_rating_forecast.sql`.

- [ ] **Step 3: SQL timing** — `EXPLAIN (ANALYZE, BUFFERS)` под `SET ROLE api_read; SET jit = off; SET random_page_cost = 1.1` для `PLATFORM_MONTH` (октябрь и сентябрь), `FORECAST_MONTHS`, `FORECAST_RUN`, `FORECAST_ROWS`. Ожидание: `PLATFORM_MONTH` < 1 с без Seq Scan по `ingest.publication`; читатели API < 20 мс. Записать планы-выжимки.

- [ ] **Step 4: Run the job and retrospective on the copy** — с переменными окружения локального API (память `local-web-stand`, пароли не печатать): `$PY -m api.tools.rating_forecast --retrospective 2026-08..2026-09` и `$PY -m api.tools.rating_forecast`; замерить `/usr/bin/time -l` (макс. RSS, время). Ожидание: < 10 с, RSS < 200 МБ. Проверить строки снимков и сравнить ретроспективу с бэктестом (Task 10).

- [ ] **Step 5: «После»** — тот же стенд на ветке: p50/p95 холодный/тёплый `/review`, `/compare`, `/rating`, `/rating?month=2026-09`, `/rating/own`. Критерий: `/review`, `/compare` не хуже «до» больше чем на шум (±10 %); `/rating` p95 тёплый ≤ `/compare`. Ухудшение — стоп, цифры владельцу.

- [ ] **Step 6: Docs** — в `docs/OPERATIONS.md` рядом с описанием `m-ranked-target-official-rating.timer`: таймер прогноза, время, что делает, как запустить ретроспективу разово (`systemd-run` под пользователем `m-ranked-api` с тем же `EnvironmentFile`/`LoadCredential`, `Nice=10`, `CPUQuota=50%`), как откатить (раздел «Откат» миграции 0084), что `/rating` пуст до первого снимка. Без адресов и портов.

- [ ] **Step 7: Commit**

```bash
git add docs/OPERATIONS.md docs/superpowers/plans/2026-10-16-rating-forecast.md
git commit -m "docs(rating): forecast timer operations and before/after measurements"
```

### Task 12: Полная проверка и PR (без выкатки)

- [ ] **Step 1: Full gates** — `$PY -m pytest tests anomaly_analysis -q` на одноразовом Postgres (память `local-pytest-postgres`; сравнить падения с `main`: 16 известных падений — не наши), `cd frontend && npx -y pnpm@11.19.0 check`.
- [ ] **Step 2: Review** — скил `superpowers:requesting-code-review` по всей ветке; исправить находки.
- [ ] **Step 3: Hygiene** — `git grep -nE '([0-9]{1,3}\.){3}[0-9]{1,3}' -- ':!*.lock'` по изменённым файлам не находит адресов; `git log --format=%B origin/main..HEAD | grep -i co-authored` пусто.
- [ ] **Step 4: PR** — `git push -u origin feat/rating-forecast`, `gh pr create` (скил `pr` для тела: что сделано, бэктест, замеры, план выкатки «после делай»: 0084 на S2, оверлей API+web, unit/timer, ретроспектива август–сентябрь). Выкатку не начинать.

## Замеры

16.10.2026, локальная копия прода `mranked_prod_20261013`, миграция 0084 применена как
`migration_owner`; API и web — production-сборки, роли входа — члены `api_read` /
`api_write_admin` с их настройками (`jit = off`, `random_page_cost = 1.1`). «До» —
`origin/main` 2ac5d9f3, «после» — эта ветка; два круга, один холодный запрос и 20 тёплых.

| Страница | До: холодный / p50 / p95, мс | После: холодный / p50 / p95, мс |
|---|---|---|
| `/review` | 191 / 30 / 34–37 | 190–196 / 29–30 / 35–37 |
| `/compare` | 528–541 / 22 / 24–26 | 541–545 / 21–23 / 25 |
| `/rating` | — | 36–43 / 14–15 / 16–17 |
| `/rating?month=2026-09` | — | 24–25 / 13–15 / 15–18 |
| `/rating/own` | — | 8–9 / 6 / 7 |

Память: API 94–98 МБ до и 95–97 МБ после; web 318–321 МБ до и 323–327 МБ после (в
пределах разброса). SQL `PLATFORM_MONTH`: сентябрь 70–99 мс, октябрь 24–30 мс;
единственный заметный Seq Scan — `publication_latest` (73 тыс. строк, 8 мс, hash join),
`ingest.publication` — по индексу. Задание: ретроспектива двух месяцев 0.41 с, ночной
прогон 0.35 с, RSS 52 МБ. Регрессий нет.

Находка замеров: на копии прода запись снимка падала с `InsufficientPrivilege` —
функции 0084 принадлежат `migration_owner`, а у него нет `EXECUTE` на
`analytics.latest_dataset_revision()`. Исправлено: ревизия читается из
`analytics.dataset_revision` напрямую (тест
`test_definer_functions_read_the_revision_without_foreign_functions`).
