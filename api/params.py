"""Нормализация параметров публичных запросов.

Прежний HTML трактовал неподдерживаемую сортировку как запрос значения по
умолчанию, а не как ошибку. Нормализация обязана происходить до построения
ключа кэша и до SQL: иначе ?sort=views и ?sort=мусор дадут одинаковый ответ,
но разные записи кэша.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import uuid
from dataclasses import dataclass

from .errors import BadRequest

PLATFORMS = ("all", "telegram", "vk", "max", "rutube")
PERIODS = ("3h", "1d", "7d", "30d")

SORTS_ALL = frozenset({"name", "m_rating", "coverage", "accounts"})
SORTS_PLATFORM = frozenset({"name", "subscribers", "posts", "views", "reactions",
                            "median_reactions", "m_rating"})

STATISTICS_VIEWS = frozenset({"publications", "entities"})
STATISTICS_PUBLICATION_SORTS = frozenset({
    "erv", "views", "reactions", "interactions", "published_at",
})
STATISTICS_ENTITY_SORTS = frozenset({
    "erv", "median_interactions", "interactions", "views", "publications",
})


def platform(value: str | None) -> str:
    resolved = value or "all"
    if resolved not in PLATFORMS:
        raise BadRequest(f"платформа должна быть одной из {', '.join(PLATFORMS)}")
    return resolved


def period(value: str | None) -> str:
    resolved = value or "1d"
    if resolved not in PERIODS:
        raise BadRequest(f"период должен быть одним из {', '.join(PERIODS)}")
    return resolved


@dataclass(frozen=True, slots=True)
class OverviewQuery:
    platform: str
    period: str
    search: str
    sort: str
    direction: str

    @property
    def all_platforms(self) -> bool:
        return self.platform == "all"


@dataclass(frozen=True, slots=True)
class StatisticsQuery:
    view: str
    platform: str
    period: str
    search: str
    publication_sort: str
    publication_direction: str
    entity_sort: str
    entity_direction: str

    @property
    def dimensions(self) -> str:
        return ":".join((self.view, self.platform, self.period, self.search,
                         self.publication_sort, self.publication_direction,
                         self.entity_sort, self.entity_direction))


def statistics_query(view_value: str | None, platform_value: str | None,
                     period_value: str | None, search_value: str | None,
                     publication_sort: str | None, publication_direction: str | None,
                     entity_sort: str | None, entity_direction: str | None) -> StatisticsQuery:
    normalized_platform = (platform_value or "all").strip().lower()
    if normalized_platform == "tg":
        normalized_platform = "telegram"
    if normalized_platform not in PLATFORMS:
        normalized_platform = "all"

    normalized_period = (period_value or "30d").strip().lower()
    if normalized_period not in PERIODS:
        normalized_period = "30d"
    text = (search_value or "").strip()
    if len(text) > 200:
        raise BadRequest("поисковый фрагмент длиннее 200 символов")
    resolved_view = view_value if view_value in STATISTICS_VIEWS else "publications"
    if normalized_platform == "all":
        resolved_view = "publications"
    return StatisticsQuery(
        resolved_view, normalized_platform, normalized_period, text,
        publication_sort if publication_sort in STATISTICS_PUBLICATION_SORTS else "erv",
        publication_direction if publication_direction in ("asc", "desc") else "desc",
        entity_sort if entity_sort in STATISTICS_ENTITY_SORTS else "erv",
        entity_direction if entity_direction in ("asc", "desc") else "desc",
    )


def overview_query(platform_value: str | None, period_value: str | None,
                   search: str | None, sort: str | None, direction: str | None) -> OverviewQuery:
    resolved_platform = platform(platform_value)
    resolved_period = period(period_value)

    text = (search or "").strip()
    if len(text) > 200:
        raise BadRequest("поисковый фрагмент длиннее 200 символов")

    supported = SORTS_ALL if resolved_platform == "all" else SORTS_PLATFORM
    fallback = "m_rating" if resolved_platform == "all" else "median_reactions"
    resolved_sort = sort if sort in supported else fallback
    resolved_direction = (direction if direction in ("asc", "desc")
                          else ("asc" if resolved_sort == "name" else "desc"))
    return OverviewQuery(resolved_platform, resolved_period, text, resolved_sort, resolved_direction)


def limit(value: int | None, default: int = 50, maximum: int = 200) -> int:
    resolved = default if value is None else value
    if not 1 <= resolved <= maximum:
        raise BadRequest(f"limit должен быть в диапазоне 1..{maximum}")
    return resolved


def cursor(value: str | None) -> str | None:
    """Курсор непрозрачен снаружи и несёт идентификатор последней карточки страницы.

    Декодирование строгое. base64 по умолчанию молча выбрасывает символы вне
    алфавита, поэтому "%%%%%%" разбирается в пустую строку и доезжает до SQL
    как пустой UUID. Здесь мусор отвергается на границе.
    """
    if value is None or value == "":
        return None
    if len(value) > 512:
        raise BadRequest("курсор длиннее 512 символов")
    try:
        decoded = base64.urlsafe_b64decode(
            (value + "=" * (-len(value) % 4)).encode("ascii"), ).decode("utf-8")
        if base64.urlsafe_b64encode(decoded.encode("utf-8")).decode("ascii").rstrip("=") != value.rstrip("="):
            raise ValueError("курсор не является каноническим base64url")
        uuid.UUID(decoded)
    except (binascii.Error, UnicodeDecodeError, UnicodeEncodeError, ValueError) as error:
        raise BadRequest("курсор повреждён") from error
    return decoded


def encode_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def entity_id(value: str) -> tuple[str | None, int | None]:
    """Разбирает совместимый идентификатор: UUID либо положительный legacy id."""
    if value.isascii() and value.isdigit() and not value.startswith("0"):
        legacy = int(value)
        if 0 < legacy <= (1 << 63) - 1:
            return None, legacy
        raise BadRequest("legacy id не помещается в int64")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise BadRequest("идентификатор должен быть UUID или положительным целым") from error
    if str(parsed) != value.lower():
        raise BadRequest("UUID должен быть записан в каноническом виде")
    return str(parsed), None


def _fingerprint(dimensions: str) -> str:
    return hashlib.sha256(dimensions.encode("utf-8")).hexdigest()


def scoped_cursor(value: str | None, revision: int, dimensions: str) -> str | None:
    """Курсор списка привязан к ревизии и нормализованным параметрам запроса."""
    if value is None or value == "":
        return None
    if len(value) > 512:
        raise BadRequest("курсор длиннее 512 символов")
    try:
        decoded_bytes = base64.b64decode(
            (value + "=" * (-len(value) % 4)).encode("ascii"), altchars=b"-_", validate=True)
        decoded = decoded_bytes.decode("ascii")
        if base64.urlsafe_b64encode(decoded_bytes).decode("ascii").rstrip("=") != value:
            raise ValueError("неканонический base64url")
        cursor_revision, fingerprint, identifier = decoded.split(":", 2)
        if int(cursor_revision) != revision or fingerprint != _fingerprint(dimensions):
            raise ValueError("курсор относится к другому набору данных")
        uuid.UUID(identifier)
    except (binascii.Error, UnicodeDecodeError, UnicodeEncodeError, ValueError) as error:
        raise BadRequest("курсор повреждён или устарел") from error
    return identifier


def encode_scoped_cursor(identifier: str | None, revision: int, dimensions: str) -> str | None:
    if identifier is None:
        return None
    value = f"{revision}:{_fingerprint(dimensions)}:{identifier}"
    return base64.urlsafe_b64encode(value.encode("ascii")).decode("ascii").rstrip("=")
