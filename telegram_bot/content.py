"""Контентные уведомления: дайджест, «выстрелил», «накрутка», снимки недели.

Расписание (`due`) — чистая функция от времени и отметок последних запусков;
сами задачи отмечают свой запуск в хранилище только после успешного прохода.
Если нашего вуза нет или API недоступен, задача возвращает 0, ничего не
отмечает и повторяется на следующем тике. В журнал попадают только классы
ошибок.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .emoji import icon
from .render import (
    PLATFORM_NAMES,
    PUBLICATION_TYPES,
    Message,
    esc,
    format_count,
    format_index,
    our_week_stats,
    render_digest,
)
from .source import SourceUnavailable
from .store import OUR_INSTITUTION
from .words import TopQuery

if TYPE_CHECKING:
    from .handlers import Bot

log = logging.getLogger(__name__)

SPIKE_INDEX = 3.0
SPIKE_MAX_AGE_HOURS = 48
CHECK_EVERY_SECONDS = 900
DIGEST_WEEKDAY = 0  # понедельник
DIGEST_HOUR = 10
SNAPSHOT_HOUR = 9
MORNING_HOUR = 8

PERIOD = "7d"
SPIKE = "spike"
ANOMALY = "anomaly"
LEVEL_CONFIDENT = 2
LEVEL_EXPLICIT = 3
# Для какого «нашего вуза» уже засеяны объявленные посты (настройка на вид).
SEEDED_FOR = {SPIKE: "spike_seeded_for", ANOMALY: "anomaly_seeded_for"}


class NoOurInstitution(Exception):
    """Админ ещё не выбрал наш вуз."""


# --- расписание ---------------------------------------------------------------

def _local_day(moment: float, now: datetime) -> date:
    return datetime.fromtimestamp(moment, now.tzinfo).date()


def _digest_due(now: datetime, last: float | None) -> bool:
    if last is not None and (datetime.fromtimestamp(last, now.tzinfo).isocalendar()[:2]
                             == now.isocalendar()[:2]):
        return False  # на этой ISO-неделе уже был
    if now.weekday() == DIGEST_WEEKDAY:
        return now.hour >= DIGEST_HOUR
    # Пропущенный в понедельник догоняем один раз, но только если дайджесты уже шли:
    # на свежей установке посреди недели ждём ближайшего понедельника.
    return last is not None and now.weekday() > DIGEST_WEEKDAY


def _daily_due(now: datetime, last: float | None, hour: int) -> bool:
    return now.hour >= hour and (last is None or _local_day(last, now) < now.date())


def due(now: datetime, last: Mapping[str, float | None]) -> list[str]:
    """Какие задачи пора запускать. `now` — с часовым поясом Москвы,
    `last` — имя задачи → время последнего запуска (epoch) или None.
    `now` обязан быть с часовым поясом (Europe/Moscow): дни и недели считаются
    по его календарю; без пояса ValueError."""
    if now.tzinfo is None:
        raise ValueError("due(): now должен быть с часовым поясом (Europe/Moscow)")
    names = ["alerts"]
    for name in ("spikes", "anomalies"):
        previous = last.get(name)
        if previous is None or now.timestamp() - previous >= CHECK_EVERY_SECONDS:
            names.append(name)
    if _daily_due(now, last.get("week_snapshot"), SNAPSHOT_HOUR):
        names.append("week_snapshot")
    if _digest_due(now, last.get("digest")):
        names.append("digest")
    if _daily_due(now, last.get("morning"), MORNING_HOUR):
        names.append("morning")
    if _daily_due(now, last.get("prune"), 0):
        names.append("prune")
    return names


# --- общее --------------------------------------------------------------------

async def _our(bot: Bot) -> int | None:
    value = await bot.store.get_setting(OUR_INSTITUTION)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _today(bot: Bot) -> date:
    return datetime.fromtimestamp(bot.clock(), ZoneInfo(bot.config.timezone)).date()


def _link(item: dict[str, Any]) -> str | None:
    url = item.get("publicUrl")
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        return f'<a href="{esc(url)}">ссылка</a>'
    return None


def _kind(item: dict[str, Any]) -> str:
    platform = PLATFORM_NAMES.get(item.get("platform"), esc(item.get("platform") or "—"))
    return f"{platform}, {PUBLICATION_TYPES.get(item.get('publicationType'), 'пост')}"


def _publication_id(item: dict[str, Any]) -> str | None:
    value = item.get("publicationId")
    return None if value is None else str(value)


async def _seeding(bot: Bot, kind: str, job: str, our: int) -> bool:
    """Первый прогон для этого вуза только запоминает посты, ничего не объявляя.

    Вуз уже засеян — не засеваем. Засеян другой (админ сменил наш вуз) —
    засеваем: свежие посты нового вуза — история, а не новость. Отметки нет —
    свежая установка: засеваем, только если ещё ничего не объявлено и задача
    ни разу не прошла, чтобы пустой первый прогон не съел первый настоящий пост.
    """
    seeded_for = await bot.store.get_setting(SEEDED_FOR[kind])
    if seeded_for is not None:
        return seeded_for != our
    return not await bot.store.has_announced_any(kind) and await bot.store.job_last_run(job) is None


async def _mark_seeded(bot: Bot, kind: str, our: int) -> None:
    if await bot.store.get_setting(SEEDED_FOR[kind]) != our:
        await bot.store.set_setting(SEEDED_FOR[kind], our, None)


# --- «выстрелил» --------------------------------------------------------------

def _is_spike(item: dict[str, Any]) -> bool:
    level = item.get("anomalyLevel")
    if isinstance(level, int) and level >= LEVEL_CONFIDENT:
        return False  # накрученный пост — не успех, о нём скажет «накрутка»
    index, age = item.get("interactionIndex"), item.get("ageHours")
    if not isinstance(index, (int, float)) or not isinstance(age, (int, float)):
        return False
    return index >= SPIKE_INDEX and age < SPIKE_MAX_AGE_HOURS


def spike_message(item: dict[str, Any]) -> Message:
    parts = [part for part in (_link(item), _kind(item), format_index(item["interactionIndex"]),
                               f"{round(item['ageHours'])} ч") if part]
    if item.get("views") is not None:
        parts.append(f"{format_count(int(item['views']))} просм.")
    if item.get("promotion"):
        parts.append(f"{icon('promo')} продвижение")
    return Message(f"{icon('spike')} Наш пост выстрелил: " + " · ".join(parts))


async def check_spikes(bot: Bot) -> int:
    """Объявить новые «выстрелившие» наши посты; вернуть, сколько объявлено."""
    our = await _our(bot)
    if our is None:
        return 0
    try:
        body = await bot.source.findings(institution=our, platform="all", period=PERIOD,
                                         suspicious=True)
    except SourceUnavailable as error:
        log.warning("spikes: %s", type(error).__name__)
        return 0
    store = bot.store
    seeding = await _seeding(bot, SPIKE, "spikes", our)
    announced = 0
    for item in body.get("items") or []:
        publication = _publication_id(item)
        if publication is None or not _is_spike(item):
            continue
        if not await store.mark_announced(SPIKE, publication, 1) or seeding:
            continue  # первый прогон только запоминает: старое не объявляем
        await bot.broadcast(spike_message(item), SPIKE)
        announced += 1
    await _mark_seeded(bot, SPIKE, our)
    await store.set_job_run("spikes", bot.clock())
    return announced


# --- «накрутка» ---------------------------------------------------------------

def anomaly_message(item: dict[str, Any], level: int) -> Message:
    title = "Накрутка на нашем посте" if level >= LEVEL_EXPLICIT else "Вероятно, накрутка на нашем посте"
    parts = [part for part in (_link(item), _kind(item)) if part]
    if item.get("views") is not None:
        parts.append(f"{format_count(int(item['views']))} просм.")
    return Message(f"{icon('anomaly')} {title}: " + " · ".join(parts))


async def check_anomalies(bot: Bot) -> int:
    """Объявить новые аномалии уровня 2 и 3 на наших постах; уровень 1 молча пропускаем.
    Пост с уровнем 2, дорастивший до 3, объявляется второй раз."""
    our = await _our(bot)
    if our is None:
        return 0
    try:
        body = await bot.source.anomalous(institution=our, period=PERIOD)
    except SourceUnavailable as error:
        log.warning("anomalies: %s", type(error).__name__)
        return 0
    store = bot.store
    seeding = await _seeding(bot, ANOMALY, "anomalies", our)
    announced = 0
    for item in body.get("items") or []:
        publication, level = _publication_id(item), item.get("anomalyLevel")
        if publication is None or not isinstance(level, int) or level < LEVEL_CONFIDENT:
            continue
        level = min(level, LEVEL_EXPLICIT)
        if not await store.mark_announced(ANOMALY, publication, level) or seeding:
            continue
        await bot.broadcast(anomaly_message(item, level), ANOMALY)
        announced += 1
    await _mark_seeded(bot, ANOMALY, our)
    await store.set_job_run("anomalies", bot.clock())
    return announced


# --- неделя к неделе ----------------------------------------------------------

async def record_week(bot: Bot) -> None:
    """Раз в день сохранить наши показатели за 7 дней; ключ — московская дата."""
    our = await _our(bot)
    if our is None:
        return
    try:
        dashboard = await bot.source.dashboard()
    except SourceUnavailable as error:
        log.warning("week_snapshot: %s", type(error).__name__)
        return
    stats = our_week_stats(dashboard, our)
    if stats:  # пустой снимок дал бы ложное «раньше 0» через неделю
        await bot.store.save_week_snapshot(_today(bot), stats)
    await bot.store.set_job_run("week_snapshot", bot.clock())


# --- дайджест -----------------------------------------------------------------

async def build_digest(bot: Bot) -> list[Message]:
    """Один и тот же дайджест для понедельничной рассылки и для /digest.
    NoOurInstitution — нет нашего вуза; SourceUnavailable — API недоступен."""
    our = await _our(bot)
    if our is None:
        raise NoOurInstitution
    # Как /top по умолчанию (наши, все площадки, 7 дней, без аномалий): с догрузкой
    # площадки, которой не хватило постов на первой странице.
    ours = await bot.source.top_body(TopQuery(), our)
    others = await bot.source.findings(institution=None, platform="all", period=PERIOD,
                                       suspicious=False)
    dashboard = await bot.source.dashboard()
    try:
        forecast = await bot.source.forecast()
    except SourceUnavailable as error:
        # Прогноз — приправа: без него дайджест всё равно полезен.
        log.warning("digest forecast: %s", type(error).__name__)
        forecast = None
    previous = await bot.store.week_snapshot(_today(bot) - timedelta(days=7))
    return render_digest(ours, others, our_week_stats(dashboard, our), previous, forecast, our)


async def send_digest(bot: Bot) -> None:
    """Понедельничная рассылка всем с флагом digest."""
    try:
        messages = await build_digest(bot)
    except NoOurInstitution:
        return
    except SourceUnavailable as error:
        log.warning("digest: %s", type(error).__name__)
        return
    result = await bot.broadcast_report(messages, "digest")
    if result.delivered == 0 and result.transient > 0:
        # Telegram моргнул для всех: не отмечаем, следующий тик повторит.
        log.warning("digest: не доставлен никому, повтор")
        return
    await bot.store.set_job_run("digest", bot.clock())
