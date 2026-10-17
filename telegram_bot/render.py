"""Тексты и кнопки бота. Чистые функции: ни ввода-вывода, ни часов.

Сообщения идут в режиме HTML, поэтому всё динамическое (названия, ссылки,
подписи периода) проходит через html.escape. Текста постов в API нет, строка
поста — вуз, площадка и тип, ссылка, индекс «во сколько раз выше нормы»,
просмотры.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .words import TopQuery

TELEGRAM_LIMIT = 4096
CALLBACK_PREFIX = "t|"
CALLBACK_LIMIT = 64
DEFAULT_COUNT = 3
DEFAULT_COUNT_ALL = 10
DIGEST_OTHERS_COUNT = 10
MOSCOW = ZoneInfo("Europe/Moscow")
MINUS = "−"

PLATFORM_ORDER = ("telegram", "vk", "max", "rutube")
PLATFORM_NAMES = {"telegram": "Telegram", "vk": "ВКонтакте", "max": "MAX", "rutube": "Rutube"}
PLATFORM_BUTTONS = (("all", "Все"), ("telegram", "Telegram"), ("vk", "ВК"),
                    ("max", "MAX"), ("rutube", "Rutube"))
PUBLICATION_TYPES = {"text": "текст", "photo": "фото", "album": "альбом", "video": "видео"}
PERIOD_BUTTONS = (("1d", "Сутки"), ("7d", "Неделя"), ("30d", "Месяц"))
MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")

_WHO_CODES = {"ours": "o", "all": "a"}
_PLATFORM_CODES = {"all": "a", "telegram": "t", "vk": "v", "max": "m", "rutube": "r"}
_PERIOD_CODES = {"1d": "d", "7d": "w", "30d": "m"}
_CALLBACK_RE = re.compile(
    r"t\|(?P<who>o|a|i[1-9][0-9]{0,9})\|(?P<platform>[atvmr])\|(?P<period>[dwm])"
    r"\|(?P<count>[1-9]|1[0-9]|20)?\|(?P<suspicious>[01])",
    re.ASCII,
)


@dataclass(frozen=True)
class Message:
    text: str
    keyboard: list[list[dict]] | None = None


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


# --- числа и даты -----------------------------------------------------------

def _comma(value: Decimal) -> str:
    return str(value).replace(".", ",")


def _decimal_comma(value: float | Decimal) -> str:
    return _comma(Decimal(str(value)).quantize(Decimal("0.1"), ROUND_HALF_UP))


def format_index(value: object) -> str:
    return "×" + _decimal_comma(float(value))


def format_count(value: int) -> str:
    """До 1000 как есть, тысячи «9,2 тыс.», миллионы «1,3 млн»."""
    if value < 1000:
        return str(value)
    thousands = (Decimal(value) / 1000).quantize(Decimal("0.1"), ROUND_HALF_UP)
    if thousands < 1000:
        return f"{_comma(thousands)} тыс."
    return f"{_comma((Decimal(value) / 1_000_000).quantize(Decimal('0.1'), ROUND_HALF_UP))} млн"


def _day(moment: datetime) -> str:
    return f"{moment.day} {MONTHS[moment.month - 1]}"


def period_label(period: str, as_of: datetime) -> str:
    """«сутки до 16 окт» / «10–16 окт» / «17 сен – 16 окт»; дата — по Москве."""
    end = as_of.astimezone(MOSCOW) if as_of.tzinfo else as_of
    if period == "1d":
        return f"сутки до {_day(end)}"
    start = end - timedelta(days=6 if period == "7d" else 29)
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{_day(end)}"
    return f"{_day(start)} – {_day(end)}"


# --- разбиение длинного текста ---------------------------------------------

def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Режет по строкам; строка длиннее лимита режется жёстко (в наших текстах
    такого нет, но Telegram отверг бы всё сообщение)."""
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:limit])
            line = line[limit:]
        if current and len(current) + 1 + len(line) <= limit:
            current += "\n" + line
        else:
            if current:
                parts.append(current)
            current = line
    parts.append(current)
    return parts


def _messages(text: str, keyboard: list[list[dict]] | None = None) -> list[Message]:
    # Кнопки правят одно сообщение, поэтому они на последней части.
    parts = split_message(text)
    return [Message(part, keyboard if index == len(parts) - 1 else None)
            for index, part in enumerate(parts)]


# --- /top -------------------------------------------------------------------

def default_count(query: TopQuery) -> int:
    if query.count:
        return query.count
    return DEFAULT_COUNT_ALL if query.who == "all" else DEFAULT_COUNT


def _name(item: dict[str, Any]) -> str:
    return item.get("institutionShortName") or item.get("institutionCanonicalName") or "—"


def _line(number: int, item: dict[str, Any], our_id: int | None) -> str:
    parts = [f"{number}. <b>{esc(_name(item))}</b>"]
    # our_id задан только там, где вузы смешаны (/top все): в своих выборках метка лишняя.
    if our_id is not None and item.get("institutionLegacyId") == our_id:
        parts[0] += " (мы)"
    platform = PLATFORM_NAMES.get(item.get("platform"), esc(item.get("platform") or "—"))
    kind = PUBLICATION_TYPES.get(item.get("publicationType"), "пост")
    parts.append(f"{platform}, {kind}")
    url = item.get("publicUrl")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        parts.append(f'<a href="{esc(url)}">ссылка</a>')
    if item.get("interactionIndex") is not None:
        parts.append(format_index(item["interactionIndex"]))
    if item.get("views") is not None:
        parts.append(f"{format_count(int(item['views']))} просм.")
    if item.get("promotion"):
        parts.append("📣 продвижение")
    return " · ".join(parts)


def _section(title: str | None, items: list[dict[str, Any]], count: int,
             our_id: int | None) -> list[str]:
    lines = [f"<b>{esc(title)}</b>"] if title else []
    lines += [_line(number, item, our_id) for number, item in enumerate(items[:count], 1)]
    if len(items) < count:
        lines.append(f"<i>выше нормы только {len(items)}</i>" if items
                     else "<i>выше нормы постов нет</i>")
    return lines


def _platform_sections(items: list[dict[str, Any]], platform: str, count: int,
                       our_id: int | None) -> list[str]:
    """Секции по площадкам; пустые площадки не рисуем, если не просили их явно."""
    lines: list[str] = []
    wanted = PLATFORM_ORDER if platform == "all" else (platform,)
    for code in wanted:
        chosen = [item for item in items if item.get("platform") == code]
        if chosen or platform != "all":
            lines += ([""] if lines else []) + _section(PLATFORM_NAMES[code], chosen, count, our_id)
    return lines or ["Постов выше нормы за период нет."]


def _institution_title(query: TopQuery, body: dict[str, Any]) -> str:
    for entry in body.get("institutions") or []:
        if entry.get("legacyId") == query.institution:
            return entry.get("shortName") or entry.get("canonicalName") or "вуз"
    for item in body.get("items") or []:
        if item.get("institutionLegacyId") == query.institution:
            return _name(item)
    return f"вуз №{query.institution}"


def render_top(query: TopQuery, body: dict[str, Any], our_id: int | None,
               period_label: str) -> list[Message]:
    items = list(body.get("items") or [])
    count = default_count(query)
    scope = "" if query.platform == "all" else f" · {PLATFORM_NAMES[query.platform]}"
    if query.who == "all":
        title = f"Лучшие посты всех вузов{scope}"
    elif query.who == "ours":
        title = f"Наши лучшие посты{scope}"
    else:
        title = f"Лучшие посты: {_institution_title(query, body)}{scope}"
    lines = []
    if query.unknown:
        lines.append(f"не понял: {esc(', '.join(query.unknown))} — подсказка в /help")
    lines.append(f"<b>{esc(title)} · {esc(period_label)}</b>")
    if query.suspicious:
        lines.append("<i>Включая подозрительные посты.</i>")
    lines.append("")
    if query.who == "all":
        lines += _section(None, items, count, our_id) if items else ["Постов выше нормы за период нет."]
    else:
        lines += _platform_sections(items, query.platform, count, None)
    hidden = body.get("hiddenAnomalous") or 0
    if hidden > 0 and not query.suspicious:
        lines += ["", f"Скрыто подозрительных: {int(hidden)}"]
    return _messages("\n".join(lines), top_keyboard(query))


# --- кнопки и callback data -------------------------------------------------

def encode_callback(query: TopQuery) -> str:
    if query.who == "institution":
        if query.institution is None:
            raise ValueError("для вуза нужен legacy id")
        who = f"i{query.institution}"
    else:
        who = _WHO_CODES[query.who]
    data = "|".join((
        "t", who, _PLATFORM_CODES[query.platform], _PERIOD_CODES[query.period],
        "" if query.count is None else str(query.count), "1" if query.suspicious else "0",
    ))
    if len(data.encode()) > CALLBACK_LIMIT:
        raise ValueError("callback data длиннее 64 байт")
    return data


def decode_callback(data: str) -> TopQuery | None:
    match = _CALLBACK_RE.fullmatch(data) if isinstance(data, str) else None
    if match is None:
        return None
    who_code = match["who"]
    who = {"o": "ours", "a": "all"}.get(who_code, "institution")
    platform = next(key for key, code in _PLATFORM_CODES.items() if code == match["platform"])
    period = next(key for key, code in _PERIOD_CODES.items() if code == match["period"])
    return TopQuery(
        who=who,  # type: ignore[arg-type]
        institution=int(who_code[1:]) if who == "institution" else None,
        platform=platform,  # type: ignore[arg-type]
        period=period,  # type: ignore[arg-type]
        count=int(match["count"]) if match["count"] else None,
        suspicious=match["suspicious"] == "1",
    )


def top_keyboard(query: TopQuery) -> list[list[dict]]:
    """Кнопки под ответом: каждая даёт запрос с одним изменённым полем."""
    base = replace(query, unknown=(), candidates=(), suggestions=())

    def button(label: str, chosen: bool, target: TopQuery) -> dict:
        return {"text": ("✓ " if chosen else "") + label, "callback_data": encode_callback(target)}

    return [
        [button("Наши", query.who == "ours", replace(base, who="ours", institution=None)),
         button("Все вузы", query.who == "all", replace(base, who="all", institution=None))],
        [button(label, query.platform == code, replace(base, platform=code))
         for code, label in PLATFORM_BUTTONS],
        [button(label, query.period == code, replace(base, period=code))
         for code, label in PERIOD_BUTTONS],
        [button("Показать подозрительные", False, replace(base, suspicious=True))
         if not query.suspicious else
         button("Подозрительные показаны", True, replace(base, suspicious=False))],
    ]


# --- /week и дайджест -------------------------------------------------------

def our_week_stats(dashboard: dict[str, Any], our_id: int) -> dict[str, dict[str, int]]:
    """Наши показатели по площадкам из compare/dashboard (legacyId → institutionId)."""
    ours = next((str(entry["institutionId"]) for entry in dashboard.get("institutions") or []
                 if entry.get("legacyId") == our_id), None)
    if ours is None:
        return {}
    return {
        row["platform"]: {"posts": row.get("posts") or 0, "views": row.get("viewsTotal") or 0,
                          "reactions": row.get("reactionsTotal") or 0}
        for row in dashboard.get("stats") or [] if str(row.get("institutionId")) == ours
    }


def _change(current: int, previous: int | None) -> str:
    if previous is None:
        return ""
    if previous == 0:
        return "" if current == 0 else " (раньше 0)"
    percent = (current - previous) * 100 / previous
    rounded = int(abs(percent) + 0.5)
    sign = "" if rounded == 0 else ("+" if percent > 0 else MINUS)
    return f" ({sign}{rounded} %)"


def _stats_line(title: str, current: dict[str, int], previous: dict[str, int] | None,
                have_previous: bool) -> str:
    def part(label: str, key: str, formatter) -> str:
        change = _change(current[key], (previous or {}).get(key, 0) if have_previous else None)
        return f"{label} {formatter(current[key])}{change}"

    return (f"{esc(title)}: {part('постов', 'posts', str)}, "
            f"{part('просмотров', 'views', format_count)}, "
            f"{part('реакций', 'reactions', format_count)}")


def _forecast_line(forecast: dict[str, Any] | None, our_id: int) -> str | None:
    if not forecast:
        return None
    row = next((r for r in forecast.get("rows") or [] if r.get("legacyId") == our_id), None)
    try:
        rank = round(float(row["categories"]["social"]["rank"]))
    except (TypeError, KeyError, ValueError):
        return None
    line = f"Прогноз места в М-Рейтинге (соцсети): ≈{rank}-е"
    error = (forecast.get("errors") or {}).get("social")
    if isinstance(error, (int, float)):
        line += f" ± {int(error) if float(error).is_integer() else _decimal_comma(error)}"
    if forecast.get("early"):
        line += " — ранний прогноз, месяц только начался"
    return line


def _week_lines(current: dict, previous: dict | None, forecast: dict | None,
                our_id: int) -> list[str]:
    lines = ["<b>Неделя к неделе</b>"]
    empty = {"posts": 0, "views": 0, "reactions": 0}
    codes = [code for code in PLATFORM_ORDER if code in current or code in (previous or {})]
    if not codes:
        lines.append("Данных за неделю пока нет.")
    totals = [dict(empty), dict(empty)]
    for code in codes:
        now, before = {**empty, **current.get(code, {})}, {**empty, **(previous or {}).get(code, {})}
        lines.append(_stats_line(PLATFORM_NAMES[code], now, before, previous is not None))
        for key in empty:
            totals[0][key] += now[key]
            totals[1][key] += before[key]
    if len(codes) > 1:
        lines.append(_stats_line("Всего", totals[0], totals[1], previous is not None))
    if previous is None:
        lines.append("<i>Первая неделя наблюдений: сравнение появится через неделю.</i>")
    forecast_line = _forecast_line(forecast, our_id)
    if forecast_line:
        lines += ["", esc(forecast_line)]
    return lines


def render_week(current: dict, previous: dict | None, forecast: dict | None,
                our_id: int) -> Message:
    return Message("\n".join(_week_lines(current, previous, forecast, our_id)))


def render_digest(ours: dict, others: dict, current: dict, previous: dict | None,
                  forecast: dict | None, our_id: int) -> list[Message]:
    label = "за неделю"
    try:
        label = period_label("7d", datetime.fromisoformat(ours["asOf"]))
    except (KeyError, TypeError, ValueError):
        pass
    foreign = [item for item in others.get("items") or []
               if item.get("institutionLegacyId") != our_id]
    lines = [f"<b>Дайджест · {esc(label)}</b>", "", "<b>Наши лучшие посты</b>",
             *_platform_sections(list(ours.get("items") or []), "all", DEFAULT_COUNT, None),
             "", "<b>Лучшие у других вузов</b>",
             *(_section(None, foreign, DIGEST_OTHERS_COUNT, None)
               if foreign else ["Постов выше нормы за период нет."]),
             "", *_week_lines(current, previous, forecast, our_id)]
    return _messages("\n".join(lines))


# --- /help ------------------------------------------------------------------

def render_help(*, alerts: bool, admin: bool) -> str:
    lines = [
        "/top — лучшие посты. Слова в любом порядке, все необязательны:",
        "  кто: наши (по умолч.) · все · название вуза (мфти)",
        "  площадка: тг · вк · макс · рутуб (можно tg, telegram, vk…)",
        "  период: сутки · неделя (по умолч.) · месяц",
        "  сколько: число до 20",
        "  Примеры: /top · /top все тг · /top мфти месяц · /top все вк 20",
        "/week — неделя к неделе и прогноз места в М-Рейтинге",
        "/digest — дайджест прямо сейчас",
        "/id — ваш Telegram ID (нужен админу, чтобы добавить вас)",
    ]
    if alerts:
        lines.append("/status — главные проверки сервера и сбора")
    if admin:
        lines.append("/settings — наш вуз, чат, люди и подписки (только в личке)")
    return "\n".join(lines)  # ни одного <, > и & — экранировать нечего
