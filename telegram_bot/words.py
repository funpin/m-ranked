"""Разбор слов команды /top: синонимы, другая раскладка, поиск вуза.

Чистые функции без ввода-вывода: каталог вузов приходит параметром.
Слова распознаются без учёта регистра, ё = е. Таблицы синонимов — ровно
«Варианты написания» из спека бота (расширять можно, сужать нельзя).
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Who = Literal["ours", "all", "institution"]
Platform = Literal["all", "telegram", "vk", "max", "rutube"]
Period = Literal["1d", "7d", "30d"]

MIN_COUNT = 1
MAX_COUNT = 20
# Самое длинное название вуза, которое пользователь пишет словами через пробел.
MAX_NGRAM = 4
# Короче трёх символов подстрока совпадает с чем угодно.
MIN_SUBSTRING_LEN = 3
SUGGESTION_LIMIT = 3
SUGGESTION_CUTOFF = 0.75

# Все слова ниже уже в нормализованном виде (нижний регистр, ё → е).
PLATFORM_WORDS: dict[str, Platform] = {
    # Telegram
    "тг": "telegram", "телеграм": "telegram", "телеграмм": "telegram",
    "телега": "telegram", "tg": "telegram", "telegram": "telegram",
    "tlg": "telegram",
    # Пример из спека: «ен» (на деле «tg» в русской раскладке — «еп», это
    # разбирается через раскладку, а «ен» держим явным синонимом).
    "ен": "telegram",
    # ВКонтакте
    "вк": "vk", "вконтакте": "vk", "контакт": "vk", "vk": "vk",
    "vkontakte": "vk",
    # MAX; «мах» кириллицей — тоже MAX
    "макс": "max", "max": "max", "мах": "max",
    # Rutube
    "рутуб": "rutube", "рутьюб": "rutube", "rutube": "rutube", "rt": "rutube",
}
# «все площадки» — фраза, отдельного слова нет.
ALL_PLATFORMS_WORDS = frozenset({"площадки", "площадка"})
# Слова, значащие «все» и для вузов, и (в фразе «все площадки») для площадок.
ALL_WORDS = frozenset({"все", "all"})  # «всё» → «все» после нормализации
WHO_WORDS: dict[str, Who] = {
    # наши
    "наши": "ours", "наш": "ours", "мы": "ours", "свои": "ours", "our": "ours",
    # все вузы («все»/«all» разбираются отдельно, см. ALL_WORDS)
    "другие": "all",
}
# Кириллическое «м» намеренно не синоним месяца: слишком неоднозначно;
# латинское «m» по таблице спека — месяц.
PERIOD_WORDS: dict[str, Period] = {
    "сутки": "1d", "день": "1d", "1д": "1d", "1d": "1d", "24ч": "1d", "day": "1d",
    "неделя": "7d", "нед": "7d", "7д": "7d", "7d": "7d", "week": "7d", "w": "7d",
    "месяц": "30d", "мес": "30d", "30д": "30d", "30d": "30d", "month": "30d",
    "m": "30d",
}

_QUOTES = "«»\"'“”„"
_EDGE_CHARS = _QUOTES + ".,;:!?()[]"
_COMMAND_RE = re.compile(r"^/([A-Za-z0-9_]+)(?:@[A-Za-z0-9_]+)?$")
_COUNT_RE = re.compile(r"[0-9]+")

# Клавиши ЙЦУКЕН ↔ US QWERTY, обе раскладки по строкам клавиатуры.
_RU_KEYS = "йцукенгшщзхъфывапролджэячсмитьбюё"
_EN_KEYS = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`"
_RU_SHIFT = "ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮЁ"
_EN_SHIFT = "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>~"
_LAYOUT_MAP: dict[int, str] = {}
for _ru, _en in zip(_RU_KEYS + _RU_SHIFT, _EN_KEYS + _EN_SHIFT, strict=True):
    _LAYOUT_MAP[ord(_ru)] = _en
    _LAYOUT_MAP[ord(_en)] = _ru


@dataclass(frozen=True)
class Institution:
    legacy_id: int
    short_name: str | None
    name: str


@dataclass(frozen=True)
class TopQuery:
    who: Literal["ours", "all", "institution"] = "ours"
    institution: int | None = None
    platform: Literal["all", "telegram", "vk", "max", "rutube"] = "all"
    period: Literal["1d", "7d", "30d"] = "7d"
    count: int | None = None
    suspicious: bool = False
    # Слова, которые не поняты ни как синоним, ни как вуз.
    unknown: tuple[str, ...] = ()
    # Вузы, подошедшие под слово неоднозначно (legacy id по возрастанию).
    candidates: tuple[int, ...] = ()
    # Ближайшие по написанию короткие названия для непонятых слов.
    suggestions: tuple[str, ...] = ()


def normalize(word: str) -> str:
    """Нижний регистр, ё → е, без кавычек и знаков по краям, пробелы схлопнуты."""
    text = word.lower().replace("ё", "е")
    text = text.strip(_EDGE_CHARS + " \t\r\n")
    return " ".join(text.split())


def from_wrong_layout(word: str) -> str:
    """Слово, набранное в другой раскладке, в исходную (в обе стороны)."""
    return word.translate(_LAYOUT_MAP)


def split_command(text: str) -> tuple[str | None, str]:
    """Первая лексема → (команда, остаток); без команды → (None, текст).

    «/top», «/top@бот» и русское «топ» дают "top"; остальные слэш-команды —
    своё имя в нижнем регистре без «@суффикса».
    """
    stripped = text.strip()
    if not stripped:
        return None, text
    parts = stripped.split(None, 1)
    head = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""
    match = _COMMAND_RE.match(head)
    if match:
        return match.group(1).lower(), rest
    if head.lower() == "топ":
        return "top", rest
    return None, text


def _classify(word: str, following: str | None) -> tuple[str, str, int] | None:
    """(поле, значение, сколько слов съедено) или None, если слово не синоним."""
    if word in ALL_WORDS:
        # «все площадки» — площадка «все», иначе — «все вузы».
        if following in ALL_PLATFORMS_WORDS:
            return "platform", "all", 2
        return "who", "all", 1
    if word in PLATFORM_WORDS:
        return "platform", PLATFORM_WORDS[word], 1
    if word in WHO_WORDS:
        return "who", WHO_WORDS[word], 1
    if word in PERIOD_WORDS:
        return "period", PERIOD_WORDS[word], 1
    return None


def _index_key(text: str) -> str:
    """Ключ названия вуза: как normalize, но кавычки убраны и внутри."""
    return normalize("".join(ch for ch in text if ch not in _QUOTES))


def _find_institutions(gram: str, index: list[tuple[int, str, str]]) -> list[int]:
    """Вузы, подходящие под n-грамму: точное совпадение, иначе подстрока."""
    exact = {
        legacy_id
        for legacy_id, short_key, full_key in index
        if gram in (short_key, full_key)
    }
    if exact:
        return sorted(exact)
    if len(gram) < MIN_SUBSTRING_LEN:
        return []
    return sorted(
        {
            legacy_id
            for legacy_id, short_key, full_key in index
            if gram in short_key or gram in full_key
        }
    )


def parse_top(args: str, institutions: Sequence[Institution]) -> TopQuery:
    """Разобрать слова /top (порядок любой, все необязательны).

    Повтор слова одного вида — побеждает последнее. Слово, подходящее и под
    синоним, и под название вуза, считается синонимом (вуз «МАХ» маловероятен).
    """
    tokens = [token for token in (normalize(t) for t in args.split()) if token]

    who: Who = "ours"
    platform: Platform = "all"
    period: Period = "7d"
    count: int | None = None
    remaining: list[str] = []

    i = 0
    while i < len(tokens):
        word = tokens[i]
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if _COUNT_RE.fullmatch(word):
            count = max(MIN_COUNT, min(MAX_COUNT, int(word)))
            i += 1
            continue
        found = _classify(word, following)
        if found is None:
            # Раскладку пробуем, только если само слово ничему не отвечает.
            swapped = from_wrong_layout(word)
            if swapped != word:
                found = _classify(swapped, following)
        if found is None:
            remaining.append(word)
            i += 1
            continue
        field, value, consumed = found
        if field == "who":
            who = value  # type: ignore[assignment]
        elif field == "platform":
            platform = value  # type: ignore[assignment]
        else:
            period = value  # type: ignore[assignment]
        i += consumed

    institution_id: int | None = None
    candidates: set[int] = set()
    unknown: list[str] = []
    if remaining:
        index = [
            (
                inst.legacy_id,
                _index_key(inst.short_name) if inst.short_name else "",
                _index_key(inst.name),
            )
            for inst in institutions
        ]
        j = 0
        while j < len(remaining):
            matched: list[int] = []
            size = 0
            for size in range(min(MAX_NGRAM, len(remaining) - j), 0, -1):
                matched = _find_institutions(" ".join(remaining[j : j + size]), index)
                if matched:
                    break
            if not matched:
                unknown.append(remaining[j])
                j += 1
                continue
            if len(matched) == 1 and institution_id is None:
                institution_id = matched[0]
            elif len(matched) == 1:
                # Второй, другой вуз в одном запросе: понять нечем.
                if matched[0] != institution_id:
                    unknown.extend(remaining[j : j + size])
            else:
                candidates.update(matched)
            j += size

    suggestions: list[str] = []
    if unknown:
        shorts: dict[str, str] = {}
        for inst in institutions:
            if inst.short_name:
                shorts.setdefault(_index_key(inst.short_name), inst.short_name)
        for word in unknown:
            for close in difflib.get_close_matches(
                word, list(shorts), n=SUGGESTION_LIMIT, cutoff=SUGGESTION_CUTOFF
            ):
                if shorts[close] not in suggestions:
                    suggestions.append(shorts[close])

    if institution_id is not None:
        who = "institution"
    return TopQuery(
        who=who,
        institution=institution_id,
        platform=platform,
        period=period,
        count=count,
        unknown=tuple(unknown),
        candidates=tuple(sorted(candidates)),
        suggestions=tuple(suggestions),
    )
