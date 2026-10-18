"""Разбор слов /top: синонимы, раскладка, поиск вуза, неоднозначность."""
from __future__ import annotations

import difflib

import pytest

from telegram_bot.words import (
    Institution,
    TopQuery,
    from_wrong_layout,
    normalize,
    parse_top,
    split_command,
)

# Небольшой рукописный каталог; legacy_id — условные числа.
INSTITUTIONS = [
    Institution(1, "МФТИ", "Московский физико-технический институт"),
    Institution(2, "НИУ ВШЭ", "Национальный исследовательский университет «Высшая школа экономики»"),
    Institution(3, "ИТМО", "Университет ИТМО"),
    Institution(4, None, "Санкт-Петербургский государственный университет"),
    Institution(5, "РУДН", "Российский университет дружбы народов"),
    Institution(6, "РЭУ", "Российский экономический университет"),
]

# Строки таблицы «Варианты написания» из спека: (поле, значение, слова).
SYNONYM_ROWS = [
    ("platform", "telegram", ["тг", "телеграм", "телеграмм", "телега", "tg", "telegram", "tlg"]),
    ("platform", "vk", ["вк", "вконтакте", "контакт", "vk", "vkontakte"]),
    ("platform", "max", ["макс", "max", "мах"]),
    ("platform", "rutube", ["рутуб", "рутьюб", "rutube", "rt"]),
    ("platform", "all", ["все площадки"]),
    ("who", "ours", ["наши", "наш", "мы", "свои", "our"]),
    ("who", "all", ["все", "всё", "all", "другие"]),
    ("period", "1d", ["сутки", "день", "1д", "1d", "24ч", "day"]),
    ("period", "7d", ["неделя", "нед", "7д", "7d", "week", "w"]),
    ("period", "30d", ["месяц", "мес", "30д", "30d", "month", "m"]),
]

SYNONYM_CASES = [
    (field, value, word) for field, value, words in SYNONYM_ROWS for word in words
]


def _cases(word: str) -> list[str]:
    return [word, word.upper(), word.capitalize()]


@pytest.mark.parametrize(("field", "value", "word"), SYNONYM_CASES)
def test_synonyms(field: str, value: str, word: str) -> None:
    for variant in _cases(word):
        query = parse_top(variant, INSTITUTIONS)
        assert getattr(query, field) == value, variant
        assert query.unknown == (), variant
        # Остальные поля не тронуты.
        rest = TopQuery(**{field: value})
        assert query == rest, variant


def test_tg_in_three_cases() -> None:
    for variant in ("тг", "ТГ", "Tg"):
        assert parse_top(variant, []).platform == "telegram"


def test_yo_equals_e() -> None:
    assert parse_top("всё", []) == parse_top("все", [])
    assert parse_top("ВСЁ", []).who == "all"


def test_wrong_layout() -> None:
    assert parse_top("ен", []).platform == "telegram"
    assert parse_top("мл", []).platform == "vk"
    assert parse_top("ЕН", []).platform == "telegram"
    # Настоящая раскладка: «tg» в русской — «еп», «тг» в английской — «nu».
    assert parse_top("еп", []).platform == "telegram"
    assert parse_top("nu", []).platform == "telegram"
    assert parse_top("Nu", []).platform == "telegram"
    assert parse_top("ьфч", []).platform == "max"
    assert parse_top("dct", []).who == "all"


def test_from_wrong_layout_both_directions() -> None:
    assert from_wrong_layout("еп") == "tg"
    assert from_wrong_layout("tg") == "еп"
    assert from_wrong_layout("nu") == "тг"
    assert from_wrong_layout("мл") == "vk"
    assert from_wrong_layout("vk") == "мл"
    assert from_wrong_layout("Еп") == "Tg"
    assert from_wrong_layout("12") == "12"


def test_order_free() -> None:
    assert parse_top("тг все месяц", INSTITUTIONS) == parse_top("месяц все тг", INSTITUTIONS)
    query = parse_top("тг все месяц", INSTITUTIONS)
    assert (query.who, query.platform, query.period) == ("all", "telegram", "30d")


def test_all_platforms_phrase() -> None:
    query = parse_top("все площадки", INSTITUTIONS)
    assert query.platform == "all"
    assert query.who == "ours"
    assert query.unknown == ()


def test_all_platforms_phrase_with_other_words() -> None:
    query = parse_top("месяц всё площадки", INSTITUTIONS)
    assert (query.who, query.platform, query.period) == ("ours", "all", "30d")
    query = parse_top("все площадки все", INSTITUTIONS)
    assert (query.who, query.platform) == ("all", "all")


def test_all_with_platform_is_who_all() -> None:
    query = parse_top("все тг", INSTITUTIONS)
    assert (query.who, query.platform) == ("all", "telegram")


def test_count_clamped() -> None:
    assert parse_top("50", []).count == 20
    assert parse_top("0", []).count == 1
    assert parse_top("7", []).count == 7
    assert parse_top("все вк 20", []).count == 20
    assert parse_top("", []).count is None


def test_institution_by_short_and_multiword() -> None:
    query = parse_top("мфти месяц", INSTITUTIONS)
    assert (query.who, query.institution, query.period) == ("institution", 1, "30d")
    query = parse_top("ниу вшэ", INSTITUTIONS)
    assert (query.who, query.institution) == ("institution", 2)
    assert query.unknown == ()


def test_institution_with_quotes_and_case() -> None:
    assert parse_top("«МФТИ»", INSTITUTIONS).institution == 1
    assert parse_top('"Итмо" тг', INSTITUTIONS).institution == 3


def test_institution_by_full_name_and_unique_substring() -> None:
    # Полное название без короткого.
    query = parse_top("санкт-петербургский государственный университет", INSTITUTIONS)
    assert query.institution == 4
    # Уникальная подстрока.
    assert parse_top("физико", INSTITUTIONS).institution == 1
    # Подстрока в названии с кавычками.
    assert parse_top("высшая школа", INSTITUTIONS).institution == 2


def test_substring_needs_three_chars() -> None:
    query = parse_top("фи", INSTITUTIONS)
    assert query.institution is None
    assert query.unknown == ("фи",)


def test_ambiguous_institution_gives_candidates() -> None:
    # «российский» есть в названиях РУДН и РЭУ.
    query = parse_top("российский", INSTITUTIONS)
    assert query.candidates == (5, 6)
    assert len(query.candidates) == 2
    assert query.institution is None
    assert query.unknown == ()


def test_synonym_wins_over_institution_name() -> None:
    catalog = [Institution(9, "МАХ", "Какой-то институт")]
    query = parse_top("мах", catalog)
    assert query.platform == "max"
    assert query.institution is None


def test_unknown_word_is_reported() -> None:
    query = parse_top("абырвалг тг", INSTITUTIONS)
    assert query.platform == "telegram"
    assert query.unknown == ("абырвалг",)
    shorts = {normalize(i.short_name): i.short_name for i in INSTITUTIONS if i.short_name}
    expected = tuple(
        shorts[m] for m in difflib.get_close_matches("абырвалг", list(shorts), n=3, cutoff=0.75)
    )
    assert query.suggestions == expected


def test_typo_gets_suggestion() -> None:
    query = parse_top("мфит", INSTITUTIONS)
    assert query.unknown == ("мфит",)
    assert "МФТИ" in query.suggestions


def test_command_with_bot_suffix() -> None:
    assert split_command("/top@examplebot все тг") == ("top", "все тг")
    assert split_command("/top@examplebot все") == ("top", "все")


def test_split_command_variants() -> None:
    assert split_command("/top") == ("top", "")
    assert split_command("/TOP все") == ("top", "все")
    assert split_command("топ все тг") == ("top", "все тг")
    assert split_command("Топ") == ("top", "")
    assert split_command("ТОП мфти месяц") == ("top", "мфти месяц")
    assert split_command("/help@x") == ("help", "")
    assert split_command("/Week@Bot  abc") == ("week", "abc")
    assert split_command("привет") == (None, "привет")
    assert split_command("привет /top") == (None, "привет /top")
    assert split_command("  /top   все  ") == ("top", "все")
    assert split_command("") == (None, "")
    # «топор» — не команда.
    assert split_command("топор") == (None, "топор")


def test_normalize() -> None:
    assert normalize("  ЁлКа ") == "елка"
    assert normalize("«МФТИ»") == "мфти"
    assert normalize('"ВШЭ".') == "вшэ"
    assert normalize("(мфти)") == "мфти"
    assert normalize("НИУ   ВШЭ") == "ниу вшэ"
    assert normalize("“ИТМО”") == "итмо"
    assert normalize("") == ""


def test_defaults() -> None:
    assert parse_top("", []) == TopQuery()
    assert parse_top("   ", INSTITUTIONS) == TopQuery()
    query = TopQuery()
    assert (query.who, query.platform, query.period) == ("ours", "all", "7d")
    assert query.count is None and query.suspicious is False


def test_institution_overrides_all() -> None:
    query = parse_top("все мфти", INSTITUTIONS)
    assert (query.who, query.institution) == ("institution", 1)
