"""Тексты и кнопки бота. Чистые функции: ни ввода-вывода, ни часов.

Сообщения идут в режиме HTML, поэтому всё динамическое (названия, ссылки,
подписи периода) проходит через html.escape. Текста постов в API нет, строка
поста — значок площадки, место, ссылка на слове типа поста, индекс «во сколько
раз выше нормы», просмотры; вуз — только там, где вузы смешаны. Значки — через
слоты emoji.py.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .emoji import band, icon
from .words import TopQuery

if TYPE_CHECKING:  # cover импортирует render: во время работы — только аннотации
    from .cover import CoverData

TELEGRAM_LIMIT = 4096
CAPTION_LIMIT = 1024  # подпись к картинке в Telegram
CALLBACK_PREFIX = "t|"
CALLBACK_LIMIT = 64
DEFAULT_COUNT = 3
DEFAULT_COUNT_ALL = 10
DIGEST_OTHERS_COUNT = 10
MOSCOW = ZoneInfo("Europe/Moscow")
MINUS = "−"
ELLIPSIS = "…"

PLATFORM_ORDER = ("telegram", "vk", "max", "rutube")
PLATFORM_NAMES = {"telegram": "Telegram", "vk": "ВКонтакте", "max": "MAX", "rutube": "Rutube"}
# Пять кнопок в ряд не влезали в ширину телефона («…m», «…be»): четыре площадки
# с короткими подписями, «все площадки» — когда отмечены все четыре.
PLATFORM_BUTTONS = (("telegram", "ТГ"), ("vk", "ВК"), ("max", "MAX"), ("rutube", "Рутуб"))
PUBLICATION_TYPES = {"text": "текст", "photo": "фото", "album": "альбом", "video": "видео"}
PERIOD_BUTTONS = (("1d", "Сутки"), ("7d", "Неделя"), ("30d", "Месяц"))
MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")

_WHO_CODES = {"ours": "o", "all": "a"}
_PLATFORM_CODES = {"all": "a", "telegram": "t", "vk": "v", "max": "m", "rutube": "r"}
_PERIOD_CODES = {"1d": "d", "7d": "w", "30d": "m"}
_CALLBACK_RE = re.compile(
    r"t\|(?P<who>o|a|i[1-9][0-9]{0,9})\|(?P<platform>[atvmr])\|(?P<period>[dwm])"
    r"\|(?P<count>[1-9]|1[0-9]|20)?\|(?P<suspicious>[01])"
    # Автор меню (необязателен: кнопки до замка — без него). Со знаком: от имени
    # чата (анонимный админ, канал) автор — отрицательный id чата.
    r"(?:\|(?P<author>-?[1-9][0-9]{0,18}))?",
    re.ASCII,
)
_AUTHOR_LIMIT = 10**19  # 19 цифр — с запасом больше любых id Telegram


@dataclass(frozen=True)
class Message:
    text: str  # при photo — подпись к картинке
    keyboard: list[list[dict]] | None = None
    photo: bytes | None = None  # PNG; пустое у подписи-шапки, пока обложку не нарисовали


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


# --- подпись-шапка обложки ----------------------------------------------------

def _units(text: str) -> int:
    """Длина так, как её считает Telegram: в кодовых единицах UTF-16."""
    return len(text.encode("utf-16-le")) // 2


def cover_caption(prefix: str, name: str, label: str | None) -> str:
    """«<b>Дайджест · МФТИ · 12–18 окт</b>» не длиннее CAPTION_LIMIT: длинное
    название режется с «…». Меряем уже экранированный HTML — видимый текст
    подписи после разбора разметки никогда не длиннее."""
    head = f"<b>{esc(prefix)} · "
    tail = f" · {esc(label)}</b>" if label else "</b>"
    room = CAPTION_LIMIT - _units(head) - _units(tail)
    if _units(esc(name)) <= room:
        return head + esc(name) + tail
    pieces, used = [], _units(ELLIPSIS)
    for char in name:  # html.escape меняет символы по одному
        piece = esc(char)
        if used + _units(piece) > room:
            break
        pieces.append(piece)
        used += _units(piece)
    return head + "".join(pieces).rstrip() + ELLIPSIS + tail


def text_only(messages: list[Message]) -> list[Message]:
    """Обложки нет (не нарисовалась или Telegram её не принял): подпись-шапка
    первого сообщения становится текстом и встаёт в начало следующей части,
    если влезает в одно сообщение, иначе уходит отдельной."""
    if not messages:
        return []
    caption, rest = Message(messages[0].text, messages[0].keyboard), list(messages[1:])
    if rest and rest[0].photo is None and \
            len(caption.text) + 2 + len(rest[0].text) <= TELEGRAM_LIMIT:
        return [replace(rest[0], text=f"{caption.text}\n\n{rest[0].text}"), *rest[1:]]
    return [caption, *rest]


# --- /top -------------------------------------------------------------------

def default_count(query: TopQuery) -> int:
    if query.count:
        return query.count
    return DEFAULT_COUNT_ALL if query.who == "all" else DEFAULT_COUNT


def _name(item: dict[str, Any]) -> str:
    return item.get("institutionShortName") or item.get("institutionCanonicalName") or "—"


def _rank(number: int) -> str:
    return icon(f"rank_{number}") if number <= 3 else f"{number}."


def _platform_icon(code: object) -> str:
    return icon(code) if code in PLATFORM_ORDER else esc(code or "—")


def _post_link(item: dict[str, Any]) -> str:
    """Ссылка на слове типа поста; ссылки не http(s) не рисуем — остаётся слово."""
    kind = PUBLICATION_TYPES.get(item.get("publicationType"), "пост")
    url = item.get("publicUrl")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return f'<a href="{esc(url)}">{kind}</a>'
    return kind


def _numbers(item: dict[str, Any], views: bool) -> list[str]:
    parts = []
    if item.get("interactionIndex") is not None:
        parts.append(format_index(item["interactionIndex"]))
    if views and item.get("views") is not None:
        parts.append(f"{format_count(int(item['views']))} просм.")
    if item.get("promotion"):
        parts.append(f"{icon('promo')} продвижение")
    return parts


def _own_line(number: int, item: dict[str, Any]) -> str:
    """Строка поста одного вуза: вуз — в шапке, площадка — значком."""
    head = f"{_platform_icon(item.get('platform'))} {_rank(number)} {_post_link(item)}"
    return " · ".join([head, *_numbers(item, views=True)])


def _mixed_line(number: int, item: dict[str, Any], our_id: int | None, views: bool) -> str:
    """Строка поста среди всех вузов: место, вуз, площадка значком."""
    name = f"{_rank(number)} <b>{esc(_name(item))}</b>"
    # our_id задан только там, где мы среди других (/top все); в «Других вузах» нас нет.
    if our_id is not None and item.get("institutionLegacyId") == our_id:
        name += " (мы)"
    post = f"{_platform_icon(item.get('platform'))} {_post_link(item)}"
    return " · ".join([name, post, *_numbers(item, views)])


def _mixed_list(items: list[dict[str, Any]], count: int, our_id: int | None,
                views: bool) -> list[str]:
    if not items:
        return ["Постов выше нормы за период нет."]
    lines = [_mixed_line(number, item, our_id, views) for number, item in enumerate(items[:count], 1)]
    if len(items) < count:
        lines.append(f"<i>выше нормы только {len(items)}</i>")
    return lines


def _own_list(items: list[dict[str, Any]], platform: str, count: int) -> list[str]:
    """Посты одного вуза плоским списком в порядке площадок, без подзаголовков.

    API в режиме вуза отдаёт все его посты; пост без индекса (у счёта мало
    истории для нормы) выше нормы не считается. Площадку, где у вуза постов
    нет вовсе, не рисуем, если её не просили явно; где есть, но выше нормы
    ни одного — одна строка «выше нормы постов нет».
    """
    lines: list[str] = []
    wanted = PLATFORM_ORDER if platform == "all" else (platform,)
    for code in wanted:
        present = [item for item in items if item.get("platform") == code]
        if not present and platform == "all":
            continue
        above = [item for item in present if item.get("interactionIndex") is not None]
        if not above:
            lines.append(f"{icon(code)} <i>выше нормы постов нет</i>")
            continue
        lines += [_own_line(number, item) for number, item in enumerate(above[:count], 1)]
        if len(above) < count:
            lines.append(f"{icon(code)} <i>выше нормы только {len(above)}</i>")
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
               period_label: str, author: int | None = None) -> list[Message]:
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
        lines += _mixed_list(items, count, our_id, views=True)
    else:
        lines += _own_list(items, query.platform, count)
    hidden = body.get("hiddenAnomalous") or 0
    if hidden > 0 and not query.suspicious:
        lines += ["", f"Скрыто подозрительных: {int(hidden)}"]
    return _messages("\n".join(lines), top_keyboard(query, author))


# --- кнопки и callback data -------------------------------------------------

def encode_callback(query: TopQuery, author: int | None = None) -> str:
    """`t|кто|площадка|период|сколько|подозрительные[|автор]`; автор — кто вызвал меню
    (id человека или, от имени чата, отрицательный id чата)."""
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
    if author is not None:
        if (not isinstance(author, int) or isinstance(author, bool) or author == 0
                or abs(author) >= _AUTHOR_LIMIT):
            raise ValueError("автор меню — ненулевой id Telegram")
        data += f"|{author}"
    if len(data.encode("utf-8")) > CALLBACK_LIMIT:
        raise ValueError("callback data длиннее 64 байт")
    return data


def decode_callback(data: str) -> tuple[TopQuery, int | None] | None:
    """(запрос, автор меню или None для кнопок без автора) или None для мусора."""
    match = _CALLBACK_RE.fullmatch(data) if isinstance(data, str) else None
    if match is None:
        return None
    who_code = match["who"]
    who = {"o": "ours", "a": "all"}.get(who_code, "institution")
    platform = next(key for key, code in _PLATFORM_CODES.items() if code == match["platform"])
    period = next(key for key, code in _PERIOD_CODES.items() if code == match["period"])
    query = TopQuery(
        who=who,  # type: ignore[arg-type]
        institution=int(who_code[1:]) if who == "institution" else None,
        platform=platform,  # type: ignore[arg-type]
        period=period,  # type: ignore[arg-type]
        count=int(match["count"]) if match["count"] else None,
        suspicious=match["suspicious"] == "1",
    )
    return query, int(match["author"]) if match["author"] else None


def top_keyboard(query: TopQuery, author: int | None = None) -> list[list[dict]]:
    """Кнопки под ответом: каждая даёт запрос с одним изменённым полем.
    Выбранное — «✅», остальное — «⬜» (как в «Моих уведомлениях»)."""
    base = replace(query, unknown=(), candidates=(), suggestions=())

    def button(label: str, chosen: bool, target: TopQuery) -> dict:
        return {"text": ("✅ " if chosen else "⬜ ") + label,
                "callback_data": encode_callback(target, author)}

    return [
        [button("Наши", query.who == "ours", replace(base, who="ours", institution=None)),
         button("Все вузы", query.who == "all", replace(base, who="all", institution=None))],
        # Все площадки — отмечены все четыре; нажатие оставляет одну, повторное
        # нажатие на выбранную возвращает все.
        [button(label, query.platform in ("all", code),
                replace(base, platform="all" if query.platform == code else code))
         for code, label in PLATFORM_BUTTONS],
        [button(label, query.period == code, replace(base, period=code))
         for code, label in PERIOD_BUTTONS],
        [button("Подозрительные", query.suspicious, replace(base, suspicious=not query.suspicious))],
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
    if rounded > 999:  # как на обложке: шестизначный процент — шум
        return " (>+999 %)"
    sign = "" if rounded == 0 else ("+" if percent > 0 else MINUS)
    return f" ({sign}{rounded} %)"


def plural(count: int, one: str, few: str, many: str) -> str:
    """«1 пост», «24 поста», «13 постов»."""
    tail = count % 100
    if 11 <= tail <= 14:
        return many
    return {1: one, 2: few, 3: few, 4: few}.get(count % 10, many)


def _stats_line(title: str, current: dict[str, int], previous: dict[str, int] | None,
                have_previous: bool) -> str:
    """Строка недели: «<значок> <b>77,9 тыс.</b> просм. (+12 %) · 24 поста · 868 реакций»."""
    def change(key: str) -> str:
        return _change(current[key], (previous or {}).get(key, 0) if have_previous else None)

    posts, reactions = current["posts"], current["reactions"]
    return (f"{title} <b>{format_count(current['views'])}</b> просм.{change('views')} · "
            f"{posts} {plural(posts, 'пост', 'поста', 'постов')}{change('posts')} · "
            f"{format_count(reactions)} {plural(reactions, 'реакция', 'реакции', 'реакций')}"
            f"{change('reactions')}")


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


def _week_stats(current: dict, previous: dict | None) -> list[str]:
    lines = []
    empty = {"posts": 0, "views": 0, "reactions": 0}
    codes = [code for code in PLATFORM_ORDER if code in current or code in (previous or {})]
    if not codes:
        lines.append("Данных за неделю пока нет.")
    totals = [dict(empty), dict(empty)]
    for code in codes:
        now, before = {**empty, **current.get(code, {})}, {**empty, **(previous or {}).get(code, {})}
        lines.append(_stats_line(icon(code), now, before, previous is not None))
        for key in empty:
            totals[0][key] += now[key]
            totals[1][key] += before[key]
    if len(codes) > 1:
        lines.append(_stats_line("<b>Всего:</b>", totals[0], totals[1], previous is not None))
    if previous is None:
        lines.append("<i>Первая неделя наблюдений: сравнение появится через неделю.</i>")
    return lines


def week_label(body: dict[str, Any]) -> str | None:
    """Подпись недели по `asOf` ответа API («10–16 окт»); нет даты — None."""
    try:
        return period_label("7d", datetime.fromisoformat(body["asOf"]))
    except (KeyError, TypeError, ValueError):
        return None


def _with_cover(caption: str | None, body: list[str]) -> list[Message]:
    """Без обложки — текст как есть; с обложкой первое сообщение — подпись-шапка
    (картинку подставит вызывающий), тело — следующими, без повтора шапки."""
    if caption is None:
        return _messages("\n".join(body))
    return [Message(caption), *_messages("\n".join(body[1:]).lstrip("\n"))]


def render_week(current: dict, previous: dict | None, forecast: dict | None,
                our_id: int, *, cover: CoverData | None = None,
                label: str | None = None) -> list[Message]:
    # Первая строка — шапка; с обложкой её несёт подпись, в тексте она не повторяется.
    lines = ["<b>Неделя к неделе</b>", "", band("band_week", "НЕДЕЛЯ"),
             *_week_stats(current, previous)]
    forecast_line = _forecast_line(forecast, our_id)
    if forecast_line:
        lines += ["", band("band_forecast", "ПРОГНОЗ"), esc(forecast_line)]
    caption = None if cover is None else cover_caption("Неделя к неделе", cover.title, label)
    return _with_cover(caption, lines)


def render_digest(ours: dict, others: dict, current: dict, previous: dict | None,
                  forecast: dict | None, our_id: int, *,
                  cover: CoverData | None = None, name: str | None = None) -> list[Message]:
    """`name` — короткое имя нашего вуза: без обложки оно в заголовке текста
    («Дайджест · вуз · неделя»); с обложкой его несёт подпись (cover.title)."""
    label = week_label(ours)
    foreign = [item for item in others.get("items") or []
               if item.get("institutionLegacyId") != our_id]
    head = " · ".join(esc(part) for part in (name, label) if part) or "за неделю"
    lines = [f"<b>Дайджест · {head}</b>",
             "", band("band_ours", "НАШИ ЛУЧШИЕ"),
             *_own_list(list(ours.get("items") or []), "all", DEFAULT_COUNT),
             "", band("band_others", "ДРУГИЕ ВУЗЫ"),
             *_mixed_list(foreign, DIGEST_OTHERS_COUNT, None, views=False),
             "", band("band_week", "НЕДЕЛЯ"), *_week_stats(current, previous)]
    forecast_line = _forecast_line(forecast, our_id)
    if forecast_line:
        lines += ["", band("band_forecast", "ПРОГНОЗ"), esc(forecast_line)]
    caption = None if cover is None else cover_caption("Дайджест", cover.title, label)
    return _with_cover(caption, lines)


# --- /help ------------------------------------------------------------------

def render_help(*, alerts: bool, admin: bool) -> str:
    """HTML в стиле дайджеста. Весь текст постоянный, динамического нет —
    экранировать нечего (литералов <, > и & в нём нет)."""
    lines = [
        f"{icon('logo')} <b>m-ranked · что умеет бот</b>",
        "",
        band("band_ours", "ПОСТЫ"),
        "<b>/top</b> — лучшие посты. Слова в любом порядке, все необязательны:",
        "• кто: наши (по умолч.) · все · название вуза (например, мфти)",
        f"• площадка: {icon('telegram')} тг · {icon('vk')} вк · {icon('max')} макс"
        f" · {icon('rutube')} рутуб"
        " (можно и tg, telegram, vk, max, rutube — регистр не важен)",
        "• период: сутки · неделя (по умолч.) · месяц",
        "• сколько: число до 20",
        "Примеры: <code>/top</code> · <code>/top все тг</code> · "
        "<code>/top мфти месяц</code> · <code>/top все вк 20</code>",
        "",
        band("band_week", "НЕДЕЛЯ"),
        "<b>/week</b> — неделя к неделе и прогноз места в М-Рейтинге",
        "<b>/digest</b> — дайджест прямо сейчас",
    ]
    if alerts or admin:
        lines += ["", band("alert_urgent", "СЕРВЕР")]
        if alerts:
            lines.append("<b>/status</b> — главные проверки сервера и сбора")
        if admin:
            lines.append("<b>/settings</b> — наш вуз, чат, люди и подписки (только в личке)")
            lines.append("<b>/emoji</b> — id кастомных эмодзи: пришлите их вместе с командой")
    lines += ["", "<b>/id</b> — ваш Telegram ID (нужен админу, чтобы добавить вас)"]
    return "\n".join(lines)
