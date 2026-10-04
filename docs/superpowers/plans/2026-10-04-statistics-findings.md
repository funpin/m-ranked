# /statistics → «Находки» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить таблицы `/statistics` лентой постов, сработавших выше нормы своего аккаунта («Находки»), с новым эндпоинтом `GET /api/v1/findings`.

**Architecture:** Один SQL-запрос считает норму аккаунта (медиана за 30 дней по `analytics.publication_checkpoint`, без уровней аномалии 2–3), значение поста на самой поздней точке не старше 24 ч и индекс к норме; Python-маршрут нормализует параметры, режет страницы и группирует по вузам. Next.js-страница `/statistics` — серверный компонент с GET-формой фильтров, таблицей на десктопе и карточками на телефоне. Старый `/api/v1/statistics` остаётся и помечается устаревшим.

**Tech Stack:** Python 3.13, FastAPI, psycopg 3, PostgreSQL 18; Next.js 16, React 19, shadcn/ui (стиль `base-mira`, Base UI), Tailwind, node:test, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-04-statistics-findings-design.md`

## Global Constraints

- Прод не трогается: никаких SSH, деплоя, запросов к серверам. Вся проверка — локально.
- Адреса, порты, ключи и пароли продакшена в репозиторий не пишутся (репозиторий публичный).
- В коммитах нет строки `Co-Authored-By` с Claude.
- Ветка `feat/statistics-findings`; коммиты — Conventional Commits.
- Пороги: окно нормы 30 дней; минимум 10 постов в норме; нижние ограничения нормы — 5 взаимодействий и 50 просмотров; лента «Все вузы» — индекс по взаимодействиям ≥ 1,5 и ≥ 10 взаимодействий.
- Возраст поста h — самая поздняя точка из 24 / 12 / 6 / 3 / 1 ч с непустыми просмотрами или взаимодействиями; значения после 24 ч не используются.
- Взаимодействия — по матрице `api/statistics_capabilities.py` (Telegram: реакции + комментарии; ВК: + репосты; MAX: только реакции; RuTube: реакции + комментарии).
- Действующий уровень аномалии: `coalesce(post_anomaly_context_recheck.effective_level, post_anomaly_state.level)`; уровни 2–3 исключаются из нормы всегда и из выдачи при `anomalies=exclude`.
- Периоды страницы: `1d`, `7d` (по умолчанию), `30d`; `3h` не поддерживается (400).
- Кеш-теги ответа: `publications`, `catalog`, `analysis`.
- UI: только компоненты shadcn из `frontend/components/ui`, без графиков, одна строка фильтров, индекс — единственный жирный акцент.
- Тексты интерфейса — на русском; подписи типов публикаций берутся из `typeName` в `frontend/lib/compare-dashboard.ts`.

## Review Focus

1. Неизвестный или скрытый вуз в `mode=institution` (`institution=999999`) — ответ 404 «вуз не найден», страница показывает пустое состояние с выбором вуза, а не ошибку API. Тест: Task 4, `test_findings_unknown_institution_is_404`; Task 9, проверка пустого состояния.
2. Пост, у которого точка 24 ч есть, но пустая (пропуск сбора), а 12 ч — с данными: берётся 12 ч, `preliminary=false`, пометка «по 12-му часу». Тест: Task 3, `test_gap_at_24h_falls_back_without_preliminary`.
3. Поиск с `%` и `_` ищет их буквально. Тест: Task 3, `test_search_treats_wildcards_literally`.
4. `localStorage` бросает исключение (приватный режим Safari) — выбор вуза работает, страница не падает. Тест: Task 7, `rememberInstitution survives throwing storage`.
5. Индекс ниже 1 и очень большой индекс форматируются читаемо (`×0,4`, `×70,5`), NULL — «—». Тест: Task 7, `formatIndex covers small, large and missing values`.

---

## Подготовка: локальная база (выполнено при планировании, повторяемо)

Локальная копия прода лежит в Docker-томе `mranked-current_postgres_data` (база `mranked_research_20260927`, 14 ГБ, схема до 0036). Для разработки используется её клон с доведённой схемой. Если контейнер не запущен:

```bash
docker run -d --rm --name findings-local-db -p 127.0.0.1:55433:5432 -v mranked-current_postgres_data:/var/lib/postgresql postgres:18.6
```

Пароль суперпользователя локального стенда — из `infra/local/compose.env.example` (`POSTGRES_SUPERUSER_PASSWORD`), пользователь `mranked_bootstrap`. Клон `mranked_findings_local` уже создан и содержит миграции 0037–0051, таблицу `analytics.post_anomaly_context_recheck` (строки 85–107 миграции 0044; сама 0044 на копии падает на уже существующей `publication_poll_receipt`) и `publication_checkpoint`, заполненную `db/tools/refresh-publication-checkpoints.sql` с `now()`, заменённым на `'2026-09-27 16:30:31+00'` (время последней ревизии копии). Пересоздание клона, если понадобится:

```bash
docker exec findings-local-db psql -U mranked_bootstrap -d postgres -c "DROP DATABASE IF EXISTS mranked_findings_local" -c "CREATE DATABASE mranked_findings_local TEMPLATE mranked_research_20260927"
```

затем повторить миграции и заполнение, как описано выше. Исходная база `mranked_research_20260927` не меняется.

Для интеграционных тестов SQL нужна отдельная пустая база со всеми миграциями (как `mranked_anomaly_it` в `.github/workflows/ci.yml`):

```bash
docker exec findings-local-db createdb -U mranked_bootstrap mranked_findings_it
docker exec findings-local-db mkdir -p /tmp/schema
for migration in db/migrations/*.sql; do docker cp -q "$migration" findings-local-db:/tmp/schema/; docker exec findings-local-db psql -U mranked_bootstrap -d mranked_findings_it --no-psqlrc -v ON_ERROR_STOP=1 -q -f "/tmp/schema/${migration##*/}"; done
```

Переменные окружения для тестов (локальная оболочка, не в репозиторий):

```bash
export MRANKED_FINDINGS_TEST_DSN="postgresql://mranked_bootstrap:local-demo-bootstrap@127.0.0.1:55433/mranked_findings_it"
```

---

### Task 1: Константы и эталон расчёта индекса

**Files:**
- Create: `api/findings.py`
- Test: `tests/test_findings.py`

**Interfaces:**
- Produces: константы `NORM_WINDOW_DAYS = 30`, `MIN_NORM_SAMPLE = 10`, `INTERACTION_NORM_FLOOR = 5`, `VIEW_NORM_FLOOR = 50`, `FINDING_MIN_INDEX = Decimal("1.5")`, `FINDING_MIN_INTERACTIONS = 10`, `AGE_HOURS = (24, 12, 6, 3, 1)`, `FINDINGS_PERIOD_DAYS = {"1d": 1, "7d": 7, "30d": 30}`, `FINDING_TYPES = ("text", "photo", "album", "video", "other")`, `MAIN_TYPES = ("text", "photo", "album", "video")`, `PAGE_CAP = 200`, `GROUP_POSTS = 3`; функции `type_bucket(publication_type: str) -> str`, `norm(values: Iterable[int | None]) -> tuple[Decimal | None, int]`, `index(value: int | None, norm_value: Decimal | None, sample: int, floor: int) -> Decimal | None`, `is_finding(interaction_index: Decimal | None, interactions: int | None) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_findings.py
from __future__ import annotations

from decimal import Decimal

from api.findings import (
    FINDING_MIN_INDEX, INTERACTION_NORM_FLOOR, MIN_NORM_SAMPLE, VIEW_NORM_FLOOR,
    index, is_finding, norm, type_bucket,
)


def test_norm_is_median_of_known_values_with_sample_size() -> None:
    assert norm([1, 3, None, 5]) == (Decimal("3"), 3)
    assert norm([2, 4]) == (Decimal("3"), 2)
    assert norm([None, None]) == (None, 0)


def test_index_needs_min_sample_and_floors_the_norm() -> None:
    ten = MIN_NORM_SAMPLE
    assert index(20, Decimal("10"), ten, INTERACTION_NORM_FLOOR) == Decimal("2")
    # Норма 2 ниже ограничения 5: делим на 5, а не на 2.
    assert index(10, Decimal("2"), ten, INTERACTION_NORM_FLOOR) == Decimal("2")
    assert index(100, Decimal("20"), ten, VIEW_NORM_FLOOR) == Decimal("2")
    assert index(20, Decimal("10"), ten - 1, INTERACTION_NORM_FLOOR) is None
    assert index(None, Decimal("10"), ten, INTERACTION_NORM_FLOOR) is None
    assert index(0, Decimal("10"), ten, INTERACTION_NORM_FLOOR) == Decimal("0")


def test_finding_threshold_needs_index_and_absolute_interactions() -> None:
    assert is_finding(FINDING_MIN_INDEX, 10)
    assert not is_finding(Decimal("1.49"), 100)
    assert not is_finding(Decimal("9"), 9)
    assert not is_finding(None, 100)
    assert not is_finding(Decimal("2"), None)


def test_publication_types_fold_into_five_buckets() -> None:
    assert [type_bucket(value) for value in ("text", "photo", "album", "video")] == [
        "text", "photo", "album", "video"]
    assert type_bucket("poll") == "other"
    assert type_bucket("share") == "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_findings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.findings'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/findings.py
"""«Находки»: пороги и эталон расчёта индекса к норме аккаунта.

SQL в api/sql/findings.py считает то же самое; эти функции закрепляют
семантику в модульных тестах и служат эталоном для проверки SQL на базе.
"""
from __future__ import annotations

from decimal import Decimal
from statistics import median
from typing import Iterable

NORM_WINDOW_DAYS = 30
MIN_NORM_SAMPLE = 10
INTERACTION_NORM_FLOOR = 5
VIEW_NORM_FLOOR = 50
FINDING_MIN_INDEX = Decimal("1.5")
FINDING_MIN_INTERACTIONS = 10
AGE_HOURS = (24, 12, 6, 3, 1)
FINDINGS_PERIOD_DAYS = {"1d": 1, "7d": 7, "30d": 30}
FINDING_TYPES = ("text", "photo", "album", "video", "other")
MAIN_TYPES = ("text", "photo", "album", "video")
PAGE_CAP = 200
GROUP_POSTS = 3


def type_bucket(publication_type: str) -> str:
    return publication_type if publication_type in MAIN_TYPES else "other"


def norm(values: Iterable[int | None]) -> tuple[Decimal | None, int]:
    known = [value for value in values if value is not None]
    if not known:
        return None, 0
    return Decimal(str(median(known))), len(known)


def index(value: int | None, norm_value: Decimal | None, sample: int,
          floor: int) -> Decimal | None:
    if value is None or norm_value is None or sample < MIN_NORM_SAMPLE:
        return None
    return Decimal(value) / max(norm_value, Decimal(floor))


def is_finding(interaction_index: Decimal | None, interactions: int | None) -> bool:
    return (interaction_index is not None and interactions is not None
            and interaction_index >= FINDING_MIN_INDEX
            and interactions >= FINDING_MIN_INTERACTIONS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_findings.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add api/findings.py tests/test_findings.py
git commit -m "feat(findings): thresholds and reference index calculation"
```

---

### Task 2: Нормализация параметров запроса

**Files:**
- Modify: `api/params.py` (добавить после `statistics_query`)
- Test: `tests/test_findings.py`

**Interfaces:**
- Consumes: `FINDINGS_PERIOD_DAYS`, `FINDING_TYPES` из Task 1; `PLATFORMS`, `BadRequest` из `api/params.py`.
- Produces: `FINDINGS_SORTS: frozenset[str]`; `@dataclass(frozen=True, slots=True) class FindingsQuery` с полями `mode: str`, `institution: int | None`, `platform: str`, `period: str`, `types: tuple[str, ...]`, `sort: str`, `direction: str`, `group: str`, `search: str`, `anomalies: str` и свойством `dimensions: str`; функция `findings_query(mode, institution, platform, period, types, sort, direction, group, q, anomalies) -> FindingsQuery`. Все аргументы — `str | None`, кроме `types: list[str] | None`.

- [ ] **Step 1: Write the failing test** (добавить в `tests/test_findings.py`)

```python
import pytest

from api.errors import BadRequest
from api.params import encode_scoped_cursor, findings_query, scoped_cursor


def _query(**overrides):
    values = {"mode": None, "institution": None, "platform": None, "period": None,
              "types": None, "sort": None, "direction": None, "group": None,
              "q": None, "anomalies": None}
    values.update(overrides)
    return findings_query(**values)


def test_findings_query_defaults() -> None:
    query = _query()
    assert (query.mode, query.institution, query.platform, query.period) == ("all", None, "all", "7d")
    assert (query.types, query.sort, query.direction, query.group) == ((), "interaction_index", "desc", "none")
    assert (query.search, query.anomalies) == ("", "exclude")


def test_findings_query_normalizes_aliases_and_type_order() -> None:
    query = _query(platform="tg", types=["video", "photo", "video"], q="  мгу ")
    assert query.platform == "telegram"
    assert query.types == ("photo", "video")
    assert query.search == "мгу"


@pytest.mark.parametrize("overrides, message", [
    ({"period": "3h"}, "период"),
    ({"platform": "ok"}, "платформа"),
    ({"sort": "erv"}, "сортировка"),
    ({"direction": "up"}, "направление"),
    ({"types": ["gif"]}, "тип"),
    ({"mode": "institution"}, "вуз"),
    ({"mode": "institution", "institution": "0"}, "вуз"),
    ({"mode": "institution", "institution": "12", "group": "institution"}, "группировка"),
    ({"group": "platform"}, "группировка"),
    ({"anomalies": "hide"}, "аномали"),
    ({"q": "a" * 201}, "200"),
])
def test_findings_query_rejects_unknown_values(overrides, message) -> None:
    with pytest.raises(BadRequest) as error:
        _query(**overrides)
    assert message in (error.value.detail or "")


def test_findings_cursor_is_bound_to_every_dimension() -> None:
    query = _query(mode="institution", institution="12", types=["photo"])
    cursor = encode_scoped_cursor("00000000-0000-4000-8000-000000000001", 5, "findings:" + query.dimensions)
    assert scoped_cursor(cursor, 5, "findings:" + query.dimensions)
    changed = _query(mode="institution", institution="12", types=["video"])
    with pytest.raises(BadRequest):
        scoped_cursor(cursor, 5, "findings:" + changed.dimensions)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_findings.py -q`
Expected: FAIL with `ImportError: cannot import name 'findings_query'`

- [ ] **Step 3: Write minimal implementation** (в `api/params.py`; импорт `from .findings import FINDING_TYPES, FINDINGS_PERIOD_DAYS` добавить к импортам в начале файла)

```python
FINDINGS_SORTS = frozenset({
    "interaction_index", "view_index", "interactions24", "views24", "erv24", "published_at",
})


@dataclass(frozen=True, slots=True)
class FindingsQuery:
    mode: str
    institution: int | None
    platform: str
    period: str
    types: tuple[str, ...]
    sort: str
    direction: str
    group: str
    search: str
    anomalies: str

    @property
    def dimensions(self) -> str:
        return ":".join((self.mode, str(self.institution or ""), self.platform, self.period,
                         ",".join(self.types), self.sort, self.direction, self.group,
                         self.search, self.anomalies))


def findings_query(mode: str | None, institution: str | None, platform: str | None,
                   period: str | None, types: list[str] | None, sort: str | None,
                   direction: str | None, group: str | None, q: str | None,
                   anomalies: str | None) -> FindingsQuery:
    resolved_mode = mode or "all"
    if resolved_mode not in ("all", "institution"):
        raise BadRequest("режим должен быть all или institution")
    resolved_platform = (platform or "all").strip().lower()
    if resolved_platform == "tg":
        resolved_platform = "telegram"
    if resolved_platform not in PLATFORMS:
        raise BadRequest(f"платформа должна быть одной из {', '.join(PLATFORMS)}")
    resolved_period = period or "7d"
    if resolved_period not in FINDINGS_PERIOD_DAYS:
        raise BadRequest(f"период должен быть одним из {', '.join(FINDINGS_PERIOD_DAYS)}")
    requested_types = set(types or ())
    if requested_types - set(FINDING_TYPES):
        raise BadRequest(f"тип публикации должен быть одним из {', '.join(FINDING_TYPES)}")
    resolved_sort = sort or "interaction_index"
    if resolved_sort not in FINDINGS_SORTS:
        raise BadRequest(f"сортировка должна быть одной из {', '.join(sorted(FINDINGS_SORTS))}")
    resolved_direction = direction or "desc"
    if resolved_direction not in ("asc", "desc"):
        raise BadRequest("направление должно быть asc или desc")
    resolved_group = group or "none"
    if resolved_group not in ("none", "institution"):
        raise BadRequest("группировка должна быть none или institution")
    resolved_anomalies = anomalies or "exclude"
    if resolved_anomalies not in ("exclude", "include"):
        raise BadRequest("параметр anomalies должен быть exclude или include")
    resolved_institution: int | None = None
    if resolved_mode == "institution":
        if not institution or not institution.isascii() or not institution.isdigit() or int(institution) <= 0:
            raise BadRequest("для режима institution нужен вуз: положительный legacy id")
        resolved_institution = int(institution)
        if resolved_group != "none":
            raise BadRequest("группировка по вузам доступна только в режиме all")
    text = (q or "").strip()
    if len(text) > 200:
        raise BadRequest("поисковый фрагмент длиннее 200 символов")
    return FindingsQuery(
        resolved_mode, resolved_institution, resolved_platform, resolved_period,
        tuple(value for value in FINDING_TYPES if value in requested_types),
        resolved_sort, resolved_direction, resolved_group, text, resolved_anomalies,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_findings.py tests/test_statistics.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/params.py tests/test_findings.py
git commit -m "feat(findings): strict query normalization"
```

---

### Task 3: SQL «Находок» и проверка на одноразовой базе

**Files:**
- Create: `api/sql/findings.py`
- Test: `tests/test_findings_postgres.py`

**Interfaces:**
- Consumes: `CAPABILITIES`, `SEARCH_PREDICATE` из `api/sql/statistics.py`; константы Task 1.
- Produces: строки `FINDINGS` и `INSTITUTIONS`. Параметры `FINDINGS`: `as_of`, `period_days`, `norm_days`, `platform`, `institution_legacy_id` (int | None), `types` (list[str]), `q`, `search_pattern`, `username_pattern`, `min_sample`, `interaction_floor`, `view_floor`, `mode`, `min_index`, `min_interactions`, `sort`, `direction`, `exclude_anomalies` (bool), `group`, `cap`. Строки результата: всегда хотя бы одна строка; `hidden_anomalous` в каждой; если выдача пуста — единственная строка с `publication_id IS NULL`. Колонки строки поста: `publication_id, published_at, publication_type, account_id, platform, institution_id, institution_legacy_id, institution_short_name, institution_canonical_name, current_username, current_title, level, age_hours, views, reactions, comments, shares, interactions, interaction_norm, view_norm, norm_sample, interaction_index, view_index, erv, preliminary, rank, institution_rank, institution_finding_count, total, external_id, public_url`. `INSTITUTIONS` (без параметров): `legacy_id, short_name, canonical_name`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_findings_postgres.py
"""SQL «Находок» на одноразовой базе со всеми миграциями; без неё пропускается.

База создаётся по шагам из плана (mranked_findings_it). Каждый тест строит
свой вуз и аккаунт, поэтому тесты независимы и не чистят за собой.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from uuid import uuid4

import pytest

from api.findings import (
    FINDING_MIN_INDEX, FINDING_MIN_INTERACTIONS, INTERACTION_NORM_FLOOR, MIN_NORM_SAMPLE,
    NORM_WINDOW_DAYS, PAGE_CAP, VIEW_NORM_FLOOR, index, norm,
)
from api.routes.statistics import _like_pattern
from api.sql import findings as sql

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

AS_OF = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def dsn() -> str:
    value = os.environ.get("MRANKED_FINDINGS_TEST_DSN", "")
    if not value:
        pytest.skip("MRANKED_FINDINGS_TEST_DSN is required")
    if "findings_it" not in value or not any(host in value for host in ("127.0.0.1", "localhost")):
        raise AssertionError("findings integration test requires the disposable local findings_it database")
    return value


def _connect(dsn: str):
    return psycopg.connect(dsn, autocommit=True, row_factory=dict_row)


class World:
    """Вуз с одним аккаунтом и постами, у которых заданы точки по часам."""

    def __init__(self, dsn: str, platform: str = "vk", name: str | None = None) -> None:
        self.dsn, self.platform = dsn, platform
        self.institution, self.account = uuid4(), uuid4()
        with _connect(dsn) as connection:
            self.legacy_id = connection.execute(
                "SELECT coalesce(max(legacy_id),0)+1 AS id FROM catalog.legacy_entity_alias "
                "WHERE entity_type='institutions'").fetchone()["id"]
            connection.execute("INSERT INTO catalog.institution(id,canonical_name,short_name) VALUES (%s,%s,%s)",
                               (self.institution, name or f"Вуз {self.legacy_id}", f"В{self.legacy_id}"))
            connection.execute("INSERT INTO catalog.legacy_entity_alias(entity_type,legacy_id,target_uuid) "
                               "VALUES ('institutions',%s,%s)", (self.legacy_id, self.institution))
            connection.execute("""
                INSERT INTO catalog.platform_account(id,institution_id,platform,canonical_external_id,access_mode)
                VALUES (%s,%s,%s,%s,'public_web')""",
                (self.account, self.institution, platform, f"findings-{self.account}"))

    def post(self, published_at: datetime, points: dict[int, tuple[int | None, int | None]],
             *, level: int | None = None, recheck_to: int | None = None,
             publication_type: str = "photo", external_id: str | None = None):
        """points: час -> (просмотры, реакции); комментарии и репосты пустые."""
        publication = uuid4()
        with _connect(self.dsn) as connection:
            connection.execute("""
                INSERT INTO ingest.publication(id,primary_account_id,published_at,discovered_at,publication_type,history_completeness)
                VALUES (%s,%s,%s,%s,%s,'complete')""",
                (publication, self.account, published_at, published_at, publication_type))
            if external_id:
                connection.execute("""
                    INSERT INTO ingest.publication_identity(publication_id,role,external_id,public_url)
                    VALUES (%s,'primary',%s,%s)""", (publication, external_id, f"https://vk.com/wall{external_id}"))
            for hour, (views, reactions) in points.items():
                connection.execute("""
                    INSERT INTO analytics.publication_checkpoint(publication_id,hour_offset,observed_at,views_count,reactions_count)
                    VALUES (%s,%s,%s,%s,%s)""",
                    (publication, hour, published_at + timedelta(hours=hour), views, reactions))
            if level is not None:
                analyzed = published_at + timedelta(hours=30)
                connection.execute("""
                    INSERT INTO analytics.post_anomaly_state(publication_id,published_at,level,analyzed_at,next_due_at)
                    VALUES (%s,%s,%s,%s,%s)""", (publication, published_at, level, analyzed, analyzed))
                if recheck_to is not None:
                    connection.execute("""
                        INSERT INTO analytics.post_anomaly_context_recheck(
                          publication_id,source_analyzed_at,source_level,effective_level,method_version,reason,evidence)
                        VALUES (%s,%s,%s,%s,'test','fixture','{}')""", (publication, analyzed, level, recheck_to))
        return publication

    def baseline(self, count: int = MIN_NORM_SAMPLE, views: int = 1000, reactions: int = 20,
                 days_ago: int = 20) -> None:
        for number in range(count):
            self.post(AS_OF - timedelta(days=days_ago, minutes=number), {24: (views, reactions)})


def run(dsn: str, world: World | None = None, **overrides) -> list[dict]:
    params = {
        "as_of": AS_OF, "period_days": 7, "norm_days": NORM_WINDOW_DAYS,
        "platform": "all", "institution_legacy_id": world.legacy_id if world else None,
        "types": [], "q": "", "search_pattern": "%", "username_pattern": "%",
        "min_sample": MIN_NORM_SAMPLE, "interaction_floor": INTERACTION_NORM_FLOOR,
        "view_floor": VIEW_NORM_FLOOR, "mode": "institution" if world else "all",
        "min_index": FINDING_MIN_INDEX, "min_interactions": FINDING_MIN_INTERACTIONS,
        "sort": "interaction_index", "direction": "desc", "exclude_anomalies": True,
        "group": "none", "cap": PAGE_CAP,
    }
    params.update(overrides)
    with _connect(dsn) as connection:
        return connection.execute(sql.FINDINGS, params).fetchall()


def posts(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row["publication_id"] is not None]


def test_index_matches_reference_on_24h_point(dsn) -> None:
    world = World(dsn)
    world.baseline(views=1000, reactions=20)
    target = world.post(AS_OF - timedelta(days=2), {24: (3000, 90)}, external_id="-1_7")
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    interaction_norm, sample = norm([20] * MIN_NORM_SAMPLE + [90])
    assert row["age_hours"] == 24 and row["preliminary"] is False
    assert row["interactions"] == 90 and row["views"] == 3000
    assert Decimal(str(row["interaction_norm"])) == interaction_norm
    assert row["interaction_index"] == index(90, interaction_norm, sample, INTERACTION_NORM_FLOOR)
    assert row["erv"] == Decimal(90) * 100 / Decimal(3000)
    assert row["external_id"] == "-1_7"


def test_young_post_uses_latest_point_and_is_preliminary(dsn) -> None:
    world = World(dsn)
    for number in range(MIN_NORM_SAMPLE):
        world.post(AS_OF - timedelta(days=10, minutes=number), {6: (400, 10), 24: (900, 20)})
    young = world.post(AS_OF - timedelta(hours=7), {1: (50, 1), 6: (800, 30)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == young)
    assert row["age_hours"] == 6 and row["preliminary"] is True
    assert row["interaction_index"] == Decimal(30) / Decimal(10)


def test_gap_at_24h_falls_back_without_preliminary(dsn) -> None:
    world = World(dsn)
    for number in range(MIN_NORM_SAMPLE):
        world.post(AS_OF - timedelta(days=10, minutes=number), {12: (500, 10), 24: (900, 20)})
    gapped = world.post(AS_OF - timedelta(days=3), {12: (700, 25), 24: (None, None)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == gapped)
    assert row["age_hours"] == 12 and row["preliminary"] is False


def test_norm_excludes_level_two_and_three_but_recheck_restores(dsn) -> None:
    world = World(dsn)
    world.baseline(reactions=20)
    for number in range(5):
        world.post(AS_OF - timedelta(days=15, minutes=number), {24: (1000, 900)}, level=3)
    restored = world.post(AS_OF - timedelta(days=1), {24: (1000, 60)}, level=2, recheck_to=1)
    hidden = world.post(AS_OF - timedelta(days=1, hours=1), {24: (1000, 80)}, level=2)
    rows = run(dsn, world, mode="all", institution_legacy_id=None)
    mine = [row for row in posts(rows) if row["institution_legacy_id"] == world.legacy_id]
    assert {row["publication_id"] for row in mine} == {restored}
    assert Decimal(str(mine[0]["interaction_norm"])) == Decimal(20)
    assert rows[0]["hidden_anomalous"] >= 1
    included = posts(run(dsn, world, exclude_anomalies=False))
    assert hidden in {row["publication_id"] for row in included}


def test_small_history_has_no_index_and_sorts_last(dsn) -> None:
    world = World(dsn)
    world.baseline(count=MIN_NORM_SAMPLE - 2)
    world.post(AS_OF - timedelta(days=1), {24: (1000, 500)})
    rows = posts(run(dsn, world))
    assert rows and all(row["interaction_index"] is None for row in rows[-1:])
    assert not posts(run(dsn, world, mode="all", institution_legacy_id=None, platform="vk",
                         q=f"В{world.legacy_id}", search_pattern=f"%в{world.legacy_id}%",
                         username_pattern=f"%в{world.legacy_id}%"))


def test_floors_prevent_noise_on_tiny_norms(dsn) -> None:
    world = World(dsn)
    world.baseline(views=10, reactions=1)
    target = world.post(AS_OF - timedelta(days=1), {24: (100, 10)})
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    assert row["interaction_index"] == Decimal(10) / Decimal(INTERACTION_NORM_FLOOR)
    assert row["view_index"] == Decimal(100) / Decimal(VIEW_NORM_FLOOR)


def test_max_counts_only_reactions(dsn) -> None:
    world = World(dsn, platform="max")
    world.baseline(reactions=10)
    target = world.post(AS_OF - timedelta(days=1), {24: (1000, 40)})
    with _connect(dsn) as connection:
        connection.execute("UPDATE analytics.publication_checkpoint SET comments_count=500, shares_count=500 "
                           "WHERE publication_id=%s", (target,))
    row = next(row for row in posts(run(dsn, world)) if row["publication_id"] == target)
    assert row["interactions"] == 40


def test_type_filter_folds_rare_types_into_other(dsn) -> None:
    world = World(dsn)
    world.baseline()
    poll = world.post(AS_OF - timedelta(days=1), {24: (1000, 30)}, publication_type="poll")
    video = world.post(AS_OF - timedelta(days=1), {24: (1000, 30)}, publication_type="video")
    assert {row["publication_id"] for row in posts(run(dsn, world, types=["other"]))} == {poll}
    assert {row["publication_id"] for row in posts(run(dsn, world, types=["video"]))} == {video}


def test_search_treats_wildcards_literally(dsn) -> None:
    world = World(dsn, name="Институт 50%_проверки")
    world.baseline()
    world.post(AS_OF - timedelta(days=1), {24: (1000, 60)})
    pattern = _like_pattern("50%_")
    found = posts(run(dsn, world, q="50%_", search_pattern=pattern, username_pattern=pattern))
    assert found
    other = _like_pattern("50xx")
    assert not posts(run(dsn, world, q="50xx", search_pattern=other, username_pattern=other))


def test_group_mode_returns_top_three_per_institution(dsn) -> None:
    world = World(dsn)
    world.baseline()
    for reactions in (40, 50, 60, 70):
        world.post(AS_OF - timedelta(days=1, minutes=reactions), {24: (1000, reactions)})
    rows = [row for row in posts(run(dsn, None, group="institution"))
            if row["institution_legacy_id"] == world.legacy_id]
    assert [row["interactions"] for row in rows] == [70, 60, 50]
    assert {row["institution_finding_count"] for row in rows} == {4}


def test_empty_result_still_returns_summary_row(dsn) -> None:
    world = World(dsn)
    rows = run(dsn, world, period_days=1)
    assert len(rows) == 1 and rows[0]["publication_id"] is None
    assert rows[0]["hidden_anomalous"] == 0


def test_institutions_list_has_legacy_ids(dsn) -> None:
    world = World(dsn)
    with _connect(dsn) as connection:
        rows = connection.execute(sql.INSTITUTIONS).fetchall()
    assert any(row["legacy_id"] == world.legacy_id for row in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `MRANKED_FINDINGS_TEST_DSN=... .venv/bin/python -m pytest tests/test_findings_postgres.py -q`
Expected: FAIL with `ImportError: cannot import name 'findings' from 'api.sql'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/sql/findings.py
"""«Находки»: посты выше нормы своего аккаунта.

Норма — медиана значения на одном и том же возрасте поста (1, 3, 6, 12 или
24 часа) по постам аккаунта за 30 дней до as_of, без постов с действующим
уровнем аномалии 2–3. Пост сравнивается на самой поздней своей точке не
старше суток: у молодого поста это 6 или 12 часов, и норма берётся на том же
часу. Значения на фиксированных часах лежат готовыми в
analytics.publication_checkpoint, поэтому снимки запрос не читает.
"""
from __future__ import annotations

from .statistics import CAPABILITIES, SEARCH_PREDICATE

_INTERACTIONS = """
CASE WHEN (NOT capability.reactions_supported OR checkpoint.reactions_count IS NULL)
       AND (NOT capability.comments_supported OR checkpoint.comments_count IS NULL)
       AND (NOT capability.shares_supported OR checkpoint.shares_count IS NULL)
  THEN NULL
  ELSE (CASE WHEN capability.reactions_supported THEN coalesce(checkpoint.reactions_count,0) ELSE 0 END)
     + (CASE WHEN capability.comments_supported THEN coalesce(checkpoint.comments_count,0) ELSE 0 END)
     + (CASE WHEN capability.shares_supported THEN coalesce(checkpoint.shares_count,0) ELSE 0 END)
END::bigint
"""

# Действующий уровень — как на панели сравнения: ручная перепроверка
# понижает сохранённый уровень, пока анализ поста не обновился.
_LEVEL = """
LEFT JOIN analytics.post_anomaly_state state ON state.publication_id=publication.id
 AND state.analyzed_at IS NOT NULL
LEFT JOIN analytics.post_anomaly_context_recheck recheck ON recheck.publication_id=publication.id
 AND recheck.source_analyzed_at=state.analyzed_at AND recheck.source_level=state.level
 AND state.review_status='unreviewed'
"""

FINDINGS = f"""
WITH params AS (
    SELECT %(as_of)s::timestamptz AS as_of,
           %(as_of)s::timestamptz-make_interval(days=>%(period_days)s) AS cutoff,
           %(as_of)s::timestamptz-make_interval(days=>%(norm_days)s) AS norm_cutoff
), {CAPABILITIES}, accounts AS MATERIALIZED (
    SELECT account.id AS account_id,account.platform::text AS platform,account.institution_id,
           account.current_username,account.current_title,
           institution.canonical_name AS institution_canonical_name,
           institution.short_name AS institution_short_name,
           institution_alias.legacy_id AS institution_legacy_id
      FROM catalog.visible_platform_account account
      JOIN catalog.visible_institution institution ON institution.id=account.institution_id
      LEFT JOIN LATERAL (
          SELECT alias.legacy_id FROM catalog.legacy_entity_alias alias
           WHERE alias.target_uuid=institution.id AND alias.entity_type='institutions'
           ORDER BY alias.legacy_id LIMIT 1) institution_alias ON true
     WHERE account.enabled
       AND (%(platform)s='all' OR account.platform::text=%(platform)s)
       AND (%(institution_legacy_id)s::bigint IS NULL
            OR institution_alias.legacy_id=%(institution_legacy_id)s::bigint)
), measured AS MATERIALIZED (
    SELECT publication.id AS publication_id,accounts.account_id,checkpoint.hour_offset,
           publication.published_at>params.cutoff AS in_period,
           checkpoint.views_count AS views,checkpoint.reactions_count AS reactions,
           checkpoint.comments_count AS comments,checkpoint.shares_count AS shares,
           {_INTERACTIONS} AS interactions,
           coalesce(recheck.effective_level,state.level) AS level
      FROM params
      JOIN ingest.visible_publication publication
        ON publication.published_at>params.norm_cutoff AND publication.published_at<=params.as_of
      JOIN accounts ON accounts.account_id=publication.primary_account_id
      JOIN capabilities capability ON capability.platform=accounts.platform
      JOIN analytics.publication_checkpoint checkpoint ON checkpoint.publication_id=publication.id
       AND checkpoint.hour_offset<=24
      {_LEVEL}
), norms AS (
    SELECT account_id,hour_offset,
           count(interactions)::integer AS interaction_sample,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY interactions) AS interaction_norm,
           count(views)::integer AS view_sample,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY views) AS view_norm
      FROM measured
     WHERE coalesce(level,0)<2
     GROUP BY account_id,hour_offset
), latest_point AS (
    -- Самая поздняя непустая точка не старше суток. Пустая строка на 24-м
    -- часу (сбор пропустил этот час) не скрывает значение на 12-м.
    SELECT DISTINCT ON (publication_id) publication_id,hour_offset,views,reactions,comments,shares,interactions
      FROM measured
     WHERE in_period AND (views IS NOT NULL OR interactions IS NOT NULL)
     ORDER BY publication_id,hour_offset DESC
), candidates AS (
    SELECT publication.id AS publication_id,publication.published_at,
           publication.publication_type::text AS publication_type,accounts.*,
           coalesce(recheck.effective_level,state.level) AS level
      FROM params
      JOIN ingest.visible_publication publication
        ON publication.published_at>params.cutoff AND publication.published_at<=params.as_of
      JOIN accounts ON accounts.account_id=publication.primary_account_id
      JOIN catalog.visible_platform_account account ON account.id=accounts.account_id
      JOIN catalog.visible_institution institution ON institution.id=accounts.institution_id
      {_LEVEL}
     WHERE (cardinality(%(types)s::text[])=0
            OR CASE WHEN publication.publication_type::text IN ('text','photo','album','video')
                    THEN publication.publication_type::text ELSE 'other' END = ANY(%(types)s::text[]))
       AND {SEARCH_PREDICATE}
), scored AS (
    SELECT candidates.*,point.hour_offset AS age_hours,point.views,point.reactions,point.comments,
           point.shares,point.interactions,norms.interaction_norm,norms.view_norm,
           least(coalesce(norms.interaction_sample,0),coalesce(norms.view_sample,0)) AS norm_sample,
           CASE WHEN norms.interaction_sample>=%(min_sample)s AND point.interactions IS NOT NULL
                THEN point.interactions::numeric
                     /greatest(norms.interaction_norm,%(interaction_floor)s)::numeric END AS interaction_index,
           CASE WHEN norms.view_sample>=%(min_sample)s AND point.views IS NOT NULL
                THEN point.views::numeric/greatest(norms.view_norm,%(view_floor)s)::numeric END AS view_index,
           CASE WHEN point.interactions IS NOT NULL AND point.views>0
                THEN point.interactions::numeric*100/point.views END AS erv,
           coalesce(point.hour_offset<24
                    AND candidates.published_at+interval '24 hours'>(SELECT as_of FROM params),
                    false) AS preliminary
      FROM candidates
      LEFT JOIN latest_point point ON point.publication_id=candidates.publication_id
      LEFT JOIN norms ON norms.account_id=candidates.account_id AND norms.hour_offset=point.hour_offset
), eligible AS (
    SELECT scored.*,
           (%(mode)s='institution'
            OR (interaction_index>=%(min_index)s AND interactions>=%(min_interactions)s)) AS above_norm
      FROM scored
), visible AS (
    SELECT eligible.*,
           CASE %(sort)s WHEN 'view_index' THEN view_index
             WHEN 'interactions24' THEN interactions::numeric
             WHEN 'views24' THEN views::numeric
             WHEN 'erv24' THEN erv
             WHEN 'published_at' THEN extract(epoch FROM published_at)::numeric
             ELSE interaction_index END AS sort_value
      FROM eligible
     WHERE above_norm AND (NOT %(exclude_anomalies)s OR coalesce(level,0)<2)
), ranked AS (
    SELECT visible.*,
           row_number() OVER(ORDER BY
             CASE WHEN %(direction)s='desc' THEN sort_value END DESC NULLS LAST,
             CASE WHEN %(direction)s='asc' THEN sort_value END ASC NULLS LAST,
             published_at DESC,publication_id DESC) AS rank,
           row_number() OVER(PARTITION BY institution_id ORDER BY
             CASE WHEN %(direction)s='desc' THEN sort_value END DESC NULLS LAST,
             CASE WHEN %(direction)s='asc' THEN sort_value END ASC NULLS LAST,
             published_at DESC,publication_id DESC) AS institution_rank,
           count(*) OVER(PARTITION BY institution_id)::integer AS institution_finding_count,
           count(*) OVER()::integer AS total
      FROM visible
), page AS (
    SELECT * FROM ranked
     WHERE (%(group)s='none' AND rank<=%(cap)s) OR (%(group)s='institution' AND institution_rank<=3)
), summary AS (
    -- Посты, которые попали бы в выдачу, если бы не аномалия 2–3.
    SELECT count(*) FILTER (WHERE above_norm AND level>=2)::integer AS hidden_anomalous FROM eligible
)
SELECT page.*,summary.hidden_anomalous,identity.external_id,identity.public_url
  FROM summary
  LEFT JOIN page ON true
  LEFT JOIN LATERAL (
      SELECT value.external_id,value.public_url FROM ingest.publication_identity value
       WHERE value.publication_id=page.publication_id AND value.role='primary'
       ORDER BY value.id LIMIT 1) identity ON true
 ORDER BY page.rank
"""

INSTITUTIONS = """
SELECT DISTINCT ON (institution.id) alias.legacy_id,institution.short_name,institution.canonical_name
  FROM catalog.visible_institution institution
  JOIN catalog.visible_platform_account account ON account.institution_id=institution.id AND account.enabled
  JOIN catalog.legacy_entity_alias alias ON alias.target_uuid=institution.id AND alias.entity_type='institutions'
 ORDER BY institution.id,alias.legacy_id
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `MRANKED_FINDINGS_TEST_DSN=... .venv/bin/python -m pytest tests/test_findings_postgres.py -q`
Expected: PASS (12 passed). Если `catalog.platform_account` отвергает `access_mode='public_web'` для `max` (ограничение в `db/migrations/0003_tables_catalog.sql`), взять допустимое значение для MAX оттуда. Если `ingest.publication_identity` требует других обязательных колонок, взять их список из `db/migrations/0004_tables_ingest.sql` (`CREATE TABLE ingest.publication_identity`) и дописать в `World.post`, не меняя проверок.

- [ ] **Step 5: Commit**

```bash
git add api/sql/findings.py tests/test_findings_postgres.py
git commit -m "feat(findings): account-norm SQL with disposable database tests"
```

---

### Task 4: DTO, маршрут и контракт OpenAPI

**Files:**
- Modify: `api/dto.py` (после `statistics_publication`)
- Create: `api/routes/findings.py`
- Modify: `api/app.py:23,115` (импорт и регистрация `findings`)
- Modify: `contracts/openapi/m-ranked-v1.yaml` (новый путь после `/api/v1/statistics`, схемы после `Statistics`, `deprecated: true` у `getStatistics`)
- Modify: `tests/test_api_contract.py` (группа `FINDINGS_GROUP`)
- Test: `tests/test_findings.py`

**Interfaces:**
- Consumes: `findings_query`, `FindingsQuery` (Task 2); `sql.FINDINGS`, `sql.INSTITUTIONS` (Task 3); `serve`, `normalize.limit`, `normalize.scoped_cursor`, `normalize.encode_scoped_cursor`, `normalize.cursor_revision`, `_like_pattern`, `_capabilities`, `_page` из `api/routes/statistics.py`.
- Produces: `dto.finding(row) -> dict`, `dto.finding_institution(row) -> dict`, `findings_body(query, rows, institutions, page_size, after_id, revision, committed_at, dimensions) -> dict` в `api/routes/findings.py`. JSON-ответ: `mode, institution, platform, period, types, sort, direction, group, q, anomalies, items, groups, total, hiddenAnomalous, institutions, limit, offset, hasMore, nextCursor, datasetRevision, asOf`. Пост (`Finding`): `publicationId, institutionId, institutionLegacyId, institutionShortName, institutionCanonicalName, accountId, platform, publicationType, externalId, publicUrl, publishedAt, ageHours, preliminary, interactionIndex, viewIndex, interactionNorm, viewNorm, normSampleSize, interactions, reactions, comments, shares, views, erv, anomalyLevel, capabilities`. Группа (`FindingGroup`): `institutionLegacyId, institutionShortName, institutionCanonicalName, findingCount, items`.

- [ ] **Step 1: Write the failing test** (добавить в `tests/test_findings.py`)

```python
from datetime import datetime, timezone

from api import dto
from api.errors import NotFound
from api.routes.findings import findings_body


def _row(number: int, institution: int = 1, **overrides) -> dict:
    row = {
        "publication_id": f"00000000-0000-4000-8000-{number:012d}",
        "institution_id": f"00000000-0000-4000-9000-{institution:012d}",
        "institution_legacy_id": institution, "institution_short_name": f"В{institution}",
        "institution_canonical_name": f"Вуз {institution}",
        "account_id": "00000000-0000-4000-a000-000000000001", "platform": "vk",
        "publication_type": "photo", "external_id": f"-1_{number}", "public_url": None,
        "published_at": datetime(2026, 9, 26, tzinfo=timezone.utc), "age_hours": 24,
        "preliminary": False, "interaction_index": Decimal("2.5"), "view_index": Decimal("1.2"),
        "interaction_norm": 20.0, "view_norm": 1000.0, "norm_sample": 12, "interactions": 50,
        "reactions": 40, "comments": 10, "shares": None, "views": 1200, "erv": Decimal("4.1666"),
        "level": None, "rank": number, "institution_rank": number,
        "institution_finding_count": 3, "total": 3, "hidden_anomalous": 2,
    }
    row.update(overrides)
    return row


def test_finding_dto_keeps_unknown_distinct_from_zero() -> None:
    result = dto.finding(_row(1, interactions=0, interaction_index=Decimal("0"), level=1))
    assert result["interactions"] == 0 and result["interactionIndex"] == 0.0
    assert result["anomalyLevel"] == 1 and result["publicationType"] == "photo"
    assert result["capabilities"] == {"reactions": True, "comments": True, "shares": True}
    unknown = dto.finding(_row(1, interactions=None, interaction_index=None, age_hours=None))
    assert unknown["interactions"] is None and unknown["interactionIndex"] is None
    assert unknown["ageHours"] is None


def test_findings_body_pages_list_and_reports_summary() -> None:
    query = _query()
    rows = [_row(number) for number in (1, 2, 3)]
    body = findings_body(query, rows, [], 2, None, 9, datetime(2026, 9, 27, tzinfo=timezone.utc), "d")
    assert [item["externalId"] for item in body["items"]] == ["-1_1", "-1_2"]
    assert body["hasMore"] is True and body["nextCursor"]
    assert (body["total"], body["hiddenAnomalous"], body["groups"]) == (3, 2, [])


def test_findings_body_groups_by_institution_in_rank_order() -> None:
    query = _query(group="institution")
    rows = [_row(1, 2), _row(2, 1), _row(3, 2, institution_rank=2)]
    body = findings_body(query, rows, [], 50, None, 9, datetime(2026, 9, 27, tzinfo=timezone.utc), "d")
    assert [group["institutionLegacyId"] for group in body["groups"]] == [2, 1]
    assert [len(group["items"]) for group in body["groups"]] == [2, 1]
    assert body["items"] == [] and body["nextCursor"] is None


def test_findings_body_handles_summary_only_row() -> None:
    empty = {key: None for key in _row(1)} | {"hidden_anomalous": 4}
    body = findings_body(_query(), [empty], [], 50, None, 9, datetime(2026, 9, 27, tzinfo=timezone.utc), "d")
    assert body["items"] == [] and body["total"] == 0 and body["hiddenAnomalous"] == 4


def test_findings_unknown_institution_is_404() -> None:
    query = _query(mode="institution", institution="404")
    with pytest.raises(NotFound):
        findings_body(query, [], [{"legacy_id": 1, "short_name": None, "canonical_name": "Вуз"}], 50,
                      None, 9, datetime(2026, 9, 27, tzinfo=timezone.utc), "d")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_findings.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.routes.findings'`

- [ ] **Step 3: Write minimal implementation**

`api/dto.py` (после `statistics_publication`; `number` и `iso` уже есть в модуле, `PLATFORM_METRIC_CAPABILITIES` и `INTERACTION_COMPONENTS` импортировать из `.statistics_capabilities`):

```python
def finding(row: dict[str, Any]) -> dict[str, Any]:
    supported = PLATFORM_METRIC_CAPABILITIES[row["platform"]]
    return {
        "publicationId": str(row["publication_id"]),
        "institutionId": str(row["institution_id"]),
        "institutionLegacyId": row["institution_legacy_id"],
        "institutionShortName": row["institution_short_name"],
        "institutionCanonicalName": row["institution_canonical_name"],
        "accountId": str(row["account_id"]),
        "platform": row["platform"],
        "publicationType": row["publication_type"],
        "externalId": row["external_id"],
        "publicUrl": row["public_url"],
        "publishedAt": iso(row["published_at"]),
        "ageHours": row["age_hours"],
        "preliminary": bool(row["preliminary"]),
        "interactionIndex": number(row["interaction_index"]),
        "viewIndex": number(row["view_index"]),
        "interactionNorm": number(row["interaction_norm"]),
        "viewNorm": number(row["view_norm"]),
        "normSampleSize": row["norm_sample"] or 0,
        "interactions": row["interactions"],
        "reactions": row["reactions"],
        "comments": row["comments"],
        "shares": row["shares"],
        "views": row["views"],
        "erv": number(row["erv"]),
        "anomalyLevel": row["level"],
        "capabilities": {metric: metric in supported for metric in INTERACTION_COMPONENTS},
    }


def finding_institution(row: dict[str, Any]) -> dict[str, Any]:
    return {"legacyId": row["legacy_id"], "shortName": row["short_name"],
            "canonicalName": row["canonical_name"]}
```

Если `number()` в `api/dto.py` не принимает `float` (норма `percentile_cont` приходит как `float`), привести в DTO: `number(Decimal(str(value)))` — проверить первым запуском теста.

`api/routes/findings.py`:

```python
"""«Находки»: посты выше нормы своего аккаунта."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import dto, params as normalize
from ..cached import serve
from ..db import Database
from ..errors import NotFound
from ..findings import (
    FINDING_MIN_INDEX, FINDING_MIN_INTERACTIONS, FINDINGS_PERIOD_DAYS, INTERACTION_NORM_FLOOR,
    MIN_NORM_SAMPLE, NORM_WINDOW_DAYS, PAGE_CAP, VIEW_NORM_FLOOR,
)
from ..sql import findings as sql
from .statistics import _like_pattern, _page

router = APIRouter(tags=["Query"])

# Уровни аномалий меняют выдачу, поэтому ответ сбрасывается и по анализу.
FINDINGS_TAGS = frozenset({"publications", "catalog", "analysis"})


def findings_body(query: normalize.FindingsQuery, rows: list[dict[str, Any]],
                  institutions: list[dict[str, Any]], page_size: int, after_id: str | None,
                  revision: int, committed_at: Any, dimensions: str) -> dict[str, Any]:
    if query.institution is not None and not any(
            row["legacy_id"] == query.institution for row in institutions):
        raise NotFound("вуз не найден")
    hidden = rows[0]["hidden_anomalous"] if rows else 0
    posts = [row for row in rows if row["publication_id"] is not None]
    items: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    offset, has_more, next_cursor = 0, False, None
    if query.group == "institution":
        by_institution: dict[Any, dict[str, Any]] = {}
        for row in sorted(posts, key=lambda value: value["rank"]):
            group = by_institution.setdefault(row["institution_id"], {
                "institutionLegacyId": row["institution_legacy_id"],
                "institutionShortName": row["institution_short_name"],
                "institutionCanonicalName": row["institution_canonical_name"],
                "findingCount": row["institution_finding_count"], "items": [],
            })
            group["items"].append(dto.finding(row))
        groups = list(by_institution.values())
    else:
        visible, offset, has_more = _page(posts, after_id, page_size, "publication_id")
        items = [dto.finding(row) for row in visible]
        next_cursor = normalize.encode_scoped_cursor(
            str(visible[-1]["publication_id"]) if has_more and visible else None,
            revision, dimensions)
    return {
        "mode": query.mode, "institution": query.institution, "platform": query.platform,
        "period": query.period, "types": list(query.types), "sort": query.sort,
        "direction": query.direction, "group": query.group, "q": query.search,
        "anomalies": query.anomalies, "items": items, "groups": groups,
        "total": posts[0]["total"] if posts else 0, "hiddenAnomalous": hidden,
        "institutions": [dto.finding_institution(row) for row in institutions],
        "limit": page_size, "offset": offset, "hasMore": has_more, "nextCursor": next_cursor,
        "datasetRevision": revision, "asOf": committed_at.isoformat(),
    }


@router.get("/api/v1/findings", operation_id="getFindings")
async def findings(
    request: Request,
    mode: str | None = Query(None),
    institution: str | None = Query(None),
    platform: str | None = Query(None),
    period: str | None = Query(None),
    types: list[str] | None = Query(None),
    sort: str | None = Query(None),
    direction: str | None = Query(None),
    group: str | None = Query(None),
    q: str | None = Query(None, max_length=200),
    anomalies: str | None = Query(None),
    limit: int = Query(50),
    cursor: str | None = Query(None),
) -> Response:
    query = normalize.findings_query(mode, institution, platform, period, types, sort,
                                     direction, group, q, anomalies)
    page_size = normalize.limit(limit, default=50, maximum=50)

    async def build(revision: int, committed_at: Any) -> dict[str, Any]:
        db: Database = request.app.state.db
        dimensions = f"findings:{query.dimensions}:{page_size}"
        after_id = normalize.scoped_cursor(cursor, revision, dimensions)
        username_search = query.search[1:] if query.search.startswith("@") else query.search
        rows = await db.fetch_all(sql.FINDINGS, {
            "as_of": committed_at, "period_days": FINDINGS_PERIOD_DAYS[query.period],
            "norm_days": NORM_WINDOW_DAYS, "platform": query.platform,
            "institution_legacy_id": query.institution, "types": list(query.types),
            "q": query.search, "search_pattern": _like_pattern(query.search),
            "username_pattern": _like_pattern(username_search),
            "min_sample": MIN_NORM_SAMPLE, "interaction_floor": INTERACTION_NORM_FLOOR,
            "view_floor": VIEW_NORM_FLOOR, "mode": query.mode,
            "min_index": FINDING_MIN_INDEX, "min_interactions": FINDING_MIN_INTERACTIONS,
            "sort": query.sort, "direction": query.direction,
            "exclude_anomalies": query.anomalies == "exclude", "group": query.group,
            "cap": PAGE_CAP,
        })
        institutions = await db.fetch_all(sql.INSTITUTIONS, {})
        institutions.sort(key=lambda row: (row["short_name"] or row["canonical_name"]).lower())
        return findings_body(query, rows, institutions, page_size, after_id, revision,
                             committed_at, dimensions)

    return await serve(request, "findings", {
        "dimensions": query.dimensions, "limit": page_size, "cursor": cursor or "",
    }, FINDINGS_TAGS, build, pinned_revision=normalize.cursor_revision(cursor))
```

`api/app.py`: в строке 23 добавить `findings` в импорт `from .routes import ...`, в строке 115 — в кортеж модулей после `statistics`.

`contracts/openapi/m-ranked-v1.yaml`:
1. У операции `getStatistics` добавить `deprecated: true` и в `description` первую фразу «Deprecated: use getFindings.».
2. После блока `/api/v1/statistics` добавить путь:

```yaml
  /api/v1/findings:
    get:
      tags: [Query]
      operationId: getFindings
      summary: Read publications that performed above their account norm
      description: >-
        Compares each publication with the median of its own account at the same age (latest
        non-empty checkpoint of 1, 3, 6, 12 or 24 hours) over the 30 days before the dataset
        revision. Posts with an effective anomaly level 2-3 are excluded from norms and, unless
        anomalies=include, from results. In mode=all only posts with an interaction index of at
        least 1.5 and at least 10 interactions are returned.
      security: []
      parameters:
        - { name: mode, in: query, schema: { type: string, enum: [all, institution], default: all } }
        - { name: institution, in: query, description: Institution legacy id; required when mode=institution., schema: { type: integer, format: int64, minimum: 1 } }
        - { name: platform, in: query, schema: { type: string, enum: [all, telegram, vk, max, rutube], default: all } }
        - { name: period, in: query, schema: { type: string, enum: ['1d', '7d', '30d'], default: '7d' } }
        - { name: types, in: query, style: form, explode: true, schema: { type: array, maxItems: 5, items: { type: string, enum: [text, photo, album, video, other] } } }
        - { name: sort, in: query, schema: { type: string, enum: [interaction_index, view_index, interactions24, views24, erv24, published_at], default: interaction_index } }
        - { name: direction, in: query, schema: { type: string, enum: [asc, desc], default: desc } }
        - { name: group, in: query, schema: { type: string, enum: [none, institution], default: none } }
        - { name: q, in: query, schema: { type: string, maxLength: 200 } }
        - { name: anomalies, in: query, schema: { type: string, enum: [exclude, include], default: exclude } }
        - { name: limit, in: query, schema: { type: integer, format: int32, minimum: 1, maximum: 50, default: 50 } }
        - { name: cursor, in: query, required: false, schema: { type: string, maxLength: 512 } }
        - $ref: '#/components/parameters/IfNoneMatch'
      responses:
        '200':
          description: Revision-pinned findings.
          headers:
            ETag: { $ref: '#/components/headers/ETag' }
            Cache-Control: { $ref: '#/components/headers/PublicCache' }
          content:
            application/json:
              schema: { $ref: '#/components/schemas/Findings' }
        '304':
          description: The supplied validator matches this representation.
          headers:
            ETag: { $ref: '#/components/headers/ETag' }
```

Блоки `'400'` и `'404'` скопировать из ответов операции `getStatistics` / `getInstitution` того же файла (одинаковые ссылки на `Problem`).

3. После схемы `Statistics` добавить:

```yaml
    Finding:
      type: object
      additionalProperties: false
      required: [publicationId, institutionId, institutionLegacyId, institutionShortName, institutionCanonicalName, accountId, platform, publicationType, externalId, publicUrl, publishedAt, ageHours, preliminary, interactionIndex, viewIndex, interactionNorm, viewNorm, normSampleSize, interactions, reactions, comments, shares, views, erv, anomalyLevel, capabilities]
      properties:
        publicationId: { type: string, format: uuid }
        institutionId: { type: string, format: uuid }
        institutionLegacyId: { type: ['integer', 'null'], format: int64 }
        institutionShortName: { type: ['string', 'null'] }
        institutionCanonicalName: { type: string }
        accountId: { type: string, format: uuid }
        platform: { type: string, enum: [telegram, vk, max, rutube] }
        publicationType: { type: string }
        externalId: { type: ['string', 'null'] }
        publicUrl: { type: ['string', 'null'] }
        publishedAt: { type: ['string', 'null'], format: date-time }
        ageHours: { type: ['integer', 'null'], enum: [1, 3, 6, 12, 24, null] }
        preliminary: { type: boolean }
        interactionIndex: { type: ['number', 'null'] }
        viewIndex: { type: ['number', 'null'] }
        interactionNorm: { type: ['number', 'null'] }
        viewNorm: { type: ['number', 'null'] }
        normSampleSize: { type: integer, minimum: 0 }
        interactions: { type: ['integer', 'null'], minimum: 0 }
        reactions: { type: ['integer', 'null'], minimum: 0 }
        comments: { type: ['integer', 'null'], minimum: 0 }
        shares: { type: ['integer', 'null'], minimum: 0 }
        views: { type: ['integer', 'null'], minimum: 0 }
        erv: { type: ['number', 'null'] }
        anomalyLevel: { type: ['integer', 'null'], minimum: 0, maximum: 3 }
        capabilities: { $ref: '#/components/schemas/StatisticsCapabilities' }
    FindingGroup:
      type: object
      additionalProperties: false
      required: [institutionLegacyId, institutionShortName, institutionCanonicalName, findingCount, items]
      properties:
        institutionLegacyId: { type: ['integer', 'null'], format: int64 }
        institutionShortName: { type: ['string', 'null'] }
        institutionCanonicalName: { type: string }
        findingCount: { type: integer, minimum: 1 }
        items: { type: array, maxItems: 3, items: { $ref: '#/components/schemas/Finding' } }
    FindingInstitution:
      type: object
      additionalProperties: false
      required: [legacyId, shortName, canonicalName]
      properties:
        legacyId: { type: integer, format: int64 }
        shortName: { type: ['string', 'null'] }
        canonicalName: { type: string }
    Findings:
      type: object
      additionalProperties: false
      required: [mode, institution, platform, period, types, sort, direction, group, q, anomalies, items, groups, total, hiddenAnomalous, institutions, limit, offset, hasMore, nextCursor, datasetRevision, asOf]
      properties:
        mode: { type: string, enum: [all, institution] }
        institution: { type: ['integer', 'null'], format: int64 }
        platform: { type: string, enum: [all, telegram, vk, max, rutube] }
        period: { type: string, enum: ['1d', '7d', '30d'] }
        types: { type: array, items: { type: string, enum: [text, photo, album, video, other] } }
        sort: { type: string, enum: [interaction_index, view_index, interactions24, views24, erv24, published_at] }
        direction: { type: string, enum: [asc, desc] }
        group: { type: string, enum: [none, institution] }
        q: { type: string, maxLength: 200 }
        anomalies: { type: string, enum: [exclude, include] }
        items: { type: array, maxItems: 50, items: { $ref: '#/components/schemas/Finding' } }
        groups: { type: array, items: { $ref: '#/components/schemas/FindingGroup' } }
        total: { type: integer, minimum: 0 }
        hiddenAnomalous: { type: integer, minimum: 0 }
        institutions: { type: array, items: { $ref: '#/components/schemas/FindingInstitution' } }
        limit: { type: integer, format: int32, minimum: 1, maximum: 50 }
        offset: { type: integer, minimum: 0 }
        hasMore: { type: boolean }
        nextCursor: { type: ['string', 'null'] }
        datasetRevision: { type: integer, format: int64, minimum: 0 }
        asOf: { type: string, format: date-time }
```

`tests/test_api_contract.py`: после `STATISTICS_GROUP` добавить `FINDINGS_GROUP = {("/api/v1/findings", "GET")}` и включить её туда же, где перечисляются группы (в объединение внутри `test_entity_and_list_group_is_implemented` — рядом с `STATISTICS_GROUP`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_findings.py tests/test_api_contract.py tests/test_statistics.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/dto.py api/routes/findings.py api/app.py contracts/openapi/m-ranked-v1.yaml tests/test_api_contract.py tests/test_findings.py
git commit -m "feat(findings): GET /api/v1/findings route and contract"
```

---

### Task 5: Бюджет запроса на локальной копии

**Files:**
- Modify: `tests/test_live_query_budgets_postgres.py` (импорт `findings`, новый тест)

**Interfaces:**
- Consumes: `sql.FINDINGS` (Task 3), `_plan`, `_assert_budget`, `DEFAULT_BUDGET` из этого файла.

- [ ] **Step 1: Write the test**

```python
from api.sql import findings as findings_sql
from api.findings import (
    FINDING_MIN_INDEX, FINDING_MIN_INTERACTIONS, INTERACTION_NORM_FLOOR, MIN_NORM_SAMPLE,
    NORM_WINDOW_DAYS, PAGE_CAP, VIEW_NORM_FLOOR,
)


def test_findings_query_budget() -> None:
    settings = Settings()
    with psycopg.connect(settings.read_dsn, autocommit=True, row_factory=dict_row) as connection:
        connection.execute("SET statement_timeout='15s'")
        connection.execute("SET max_parallel_workers_per_gather=0")
        as_of = connection.execute(
            "SELECT committed_at FROM analytics.dataset_revision ORDER BY id DESC LIMIT 1").fetchone()["committed_at"]
        base = {
            "as_of": as_of, "norm_days": NORM_WINDOW_DAYS, "institution_legacy_id": None,
            "types": [], "q": "", "search_pattern": "%", "username_pattern": "%",
            "min_sample": MIN_NORM_SAMPLE, "interaction_floor": INTERACTION_NORM_FLOOR,
            "view_floor": VIEW_NORM_FLOOR, "min_index": FINDING_MIN_INDEX,
            "min_interactions": FINDING_MIN_INTERACTIONS, "sort": "interaction_index",
            "direction": "desc", "exclude_anomalies": True, "cap": PAGE_CAP,
        }
        for name, overrides in {
            "findings 30d all": {"period_days": 30, "platform": "all", "mode": "all", "group": "none"},
            "findings 7d grouped": {"period_days": 7, "platform": "all", "mode": "all", "group": "institution"},
        }.items():
            _assert_budget(name, _plan(connection, findings_sql.FINDINGS, base | overrides), DEFAULT_BUDGET)
```

- [ ] **Step 2: Run against the local clone**

Run: `API_READ_DB_HOST=127.0.0.1 API_READ_DB_PORT=55433 API_READ_DB_USER=mranked_bootstrap API_READ_DB_PASSWORD=local-demo-bootstrap API_READ_DB_NAME=mranked_findings_local .venv/bin/python -m pytest tests/test_live_query_budgets_postgres.py::test_findings_query_budget -q -s`
Expected: PASS; выводятся строки `findings 30d all: … ms` (на прототипе — 0,3–0,7 с). Если имена переменных порта в `api/config.py` (`_dsn("API_READ")`) другие — взять их оттуда. Если блоков больше 100 000, поднять лимит отдельной константой `FINDINGS_BUDGET` с комментарием об измерении, а не расширять `DEFAULT_BUDGET`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_query_budgets_postgres.py
git commit -m "test(findings): live query budget on restored data"
```

---

### Task 6: Документация API и прогрев кеша

**Files:**
- Modify: `docs/REFERENCE.md` (раздел про `/statistics` около строк 80–130)
- Modify: `operations/env/cache-warmup.env.example:13`, `operations/env/api-profile-b.env.example:16`

- [ ] **Step 1: Обновить `docs/REFERENCE.md`**

Заменить строку `- \`/statistics\` — накопленная статистика публикаций и агрегаты вузов;` на `- \`/statistics\` — «Находки»: посты выше нормы своего аккаунта;`. Рядом с абзацем про `API /api/v1/statistics` добавить абзац:

```markdown
API `/api/v1/findings` принимает `mode` (`all`, `institution`), `institution`
(legacy id вуза, обязателен при `mode=institution`), `platform`, `period`
(`1d`, `7d`, `30d`), повторяемый `types` (`text`, `photo`, `album`, `video`,
`other`), `sort`, `direction`, `group` (`none`, `institution`), `q`,
`anomalies` (`exclude`, `include`), `limit` и `cursor`. Индекс — значение поста
на самой поздней непустой точке не старше 24 часов, делённое на медиану его
аккаунта на том же часу за 30 дней (не меньше 5 взаимодействий и 50
просмотров; нужно 10 постов). `/api/v1/statistics` устарел и будет удалён
отдельным изменением.
```

- [ ] **Step 2: Прогрев кеша**

В обоих файлах в JSON-массив `API_CACHE_WARMUP_TARGETS` дописать в конец (перед `"/api/v1/site/summary"`) `"/api/v1/findings?period=7d"` и `"/api/v1/findings?period=7d&group=institution"`. Строки старого `/api/v1/statistics` оставить.

- [ ] **Step 3: Проверить конфигурацию**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add docs/REFERENCE.md operations/env/cache-warmup.env.example operations/env/api-profile-b.env.example
git commit -m "docs(findings): API reference and cache warmup targets"
```

---

### Task 7: Фронтенд — клиент API, типы и логика страницы

**Files:**
- Regenerate: `contracts/openapi/m-ranked-v1-client.ts`, `frontend/lib/api-reference.generated.json`
- Modify: `frontend/lib/types.ts` (типы `Finding*`)
- Modify: `frontend/lib/api.ts` (метод `findings`, удалить `statistics`)
- Modify: `frontend/lib/revision-cache.ts:11` (добавить `findings` в `PUBLIC_DOMAINS`)
- Modify: `frontend/lib/api-reference.ts` (текст для `getFindings`, `getStatistics` помечен устаревшим)
- Create: `frontend/lib/findings.ts`
- Delete: `frontend/lib/statistics.ts`, `frontend/tests/statistics.test.ts`
- Modify: `frontend/tests/api.test.ts` (тест `statistics client…` заменить)
- Test: `frontend/tests/findings.test.ts`

**Interfaces:**
- Consumes: схемы `Findings`, `Finding`, `FindingGroup`, `FindingInstitution` (Task 4).
- Produces (`frontend/lib/types.ts`): `FindingsPage = components["schemas"]["Findings"]`, `Finding`, `FindingGroup`, `FindingInstitution`; `FindingsRequest` (поля `ParsedFindingsQuery` + `anomalies: "exclude" | "include"`, `limit?`, `cursor?`).
- Produces (`frontend/lib/findings.ts`): `FINDINGS_PERIOD_OPTIONS`, `FINDINGS_SORT_OPTIONS`, `FINDINGS_TYPE_OPTIONS`, `type FindingsMode = "all" | "institution"`, `type FindingsPeriod = "1d" | "7d" | "30d"`, `type FindingsSort`, `type FindingsType`, `type FindingsGroup = "none" | "institution"`, `interface ParsedFindingsQuery { mode; institution: number | null; platform: Platform; period; types: FindingsType[]; sort; direction: SortDirection; group; q: string }`, `normalizeFindingsQuery(params: SearchParams): ParsedFindingsQuery`, `findingsHrefQuery(query): Record<string, QueryValue>`, `formatIndex(value: number | null): string`, `findingBadge(row: Finding, anomaliesVisible: boolean): string | null`, `INSTITUTION_STORAGE_KEY = "m-ranked-findings-institution"`, `rememberInstitution(storage: Pick<Storage, "setItem"> | null, id: number): void`, `recallInstitution(storage: Pick<Storage, "getItem"> | null): number | null`.
- Produces (`frontend/lib/api.ts`): `api.findings(input: FindingsRequest): Promise<FindingsPage>`.

- [ ] **Step 1: Regenerate the client**

Run: `cd frontend && pnpm generate:api`
Expected: изменены `contracts/openapi/m-ranked-v1-client.ts` и `lib/api-reference.generated.json`; `pnpm check:api` проходит.

- [ ] **Step 2: Write the failing test**

```ts
// frontend/tests/findings.test.ts
import assert from "node:assert/strict";
import test from "node:test";
import {
  findingBadge, findingsHrefQuery, formatIndex, normalizeFindingsQuery,
  recallInstitution, rememberInstitution,
} from "../lib/findings";
import type { Finding } from "../lib/types";

test("findings defaults to all institutions, 7 days and interaction index", () => {
  assert.deepEqual(normalizeFindingsQuery({}), {
    mode: "all", institution: null, platform: "all", period: "7d", types: [],
    sort: "interaction_index", direction: "desc", group: "none", q: "",
  });
});

test("findings normalizes unknown values instead of failing", () => {
  const query = normalizeFindingsQuery({
    mode: "institution", institution: "abc", period: "3h", types: ["gif", "video", "photo", "video"],
    sort: "erv", direction: "up", group: "platform", q: "  мгу ",
  });
  assert.equal(query.mode, "all");
  assert.equal(query.institution, null);
  assert.equal(query.period, "7d");
  assert.deepEqual(query.types, ["photo", "video"]);
  assert.equal(query.sort, "interaction_index");
  assert.equal(query.direction, "desc");
  assert.equal(query.group, "none");
  assert.equal(query.q, "мгу");
});

test("institution mode keeps the id and drops grouping", () => {
  const query = normalizeFindingsQuery({ mode: "institution", institution: "12", group: "institution" });
  assert.equal(query.mode, "institution");
  assert.equal(query.institution, 12);
  assert.equal(query.group, "none");
});

test("href query omits defaults-free empties and repeats types", () => {
  const query = normalizeFindingsQuery({ types: ["photo", "video"], q: "" });
  assert.deepEqual(findingsHrefQuery(query), {
    mode: undefined, institution: undefined, platform: "all", period: "7d",
    types: ["photo", "video"], sort: "interaction_index", direction: "desc", group: undefined, q: undefined,
  });
});

test("formatIndex covers small, large and missing values", () => {
  assert.equal(formatIndex(4.2), "×4,2");
  assert.equal(formatIndex(0.4), "×0,4");
  assert.equal(formatIndex(70.5), "×70,5");
  assert.equal(formatIndex(2), "×2,0");
  assert.equal(formatIndex(null), "—");
});

const base = { ageHours: 24, preliminary: false, anomalyLevel: 0 } as Finding;

test("one badge by priority: preliminary, gap hour, weak signal, unchecked", () => {
  assert.equal(findingBadge({ ...base, ageHours: 6, preliminary: true, anomalyLevel: 1 }, true), "предварительно, 6 ч");
  assert.equal(findingBadge({ ...base, ageHours: 12 }, true), "по 12-му часу");
  assert.equal(findingBadge({ ...base, anomalyLevel: 1 }, true), "слабый сигнал");
  assert.equal(findingBadge({ ...base, anomalyLevel: null }, true), "не проверен");
  assert.equal(findingBadge({ ...base, anomalyLevel: null }, false), null);
  assert.equal(findingBadge(base, true), null);
});

test("rememberInstitution survives throwing storage", () => {
  const broken = { setItem() { throw new Error("denied"); }, getItem() { throw new Error("denied"); } };
  assert.doesNotThrow(() => rememberInstitution(broken, 5));
  assert.equal(recallInstitution(broken), null);
  assert.equal(recallInstitution(null), null);
  const values = new Map<string, string>();
  const storage = { setItem: (key: string, value: string) => void values.set(key, value), getItem: (key: string) => values.get(key) ?? null };
  rememberInstitution(storage, 7);
  assert.equal(recallInstitution(storage), 7);
  values.set("m-ranked-findings-institution", "-3");
  assert.equal(recallInstitution(storage), null);
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && node --import tsx --test tests/findings.test.ts`
Expected: FAIL with `Cannot find module '../lib/findings'`

- [ ] **Step 4: Write minimal implementation**

`frontend/lib/types.ts` — удалить блок `StatisticsView … StatisticsPage` кроме `SortDirection`, добавить:

```ts
export type FindingsPage = components["schemas"]["Findings"];
export type Finding = components["schemas"]["Finding"];
export type FindingGroup = components["schemas"]["FindingGroup"];
export type FindingInstitution = components["schemas"]["FindingInstitution"];
```

Если удаление `Statistics*` ломает импорты в других файлах (`grep -rn "Statistics" frontend/lib frontend/components frontend/app`), удалить эти импорты вместе с файлами в Task 8.

`frontend/lib/findings.ts`:

```ts
import { first, many, normalizePlatform, parsePositiveLegacyId, type QueryValue, type SearchParams } from "./params";
import type { Finding, Platform, SortDirection } from "./types";

export type FindingsMode = "all" | "institution";
export type FindingsPeriod = "1d" | "7d" | "30d";
export type FindingsSort = "interaction_index" | "view_index" | "interactions24" | "views24" | "erv24" | "published_at";
export type FindingsType = "text" | "photo" | "album" | "video" | "other";
export type FindingsGroup = "none" | "institution";

export const FINDINGS_PERIOD_OPTIONS = [
  { value: "1d", label: "24 ч", title: "Сутки" },
  { value: "7d", label: "7 д", title: "7 дней" },
  { value: "30d", label: "30 д", title: "30 дней" },
] as const satisfies readonly { value: FindingsPeriod; label: string; title: string }[];

export const FINDINGS_SORT_OPTIONS = [
  ["interaction_index", "Индекс взаимодействий"],
  ["view_index", "Индекс просмотров"],
  ["interactions24", "Взаимодействия · 24 ч"],
  ["views24", "Просмотры · 24 ч"],
  ["erv24", "ERV · 24 ч"],
  ["published_at", "Новые"],
] as const satisfies readonly (readonly [FindingsSort, string])[];

export const FINDINGS_TYPE_OPTIONS = [
  ["text", "Текст"], ["photo", "Фото"], ["album", "Альбом"], ["video", "Видео"], ["other", "Прочее"],
] as const satisfies readonly (readonly [FindingsType, string])[];

export interface ParsedFindingsQuery {
  mode: FindingsMode;
  institution: number | null;
  platform: Platform;
  period: FindingsPeriod;
  types: FindingsType[];
  sort: FindingsSort;
  direction: SortDirection;
  group: FindingsGroup;
  q: string;
}

const PERIODS = new Set<string>(FINDINGS_PERIOD_OPTIONS.map((option) => option.value));
const SORTS = new Set<string>(FINDINGS_SORT_OPTIONS.map(([value]) => value));
const TYPES: readonly FindingsType[] = FINDINGS_TYPE_OPTIONS.map(([value]) => value);

export function normalizeFindingsQuery(params: SearchParams): ParsedFindingsQuery {
  const institution = parsePositiveLegacyId(first(params.institution) ?? "");
  const mode: FindingsMode = first(params.mode) === "institution" && institution !== null ? "institution" : "all";
  const period = first(params.period) ?? "";
  const sort = first(params.sort) ?? "";
  const requested = new Set(many(params.types));
  return {
    mode,
    institution: mode === "institution" ? institution : null,
    platform: normalizePlatform(params.platform, "all"),
    period: PERIODS.has(period) ? period as FindingsPeriod : "7d",
    types: TYPES.filter((value) => requested.has(value)),
    sort: SORTS.has(sort) ? sort as FindingsSort : "interaction_index",
    direction: first(params.direction) === "asc" ? "asc" : "desc",
    group: mode === "all" && first(params.group) === "institution" ? "institution" : "none",
    q: (first(params.q) ?? "").trim(),
  };
}

export function findingsHrefQuery(query: ParsedFindingsQuery): Record<string, QueryValue> {
  return {
    mode: query.mode === "institution" ? "institution" : undefined,
    institution: query.institution ?? undefined,
    platform: query.platform,
    period: query.period,
    types: query.types,
    sort: query.sort,
    direction: query.direction,
    group: query.group === "institution" ? "institution" : undefined,
    q: query.q || undefined,
  };
}

const indexFormat = new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function formatIndex(value: number | null): string {
  return value === null ? "—" : `×${indexFormat.format(value)}`;
}

/** Не больше одной пометки на строку: возраст важнее уровня анализа. */
export function findingBadge(row: Finding, anomaliesVisible: boolean): string | null {
  if (row.preliminary && row.ageHours !== null) return `предварительно, ${row.ageHours} ч`;
  if (row.ageHours !== null && row.ageHours < 24) return `по ${row.ageHours}-му часу`;
  if (!anomaliesVisible) return null;
  if (row.anomalyLevel === 1) return "слабый сигнал";
  if (row.anomalyLevel === null) return "не проверен";
  return null;
}

export const INSTITUTION_STORAGE_KEY = "m-ranked-findings-institution";

export function rememberInstitution(storage: Pick<Storage, "setItem"> | null, id: number): void {
  try { storage?.setItem(INSTITUTION_STORAGE_KEY, String(id)); } catch { /* приватный режим: только удобство */ }
}

export function recallInstitution(storage: Pick<Storage, "getItem"> | null): number | null {
  try { return parsePositiveLegacyId(storage?.getItem(INSTITUTION_STORAGE_KEY) ?? ""); } catch { return null; }
}
```

Если `QueryValue` не экспортируется из `lib/params.ts`, добавить `export` к его объявлению (тип уже используется `queryHref`).

`frontend/lib/api.ts` — заменить метод `statistics` на:

```ts
    findings(input: FindingsRequest) {
      const q = (input.q ?? "").trim();
      if ([...q].length > 200) throw new RangeError("q must contain at most 200 characters");
      return client.GET("/api/v1/findings", { params: { query: {
        mode: input.mode, platform: input.platform, period: input.period,
        ...(input.institution !== null ? { institution: input.institution } : {}),
        ...(input.types.length ? { types: input.types } : {}),
        sort: input.sort, direction: input.direction, group: input.group,
        q: q || undefined, anomalies: input.anomalies,
        limit: Math.min(50, Math.max(1, input.limit ?? 50)),
        ...(input.cursor ? { cursor: input.cursor } : {}),
      } } }).then(unwrap);
    },
```

и в импорте типов заменить `StatisticsRequest` на `FindingsRequest`, объявив его в `frontend/lib/types.ts`:

```ts
export type FindingsRequest = import("./findings").ParsedFindingsQuery & {
  anomalies: "exclude" | "include"; limit?: number; cursor?: string;
};
```

`frontend/lib/revision-cache.ts:11` — в `PUBLIC_DOMAINS` заменить `overview|statistics|` на `overview|statistics|findings|`.

`frontend/lib/api-reference.ts` — `getStatistics.text` начать с «Устарел, используйте /api/v1/findings. »; добавить:

```ts
  getFindings: {
    section: "overview", title: "Находки: посты выше нормы",
    text: "Данные страницы /statistics: посты, сработавшие лучше обычного для своего аккаунта, с индексом к норме на возрасте до 24 часов. Все вузы или один вуз, группировка по вузам, курсор.",
    example: "/api/v1/findings?platform=vk&period=7d&limit=20",
  },
```

`frontend/tests/api.test.ts` — тест `statistics client sends every result dimension and bounds the limit` заменить на тот же по форме тест для `client.findings({ mode: "institution", institution: 12, platform: "vk", period: "30d", types: ["photo", "video"], sort: "view_index", direction: "asc", group: "none", q: " мгу ", anomalies: "include", limit: 500 })` с проверками: `url.pathname === "/api/v1/findings"`, `url.searchParams.getAll("types")` равно `["photo", "video"]`, `institution === "12"`, `q === "мгу"`, `anomalies === "include"`, `limit === "50"`. Тело и мок клиента скопировать из удаляемого теста (строки 143–170).

Удалить `frontend/lib/statistics.ts` и `frontend/tests/statistics.test.ts`.

- [ ] **Step 5: Run tests**

Run: `cd frontend && node --import tsx --test tests/findings.test.ts tests/api.test.ts tests/revision-cache.test.ts tests/methodology.test.ts`
Expected: PASS. `pnpm typecheck` на этом шаге упадёт на `app/statistics/page.tsx` и `components/statistics-*` — это чинит Task 8.

- [ ] **Step 6: Commit**

```bash
git add contracts/openapi/m-ranked-v1-client.ts frontend/lib frontend/tests
git commit -m "feat(findings): frontend client, query state and formatting"
```

---

### Task 8: Страница «Находки»

**Files:**
- Create: `frontend/components/ui/combobox.tsx` (через shadcn CLI)
- Create: `frontend/components/findings/filter-form.tsx`, `frontend/components/findings/institution-picker.tsx`, `frontend/components/findings/types-popover.tsx`, `frontend/components/findings/findings-results.tsx`
- Modify: `frontend/app/statistics/page.tsx` (полная замена)
- Modify: `frontend/components/skeletons.tsx:106-158` (`StatisticsSkeleton` без `view`, новый заголовок)
- Delete: `frontend/components/statistics-results.tsx`, `frontend/components/statistics-filter-form.tsx`

**Interfaces:**
- Consumes: всё из Task 7; `PageHeader`, `ApiFailureState` из `@/components/ui`; `MethodNote`; `NativeSegments`; `NativeSelect`; `FILTER_PLATFORM_OPTIONS`, `STICKY_CONTROL_SURFACE_CLASS` из `@/components/filter-toolbar`; `anomalyReportVisible()`; `typeName()`; `publicationHref`, `RowLink`, `formatMetric`, `formatPercentage`, `PLATFORM_LONG_LABELS`, `publicationLabel`.
- Produces: `FindingsFilterForm` (client), `InstitutionPicker` (client, props `{ institutions: FindingInstitution[]; value: number | null }`, пишет скрытый `input name="institution"`), `TypesPopover` (client, props `{ value: FindingsType[]; group: FindingsGroup; groupAvailable: boolean }`), `FindingsResults` (client, props `{ page: FindingsPage; query: ParsedFindingsQuery; anomaliesVisible: boolean }`). Тест-идентификаторы: `filter-toolbar`, `findings-table`, `findings-cards`, `findings-groups`, `findings-hidden-note`.

- [ ] **Step 1: Добавить Combobox**

Run: `cd frontend && pnpm dlx shadcn@4.21.0 add combobox`
Expected: создан `components/ui/combobox.tsx` в стиле `base-mira`. Открыть файл и выписать фактические экспорты (`grep -n "^export\|^function Combobox" components/ui/combobox.tsx`); код ниже рассчитан на `Combobox`, `ComboboxInput`, `ComboboxContent`, `ComboboxList`, `ComboboxItem`, `ComboboxEmpty` — при других именах заменить их в `institution-picker.tsx`, сохранив поведение.

- [ ] **Step 2: Форма фильтров**

`frontend/components/findings/filter-form.tsx` — копия логики `statistics-filter-form.tsx` (её затем удалить), но с `append` для повторяемых полей и путём `/statistics`:

```tsx
"use client";

import { beginNavigation } from "@/lib/navigation-pending";
import { useRouter } from "next/navigation";
import { useRef, useTransition, type ComponentProps } from "react";
import { useStuck } from "@/components/use-stuck";

/** GET-форма фильтров: работает и без скриптов, со скриптами — без перезагрузки. */
export function FindingsFilterForm(props: ComponentProps<"form">) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [pending, startTransition] = useTransition();
  useStuck(formRef);

  function navigate(form: HTMLFormElement) {
    const query = new URLSearchParams();
    new FormData(form).forEach((value, key) => {
      if (typeof value === "string" && value !== "") query.append(key, value);
    });
    beginNavigation();
    startTransition(() => router.push(`/statistics?${query}`, { scroll: false }));
  }

  return (
    <form {...props} ref={formRef} aria-busy={pending}
      onChange={(event) => {
        const field = event.target;
        if (field instanceof HTMLSelectElement
          || (field instanceof HTMLInputElement && (field.type === "radio" || field.type === "checkbox" || field.type === "hidden"))) {
          event.currentTarget.requestSubmit();
        }
      }}
      onSubmit={(event) => { event.preventDefault(); navigate(event.currentTarget); }}>
      {props.children}
      <span className="sr-only" role="status" hidden={!pending}>Обновляю…</span>
    </form>
  );
}
```

- [ ] **Step 3: Выбор вуза**

`frontend/components/findings/institution-picker.tsx`:

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from "@/components/ui/combobox";
import { recallInstitution, rememberInstitution } from "@/lib/findings";
import type { FindingInstitution } from "@/lib/types";

const label = (item: FindingInstitution) => item.shortName || item.canonicalName;

function browserStorage(): Storage | null {
  try { return window.localStorage; } catch { return null; }
}

/** Вуз режима «Мой вуз». Значение уходит в форму скрытым полем; выбор
 *  запоминается в localStorage только как удобство следующего визита. */
export function InstitutionPicker({ institutions, value }: { institutions: FindingInstitution[]; value: number | null }) {
  const hidden = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<FindingInstitution | null>(
    institutions.find((item) => item.legacyId === value) ?? null);

  function choose(item: FindingInstitution | null) {
    setSelected(item);
    if (!item || !hidden.current) return;
    rememberInstitution(browserStorage(), item.legacyId);
    hidden.current.value = String(item.legacyId);
    hidden.current.form?.requestSubmit();
  }

  useEffect(() => {
    if (value !== null) return;
    const remembered = recallInstitution(browserStorage());
    const item = institutions.find((entry) => entry.legacyId === remembered);
    if (item) choose(item);
    // Только при первом показе пустого режима.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <>
    <input ref={hidden} type="hidden" name="institution" defaultValue={value ?? ""} />
    <Combobox items={institutions} value={selected} onValueChange={choose} itemToStringLabel={label}>
      <ComboboxInput placeholder="Выберите вуз" aria-label="Вуз" className="h-8 w-full sm:w-64" />
      <ComboboxContent>
        <ComboboxEmpty>Вуз не найден</ComboboxEmpty>
        <ComboboxList>
          {(item: FindingInstitution) => (
            <ComboboxItem key={item.legacyId} value={item}>
              <span className="min-w-0">
                <span className="block font-medium">{label(item)}</span>
                {item.shortName ? <span className="text-muted-foreground block truncate text-xs">{item.canonicalName}</span> : null}
              </span>
            </ComboboxItem>
          )}
        </ComboboxList>
      </ComboboxContent>
    </Combobox>
  </>;
}
```

Если у сгенерированного `Combobox` другие имена пропсов для подписи (`itemToStringLabel`), взять их из `components/ui/combobox.tsx` и документации Base UI Combobox, сохранив поиск по `shortName` и `canonicalName`.

- [ ] **Step 4: Popover «Фильтры»**

`frontend/components/findings/types-popover.tsx`:

```tsx
"use client";

import { SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { FINDINGS_TYPE_OPTIONS, type FindingsGroup, type FindingsType } from "@/lib/findings";

/** Редкие фильтры: тип публикации и группировка. Счётчик — число активных. */
export function TypesPopover({ value, group, groupAvailable }: {
  value: FindingsType[]; group: FindingsGroup; groupAvailable: boolean;
}) {
  const active = value.length + (group === "institution" ? 1 : 0);
  return (
    <Popover>
      <PopoverTrigger render={<Button type="button" variant="outline" size="sm" className="h-8" />}>
        <SlidersHorizontal aria-hidden="true" />Фильтры{active ? <span className="tabular-nums">· {active}</span> : null}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 space-y-4">
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Тип публикации</legend>
          {FINDINGS_TYPE_OPTIONS.map(([type, label]) => (
            <label key={type} className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="types" value={type} defaultChecked={value.includes(type)} className="accent-primary size-4" />
              {label}
            </label>
          ))}
        </fieldset>
        {groupAvailable ? (
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Показать</legend>
            {(["none", "institution"] as const).map((option) => (
              <label key={option} className="flex items-center gap-2 text-sm">
                <input type="radio" name="group" value={option === "none" ? "" : option} defaultChecked={group === option} className="accent-primary size-4" />
                {option === "none" ? "Списком" : "По вузам"}
              </label>
            ))}
          </fieldset>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
```

Popover рендерит содержимое в портал — поля окажутся вне `<form>`. Поэтому каждому `input` добавить атрибут `form="findings-filters"`, а форме страницы — `id="findings-filters"`; `onChange` формы не увидит событие из портала, поэтому на `input` повесить `onChange={(event) => event.currentTarget.form?.requestSubmit()}`.

- [ ] **Step 5: Результаты**

`frontend/components/findings/findings-results.tsx`:

```tsx
"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";
import Link from "@/components/native-link";
import { RowLink } from "@/components/row-link";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { typeName } from "@/lib/compare-dashboard";
import { publicationHref } from "@/lib/entity-routes";
import { findingBadge, findingsHrefQuery, formatIndex, type ParsedFindingsQuery } from "@/lib/findings";
import { formatMetric, formatPercentage, PLATFORM_LABELS, publicationLabel } from "@/lib/format";
import { queryHref } from "@/lib/params";
import type { Finding, FindingsPage } from "@/lib/types";
import { cn } from "@/lib/utils";

const published = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
});

export function FindingsResults({ page, query, anomaliesVisible }: {
  page: FindingsPage; query: ParsedFindingsQuery; anomaliesVisible: boolean;
}) {
  const [shown, setShown] = useState(20);
  const hiddenNote = anomaliesVisible && page.hiddenAnomalous > 0
    ? <p data-testid="findings-hidden-note" className="text-muted-foreground text-xs">
        Скрыто постов с выраженной аномалией: {page.hiddenAnomalous}. <Link className="underline underline-offset-4" href="/compare#anomalies">Подробнее на сравнении</Link>
      </p>
    : null;

  if (query.group === "institution") {
    if (!page.groups.length) return <><NoFindings query={query} />{hiddenNote}</>;
    return <TooltipProvider><div data-testid="findings-groups" className="space-y-4">
      {page.groups.map((group) => (
        <section key={group.institutionLegacyId ?? group.institutionCanonicalName} className="bg-card rounded-xl border p-4 md:p-5">
          <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-heading font-semibold" title={group.institutionCanonicalName}>{group.institutionShortName || group.institutionCanonicalName}</h2>
            <span className="text-muted-foreground text-sm">выше нормы: {group.findingCount}</span>
          </header>
          <FindingRows rows={group.items} query={query} anomaliesVisible={anomaliesVisible} showInstitution={false} />
          {group.institutionLegacyId !== null ? (
            <Link className="text-sm underline-offset-4 hover:underline" prefetch={false}
              href={queryHref("/statistics", { ...findingsHrefQuery(query), mode: "institution", institution: group.institutionLegacyId, group: undefined })}>
              Все посты вуза →
            </Link>
          ) : null}
        </section>
      ))}
      {hiddenNote}
    </div></TooltipProvider>;
  }

  if (!page.items.length) return <><NoFindings query={query} />{hiddenNote}</>;
  const visible = page.items.slice(0, shown);
  return <TooltipProvider><div className="space-y-3 md:rounded-xl md:border md:bg-card md:p-5">
    <FindingRows rows={visible} query={query} anomaliesVisible={anomaliesVisible} showInstitution={query.mode === "all"} />
    {shown < page.items.length ? <div className="flex justify-center"><Button type="button" variant="outline" onClick={() => setShown(page.items.length)}>Показать ещё</Button></div>
      : page.nextCursor ? <div className="flex justify-center"><Link className={buttonVariants({ variant: "outline" })} prefetch={false}
          href={queryHref("/statistics", { ...findingsHrefQuery(query), cursor: page.nextCursor })}>Следующие 50</Link></div> : null}
    {hiddenNote}
  </div></TooltipProvider>;
}

function FindingRows({ rows, query, anomaliesVisible, showInstitution }: {
  rows: Finding[]; query: ParsedFindingsQuery; anomaliesVisible: boolean; showInstitution: boolean;
}) {
  return <>
    <div className="hidden overflow-x-auto md:block"><Table data-testid="findings-table" className="tabular">
      <caption className="sr-only">Посты выше нормы своего аккаунта</caption>
      <TableHeader><TableRow>
        <TableHead>Пост</TableHead><TableHead>Индекс</TableHead><TableHead>Взаимодействия</TableHead>
        <TableHead>Просмотры</TableHead><TableHead>ERV</TableHead><TableHead className="w-12"><span className="sr-only">Оригинал</span></TableHead>
      </TableRow></TableHeader>
      <TableBody>{rows.map((row) => (
        <RowLink key={row.publicationId} href={publicationHref(row.publicationId)} className="hover:bg-muted/50 cursor-pointer">
          <TableCell className="min-w-64 whitespace-normal"><Identity row={row} showInstitution={showInstitution} badge={findingBadge(row, anomaliesVisible)} /></TableCell>
          <TableCell><IndexValue row={row} /></TableCell>
          <TableCell><Interactions row={row} /></TableCell>
          <TableCell>{formatMetric(row.views)}</TableCell>
          <TableCell>{formatPercentage(row.erv)}</TableCell>
          <TableCell><Original row={row} /></TableCell>
        </RowLink>
      ))}</TableBody>
    </Table></div>
    <div data-testid="findings-cards" className="grid gap-3 md:hidden">{rows.map((row) => (
      <article key={row.publicationId} className="bg-card rounded-xl border p-4">
        <div className="flex items-start justify-between gap-3">
          <Identity row={row} showInstitution={showInstitution} badge={findingBadge(row, anomaliesVisible)} />
          <IndexValue row={row} prominent />
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
          <Pair label="Взаимодействия" value={formatMetric(row.interactions)} />
          <Pair label="Просмотры" value={formatMetric(row.views)} />
          <Pair label="ERV" value={formatPercentage(row.erv)} />
        </dl>
        <div className="mt-3 flex gap-2">
          <Link className={cn(buttonVariants({ variant: "outline" }), "flex-1")} href={publicationHref(row.publicationId)} prefetch={false}>Открыть карточку</Link>
          <Original row={row} />
        </div>
      </article>
    ))}</div>
    <span className="sr-only">Сортировка: {query.sort}</span>
  </>;
}

function Identity({ row, showInstitution, badge }: { row: Finding; showInstitution: boolean; badge: string | null }) {
  const number = row.externalId ? publicationLabel(row.externalId, row.platform).replace(/^(?:№\s*)+/, "") : null;
  return <div className="min-w-0">
    <div className="flex flex-wrap items-center gap-x-1.5 text-sm">
      {showInstitution ? <span className="font-semibold" title={row.institutionCanonicalName}>{row.institutionShortName || row.institutionCanonicalName}</span> : null}
      <span className="text-muted-foreground">{PLATFORM_LABELS[row.platform]} · {typeName(row.publicationType)}{number ? ` · №${number}` : ""}</span>
    </div>
    <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-1.5 text-xs">
      {row.publishedAt ? published.format(new Date(row.publishedAt)) : null}
      {badge ? <Badge variant="outline" className="rounded-full font-normal">{badge}</Badge> : null}
    </div>
  </div>;
}

function IndexValue({ row, prominent = false }: { row: Finding; prominent?: boolean }) {
  const strong = (row.interactionIndex ?? 0) >= 2;
  const text = formatIndex(row.interactionIndex);
  const tip = row.interactionIndex === null
    ? "Мало истории для нормы: нужно 10 постов аккаунта с замером на этом возрасте."
    : `Норма аккаунта: ${formatMetric(row.interactionNorm, true)} взаимодействий на ${row.ageHours}-м часу (${row.normSampleSize} постов). Индекс просмотров: ${formatIndex(row.viewIndex)}.`;
  return <Tooltip><TooltipTrigger render={<button type="button" className={cn("relative z-10 cursor-help tabular-nums font-bold", prominent && "font-heading text-xl", strong && "text-primary")} aria-label={`Индекс ${text}. Подробнее`} />}>{text}</TooltipTrigger>
    <TooltipContent className="max-w-sm whitespace-normal leading-relaxed">{tip}</TooltipContent></Tooltip>;
}

function Interactions({ row }: { row: Finding }) {
  const parts = [
    row.capabilities.reactions ? `реакции ${formatMetric(row.reactions)}` : null,
    row.capabilities.comments ? `комментарии ${formatMetric(row.comments)}` : null,
    row.capabilities.shares ? `репосты ${formatMetric(row.shares)}` : null,
  ].filter(Boolean).join(" · ");
  return <Tooltip><TooltipTrigger render={<button type="button" className="relative z-10 cursor-help border-b border-dotted border-current tabular-nums" aria-label={`Взаимодействия ${formatMetric(row.interactions)}: ${parts}`} />}>{formatMetric(row.interactions)}</TooltipTrigger>
    <TooltipContent>{parts}</TooltipContent></Tooltip>;
}

function Original({ row }: { row: Finding }) {
  return row.publicUrl ? <a className="hover:bg-accent focus-visible:ring-ring relative z-10 inline-flex size-9 items-center justify-center rounded-md focus-visible:ring-2" href={row.publicUrl} target="_blank" rel="noopener noreferrer" aria-label="Открыть оригинал"><ExternalLink className="size-4" aria-hidden="true" /></a> : null;
}

function Pair({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-muted-foreground text-[10px] uppercase">{label}</dt><dd className="font-medium tabular-nums">{value}</dd></div>;
}

function NoFindings({ query }: { query: ParsedFindingsQuery }) {
  const wider = query.period !== "30d";
  return <Empty role="status" className="bg-card border py-10">
    <EmptyHeader>
      <EmptyTitle><h2 className="font-heading text-lg font-semibold">{query.q ? "Ничего не найдено" : "За период нет постов выше нормы"}</h2></EmptyTitle>
      <EmptyDescription className="text-sm">{query.platform === "rutube" ? "На RuTube взаимодействий мало, и посты редко выходят за норму." : "Норма — типичный пост своего аккаунта на том же возрасте."}</EmptyDescription>
    </EmptyHeader>
    {wider ? <EmptyContent><Link className={buttonVariants({ variant: "outline" })} prefetch={false}
      href={queryHref("/statistics", { ...findingsHrefQuery(query), period: "30d" })}>Расширить до 30 дней</Link></EmptyContent> : null}
  </Empty>;
}
```

- [ ] **Step 6: Страница**

`frontend/app/statistics/page.tsx` (полная замена):

```tsx
import type { Metadata } from "next";
import { ArrowRight, Search, X } from "lucide-react";
import Link from "@/components/native-link";
import { FindingsFilterForm } from "@/components/findings/filter-form";
import { FindingsResults } from "@/components/findings/findings-results";
import { InstitutionPicker } from "@/components/findings/institution-picker";
import { TypesPopover } from "@/components/findings/types-popover";
import { STICKY_CONTROL_SURFACE_CLASS, FILTER_PLATFORM_OPTIONS, FILTER_SELECT_CLASS } from "@/components/filter-toolbar";
import { MethodNote } from "@/components/method-note";
import { NativeSegments } from "@/components/native-field";
import { NavigationBoundary } from "@/components/navigation-boundary";
import { StatisticsSkeleton } from "@/components/skeletons";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Empty, EmptyHeader, EmptyTitle } from "@/components/ui/empty";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput } from "@/components/ui/input-group";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { ApiFailureState, PageHeader } from "@/components/ui";
import { anomalyReportVisible } from "@/lib/anomaly-visibility";
import { api, ApiError } from "@/lib/api";
import { FINDINGS_PERIOD_OPTIONS, FINDINGS_SORT_OPTIONS, findingsHrefQuery, normalizeFindingsQuery } from "@/lib/findings";
import { formatDate } from "@/lib/format";
import { first, queryHref, type SearchParams } from "@/lib/params";
import type { FindingInstitution, FindingsPage } from "@/lib/types";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Находки: посты выше нормы",
  description: "Посты вузов, сработавшие лучше обычного для своего аккаунта: индекс к норме на одном возрасте поста.",
};

const MODE_OPTIONS = [
  { value: "all", label: "Все вузы", title: "Лучшие посты всех вузов" },
  { value: "institution", label: "Мой вуз", title: "Посты одного вуза" },
] as const;

export default async function FindingsPageRoute({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const raw = await searchParams;
  const query = normalizeFindingsQuery(raw);
  // «Мой вуз» без выбранного вуза — пустое состояние с выбором, без запроса постов.
  const choosing = first(raw.mode) === "institution" && query.mode === "all";
  const anomaliesVisible = anomalyReportVisible();
  const anomalies = anomaliesVisible ? "exclude" : "include";
  const cursor = first(raw.cursor);
  let page: FindingsPage | null = null;
  let institutions: FindingInstitution[] = [];
  let failed = false;
  let unknownInstitution = false;
  try {
    // Без выбранного вуза посты не нужны: запрос только за списком вузов.
    page = await api.findings({ ...query, group: choosing ? "none" : query.group, anomalies,
      limit: choosing ? 1 : 50, cursor: choosing ? undefined : cursor });
    institutions = page.institutions;
  } catch (error) {
    if (error instanceof ApiError && error.status === 400 && cursor) {
      // Курсор устарел (сменилась ревизия): начинаем список заново.
      redirect(queryHref("/statistics", findingsHrefQuery(query)));
    }
    if (error instanceof ApiError && error.status === 404) {
      unknownInstitution = true;
      institutions = await api.findings({ ...query, mode: "all", institution: null, group: "none", anomalies, limit: 1 })
        .then((body) => body.institutions, () => []);
    } else failed = true;
  }
  const institutionMode = query.mode === "institution" || choosing || unknownInstitution;
  const selectionKey = JSON.stringify(findingsHrefQuery(query));
  const updated = page ? new Date(page.asOf).toLocaleTimeString("ru-RU", { timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit" }) : null;

  return <>
    <PageHeader
      title="Находки: посты выше нормы"
      titleNote={<MethodNote title="Как считается индекс"><p>Индекс — взаимодействия поста на 24-м часу (у свежих — на последнем замере), делённые на типичное значение его аккаунта на том же часу за 30 дней.</p><p>Посты с выраженной аномалией не входят ни в норму, ни в выдачу.</p><p><Link href="/methodology/findings" className="underline underline-offset-4">Подробнее о методике</Link></p></MethodNote>}
      description="Посты, которые сработали лучше обычного для своего аккаунта."
      meta={page ? <span className="text-muted-foreground text-xs" title={`${formatDate(page.asOf)} · datasetRevision ${page.datasetRevision}`}>Обновлено {updated}</span> : null}
    />
    {!anomaliesVisible ? <Alert className="mb-4"><AlertDescription>Проверка аномалий временно недоступна — посты не отфильтрованы.</AlertDescription></Alert> : null}

    <FindingsFilterForm key={selectionKey} id="findings-filters" action="/statistics" method="get" aria-label="Фильтры находок"
      data-testid="filter-toolbar" className={`mb-6 flex flex-wrap items-center gap-2 p-2.5 ${STICKY_CONTROL_SURFACE_CLASS}`}>
      <NativeSegments name="mode" legend="Режим" value={institutionMode ? "institution" : "all"} options={MODE_OPTIONS} labelled={false} />
      {institutionMode ? <InstitutionPicker institutions={institutions} value={query.institution} /> : null}
      <NativeSegments name="platform" legend="Площадка" value={query.platform} options={FILTER_PLATFORM_OPTIONS} labelled={false} />
      <NativeSegments name="period" legend="Период" value={query.period} options={FINDINGS_PERIOD_OPTIONS} labelled={false} />
      <NativeSelect name="sort" defaultValue={query.sort} aria-label="Сортировка" className={`${FILTER_SELECT_CLASS} w-auto`}>
        {FINDINGS_SORT_OPTIONS.map(([value, label]) => <NativeSelectOption key={value} value={value}>{label}</NativeSelectOption>)}
      </NativeSelect>
      <NativeSelect name="direction" defaultValue={query.direction} aria-label="Направление сортировки" className={`${FILTER_SELECT_CLASS} w-auto`}>
        <NativeSelectOption value="desc">По убыванию</NativeSelectOption><NativeSelectOption value="asc">По возрастанию</NativeSelectOption>
      </NativeSelect>
      <TypesPopover value={query.types} group={query.group} groupAvailable={!institutionMode} />
      <InputGroup className="h-8 min-w-48 flex-1">
        <InputGroupAddon><Search className="size-4" aria-hidden="true" /></InputGroupAddon>
        <InputGroupInput name="q" type="search" defaultValue={query.q} maxLength={200} placeholder="Номер, URL или аккаунт" aria-label="Поиск публикаций" className="text-sm md:text-sm" />
        <InputGroupAddon align="inline-end">
          {query.q ? <InputGroupButton size="icon-sm" className="size-6" nativeButton={false} aria-label="Очистить поиск"
            render={<Link role="link" href={queryHref("/statistics", { ...findingsHrefQuery(query), q: undefined })} prefetch={false} />}><X className="size-3.5" aria-hidden="true" /></InputGroupButton> : null}
          <InputGroupButton type="submit" variant="secondary" size="icon-sm" className="size-6" aria-label="Применить фильтры"><ArrowRight className="size-3.5" aria-hidden="true" /></InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
    </FindingsFilterForm>

    <NavigationBoundary fallback={<StatisticsSkeleton chrome={false} />}>
      {failed ? <ApiFailureState retryHref={queryHref("/statistics", findingsHrefQuery(query))} />
        : choosing || unknownInstitution || !page ? <Empty role="status" className="bg-card border py-10"><EmptyHeader><EmptyTitle><h2 className="font-heading text-lg font-semibold">{unknownInstitution ? "Вуз не найден — выберите другой" : "Выберите вуз, чтобы увидеть его посты"}</h2></EmptyTitle></EmptyHeader></Empty>
        : <FindingsResults key={selectionKey} page={page} query={query} anomaliesVisible={anomaliesVisible} />}
    </NavigationBoundary>
  </>;
}
```

`redirect()` из `next/navigation` прерывает рендер собственным исключением. В коде выше он вызывается внутри `catch`, и это исключение уходит наружу — так и должно быть; не оборачивать этот вызов в ещё один `try`.

Если `ApiError` не экспортируется из `@/lib/api` под этим именем — взять имя из `app/accounts/[id]/page.tsx` (там `import { api, ApiError } from "@/lib/api"`).

- [ ] **Step 7: Заготовка и удаление старых компонентов**

В `frontend/components/skeletons.tsx` у `StatisticsSkeleton` убрать проп `view` (и ветку `view === "publications"` — квадрат оставить всегда), заголовок `Chrome` заменить на `title="Находки: посты выше нормы"` и `description="Посты, которые сработали лучше обычного для своего аккаунта."`. Текст `Загрузка статистики` не менять: на него опирается `tests/browser/navigation.spec.ts`.

```bash
git rm frontend/components/statistics-results.tsx frontend/components/statistics-filter-form.tsx
```

- [ ] **Step 8: Проверки**

Run: `cd frontend && pnpm lint && pnpm typecheck && pnpm test`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add frontend
git commit -m "feat(findings): /statistics page with modes, grouping and filters"
```

---

### Task 9: Тестовый API-двойник и браузерные тесты

**Files:**
- Modify: `frontend/tests/api-fixture.mts` (обработчик `/api/v1/findings`, строки около 325–335 для старого `/api/v1/statistics` оставить)
- Modify: `frontend/tests/browser/parity.spec.ts:103-185,367-381`
- Modify: `frontend/tests/browser/redesign.spec.ts:52`

**Interfaces:**
- Consumes: схемы `Findings`, `Finding`, `FindingGroup`, `FindingInstitution` из `../../contracts/openapi/m-ranked-v1-client`.

- [ ] **Step 1: Двойник API**

В `frontend/tests/api-fixture.mts` рядом с `statisticsPublication` добавить:

```ts
function finding(id: number, platform: "telegram" | "vk" | "max" | "rutube", institution = 1): Schema["Finding"] {
  return {
    publicationId: uuid(5, id), institutionId: uuid(9, institution), institutionLegacyId: institution,
    institutionShortName: `Вуз ${String(institution).padStart(3, "0")}`,
    institutionCanonicalName: `Полное название университета ${String(institution).padStart(3, "0")}`,
    accountId: uuid(1, institution), platform, publicationType: id % 3 === 0 ? "video" : "photo",
    externalId: String(id), publicUrl: `https://example.test/${id}`, publishedAt: asOf,
    ageHours: id === 2 ? 6 : 24, preliminary: id === 2, interactionIndex: id === 4 ? null : 5 - id / 20,
    viewIndex: 1.5, interactionNorm: 20, viewNorm: 1000, normSampleSize: 12,
    interactions: id === 3 ? 0 : 100 - id, reactions: 80, comments: platform === "max" ? null : 15,
    shares: platform === "vk" ? 5 : null, views: 2000, erv: id === 3 ? 0 : 5,
    anomalyLevel: id === 5 ? 1 : id === 6 ? null : 0,
    capabilities: { reactions: true, comments: platform !== "max", shares: platform === "vk" },
  };
}
```

и обработчик перед блоком `/api/v1/statistics`:

```ts
  if (url.pathname === "/api/v1/findings") {
    const mode = url.searchParams.get("mode") ?? "all";
    const institution = Number(url.searchParams.get("institution") ?? "0") || null;
    if (mode === "institution" && institution !== 1 && institution !== 2) {
      return json(response, 404, { type: "about:blank", title: "Not Found", status: 404, detail: "вуз не найден" });
    }
    const platform = (url.searchParams.get("platform") ?? "all") as Schema["Findings"]["platform"];
    const empty = url.searchParams.get("q") === "missing";
    const group = (url.searchParams.get("group") ?? "none") as Schema["Findings"]["group"];
    const rowPlatform = platform === "all" ? "vk" : platform;
    const items = empty ? [] : Array.from({ length: 30 }, (_, index) => finding(index + 1, rowPlatform, mode === "institution" ? institution! : (index % 2) + 1));
    const body: Schema["Findings"] = {
      mode: mode as Schema["Findings"]["mode"], institution, platform,
      period: (url.searchParams.get("period") ?? "7d") as Schema["Findings"]["period"],
      types: url.searchParams.getAll("types") as Schema["Findings"]["types"],
      sort: (url.searchParams.get("sort") ?? "interaction_index") as Schema["Findings"]["sort"],
      direction: (url.searchParams.get("direction") ?? "desc") as Schema["Findings"]["direction"],
      group, q: url.searchParams.get("q") ?? "",
      anomalies: (url.searchParams.get("anomalies") ?? "exclude") as Schema["Findings"]["anomalies"],
      items: group === "none" ? items : [],
      groups: group === "institution" && !empty ? [1, 2].map((number) => ({
        institutionLegacyId: number, institutionShortName: `Вуз ${String(number).padStart(3, "0")}`,
        institutionCanonicalName: `Полное название университета ${String(number).padStart(3, "0")}`,
        findingCount: 15, items: items.filter((item) => item.institutionLegacyId === number).slice(0, 3),
      })) : [],
      total: items.length, hiddenAnomalous: empty ? 0 : 3,
      institutions: [1, 2].map((number) => ({ legacyId: number, shortName: `Вуз ${String(number).padStart(3, "0")}`, canonicalName: `Полное название университета ${String(number).padStart(3, "0")}` })),
      limit: 50, offset: 0, hasMore: false, nextCursor: null, datasetRevision: revision, asOf,
    };
    return json(response, 200, body);
  }
```

Имя функции ответа (`json(...)`) и форму 404 взять из соседних обработчиков двойника — если там другой помощник, использовать его.

- [ ] **Step 2: Заменить браузерные тесты статистики**

В `frontend/tests/browser/parity.spec.ts` удалить три теста `statistics …` (строки 103–185) и вставить:

```ts
test("findings list shows posts above norm with one badge and hidden-anomaly note", async ({ page }, info) => {
  await page.goto("/statistics?platform=vk");
  await expect(page.getByRole("heading", { level: 1, name: "Находки: посты выше нормы" })).toBeVisible();
  const rows = info.project.name === "mobile"
    ? page.getByTestId("findings-cards").locator("article")
    : page.getByTestId("findings-table").locator("tbody tr");
  await expect(rows).toHaveCount(20);
  await expect(rows.first()).toContainText("Вуз 001");
  await expect(rows.first()).toContainText("×5,0");
  await expect(rows.nth(1)).toContainText("предварительно, 6 ч");
  await expect(rows.nth(3)).toContainText("—");
  await expect(rows.nth(4)).toContainText("слабый сигнал");
  await expect(page.getByTestId("findings-hidden-note")).toContainText("3");
  await page.getByRole("button", { name: "Показать ещё" }).click();
  await expect(rows).toHaveCount(30);
});

test("findings restores URL state and searches", async ({ page }) => {
  await page.goto("/statistics?platform=vk&period=30d&sort=views24&direction=asc&q=alpha");
  await expect(page.locator('input[name="period"][value="30d"]')).toBeChecked();
  await expect(page.locator('select[name="sort"]')).toHaveValue("views24");
  await expect(page.locator('select[name="direction"]')).toHaveValue("asc");
  await expect(page.locator('input[name="q"]')).toHaveValue("alpha");
  await page.locator('input[name="q"]').fill("missing");
  await page.locator('input[name="q"]').press("Enter");
  await expect(page).toHaveURL(/q=missing/);
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
  await page.goBack();
  await expect(page.locator('input[name="q"]')).toHaveValue("alpha");
});

test("findings groups by institution and links into institution mode", async ({ page }) => {
  await page.goto("/statistics?group=institution");
  const groups = page.getByTestId("findings-groups").locator("section");
  await expect(groups).toHaveCount(2);
  await expect(groups.first().getByRole("heading", { level: 2 })).toHaveText("Вуз 001");
  await groups.first().getByRole("link", { name: "Все посты вуза →" }).click();
  await expect(page).toHaveURL(/mode=institution/);
  await expect(page).toHaveURL(/institution=1/);
  await expect(page.getByRole("combobox", { name: "Вуз" })).toHaveValue("Вуз 001");
});

test("institution mode without a choice asks for one and unknown id is not an error", async ({ page }) => {
  await page.goto("/statistics?mode=institution");
  await expect(page.getByText("Выберите вуз, чтобы увидеть его посты")).toBeVisible();
  await page.getByRole("combobox", { name: "Вуз" }).fill("002");
  await page.getByRole("option", { name: /Вуз 002/ }).click();
  await expect(page).toHaveURL(/institution=2/);
  await page.goto("/statistics?mode=institution&institution=999");
  await expect(page.getByText("Вуз не найден — выберите другой")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Вуз" })).toBeVisible();
});

test("findings filters popover applies publication types", async ({ page }) => {
  await page.goto("/statistics");
  await page.getByRole("button", { name: /Фильтры/ }).click();
  await page.getByRole("checkbox", { name: "Видео" }).check();
  await expect(page).toHaveURL(/types=video/);
  await expect(page.getByRole("button", { name: /Фильтры · 1/ })).toBeVisible();
});
```

В тесте `overview and statistics keep desktop filters within two rows…` (строки 367–381) оставить `/statistics?platform=telegram` в списке путей; селектор дочерних элементов панели заменить на `":scope > :not(input[type=hidden]):not([role=status])"` — он уже такой. Если на десктопе 1440 px панель «Находок» занимает больше двух рядов, сократить подписи сортировки, а не ослаблять проверку.

В `frontend/tests/browser/redesign.spec.ts:52` заменить `"/statistics?platform=telegram&view=entities"` на `"/statistics?group=institution"`.

- [ ] **Step 3: Run browser tests**

Run: `cd frontend && pnpm test:e2e`
Expected: PASS (desktop и mobile; включая axe AA в светлой и тёмной теме для `/statistics?platform=telegram` и отсутствие горизонтальной прокрутки на 375/390/430 px).

- [ ] **Step 4: Commit**

```bash
git add frontend/tests
git commit -m "test(findings): contract double and browser coverage"
```

---

### Task 10: Методология

**Files:**
- Create: `frontend/content/methodology/findings.mdx`
- Modify: `frontend/lib/methodology.ts` (запись в `ARTICLES` после `comparison`)

- [ ] **Step 1: Статья**

`frontend/lib/methodology.ts` — после строки `comparison`:

```ts
  { slug: "findings", title: "Находки: индекс к норме", description: "Как пост сравнивается с типичным постом своего аккаунта и почему часть постов скрыта." },
```

`frontend/content/methodology/findings.mdx`:

```mdx
## Что показывает страница

«Находки» — посты, которые сработали лучше обычного для своего аккаунта. Пост
сравнивается не с другими вузами, а с самим аккаунтом: так маленький канал с
удачным постом стоит рядом с крупным, а не теряется под ним. Сравнение вузов
между собой — на странице [сравнения](/compare).

## Индекс к норме

Индекс = взаимодействия поста на возрасте h ÷ норма аккаунта на возрасте h.

- **Возраст h** — 24 часа. У поста моложе суток берётся последний замер
  (12, 6, 3 или 1 час), и индекс помечается «предварительно».
- **Взаимодействия** — реакции, комментарии и репосты, которые отдаёт
  площадка: в MAX это только реакции, в Telegram и RuTube — реакции и
  комментарии, во ВКонтакте — все три.
- **Норма** — медиана того же показателя на том же часу по постам аккаунта
  за 30 дней. Нужно не меньше 10 таких постов; иначе индекса нет.
- Норма не бывает меньше 5 взаимодействий и 50 просмотров: на маленьких числах
  случайный пост иначе выглядел бы «впятеро лучше».

В общей ленте — посты с индексом от 1,5 и не меньше 10 взаимодействиями. В
режиме «Мой вуз» показываются все посты вуза.

## Почему часть постов скрыта

Посты с выраженной аномалией или признаками искусственной активности (уровни 2
и 3 [анализа динамики](/methodology/analysis)) не входят ни в норму, ни в
выдачу: копировать накрученный пост бессмысленно. Слабый сигнал (уровень 1)
показывается с пометкой; пост, который ещё не проверен, — с пометкой «не
проверен».
```

- [ ] **Step 2: Проверить**

Run: `cd frontend && node --import tsx --test tests/methodology.test.ts && pnpm build`
Expected: PASS; страница `/methodology/findings` собирается.

- [ ] **Step 3: Commit**

```bash
git add frontend/content/methodology/findings.mdx frontend/lib/methodology.ts
git commit -m "docs(findings): methodology article"
```

---

### Task 11: Полная проверка и локальный просмотр

**Files:** нет новых.

- [ ] **Step 1: Все гейты**

Run: `make test-python && cd frontend && pnpm check`
Expected: PASS. Postgres-тесты без переменных окружения пропускаются — запустить их отдельно с `MRANKED_FINDINGS_TEST_DSN` и `API_READ_DB_*` (Tasks 3 и 5).

- [ ] **Step 2: Локальный API на клоне**

Run: `API_READ_DB_HOST=127.0.0.1 API_READ_DB_PORT=55433 API_READ_DB_USER=mranked_bootstrap API_READ_DB_PASSWORD=local-demo-bootstrap API_READ_DB_NAME=mranked_findings_local .venv/bin/python -m api` (в фоне; имена переменных хоста и порта сверить с `api/config.py`, переменные `API_WRITE_ADMIN_DB_*` и `OUTBOX_WORKER_DB_*` не задавать, если `Settings` их не требует).

Затем: `cd frontend && API_BASE_URL=http://127.0.0.1:<порт API из api/config.py> NEXT_PUBLIC_DATA_CACHE=disabled pnpm dev`.

- [ ] **Step 3: Просмотреть страницу на реальных данных**

Открыть во встроенном браузере `/statistics`, `/statistics?period=30d&group=institution`, `/statistics?mode=institution&institution=<legacy id из списка>`, `/statistics?platform=rutube`; проверить десктоп и ширину 375 px, светлую и тёмную тему. Записать в ответ пользователю, что видно, и скриншоты.

- [ ] **Step 4: Итог ветки**

Run: `git log --oneline main..HEAD && git status`
Expected: чистое дерево, коммиты задач 1–10. Push и PR — только по решению пользователя.
