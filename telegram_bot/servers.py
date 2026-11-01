"""Серверы в боте: список под /status → выбор сервера → его состояние.

Состояние сервера — текст с моноширинными шкалами и спарклайнами: картинку
пришлось бы рисовать и заново выгружать на каждое обновление, а текст
правится одним editMessageText и копируется. Процессы — свои у каждой роли:
основной принимает и анализирует, сборщик опрашивает площадки и отправляет
пачки. Ниже — пропуски замеров за сутки с причиной.

Нагрузка обновляется вживую правкой сообщения, но так, чтобы запросами нельзя
было нагрузить сервер:
- смотреть могут только получатели тревог и только в личке (как /status);
- ответ на сервер кэшируется (основной — 5 с, сборщик — 30 с) и общий для всех
  чатов: база и /proc читаются не чаще раза в этот срок, сколько ни жми;
- кнопки чата — не чаще раза в 3 с;
- живой сеанс: один на чат, не больше трёх на весь бот, две минуты, правка
  раз в 10 с (основной) или 60 с (сборщик — точки агента минутные).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from api import server_monitor as monitor
from api.system_overview import PROFILE_B_FRESHNESS, cpu_percent, pipeline
from operations.storage import hostinfo

from .emoji import banner, icon
from .render import Message, esc

log = logging.getLogger(__name__)

NODE_ID = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
CACHE_SECONDS = {"main": 5.0, "node": 30.0}
LIVE_STEP_SECONDS = {"main": 10.0, "node": 60.0}
LIVE_SECONDS = 120.0
LIVE_LIMIT = 3
PRESS_COOLDOWN_SECONDS = 3.0
# Окно для пропусков и спарклайна: сутки и запас на опорную точку.
GAP_WINDOW_SECONDS = 86400
SPARK_POINTS = 12
LIGHT = {"ok": "🟢", "warn": "🟡", "fail": "🔴", "unknown": "⚪"}
STATE_LIGHT = {"ok": "🟢", "updating": "🔄", "restarted": "🔵", "degraded": "🔴", "offline": "🔴"}
SPARK = "▁▂▃▄▅▆▇█"

LIST_DATA = "st|r"


def server_data(kind: str, server: str) -> str:
    return f"st|{kind}|{server}"


def parse_data(data: str) -> tuple[str, str] | None:
    """(действие, сервер) из кнопки; чужое и испорченное — None."""
    parts = data.split("|")
    if len(parts) != 3 or parts[0] != "st" or parts[1] not in {"s", "v", "x"} or not NODE_ID.fullmatch(parts[2]):
        return None
    return parts[1], parts[2]


def server_buttons(servers: list[dict]) -> list[list[dict]]:
    """По кнопке на подключённый сервер, со светофором состояния."""
    return [[{"text": f"{STATE_LIGHT.get(item['status']['state'], '⚪')} {item['displayName']}",
              "callback_data": server_data("s", item["id"])}] for item in servers]


def bar(percent: float | None, width: int = 10) -> str:
    """Шкала ▰▱ на width делений."""
    if percent is None:
        return "·" * width
    filled = round(max(0.0, min(100.0, percent)) * width / 100)
    return "▰" * filled + "▱" * (width - filled)


def sparkline(values: list[float | None], points: int = SPARK_POINTS) -> str:
    """Спарклайн последних значений: шкала от 0 до 100 (проценты),
    пропуск — пробел."""
    tail = values[-points:]
    return "".join(" " if value is None else SPARK[min(len(SPARK) - 1, int(max(0.0, value) * len(SPARK) / 100.01))]
                   for value in tail)


def size(value: float | None) -> str:
    if value is None:
        return "—"
    for unit, scale in (("ГБ", 1024 ** 3), ("МБ", 1024 ** 2), ("КБ", 1024)):
        if value >= scale:
            return f"{value / scale:.1f} {unit}"
    return f"{value:.0f} Б"


def ago(seconds: float | None) -> str:
    if seconds is None:
        return "нет данных"
    if seconds < 90:
        return "только что"
    if seconds < 5400:
        return f"{seconds / 60:.0f} мин назад"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.1f} ч назад".replace(".", ",")
    return f"{seconds / 86400:.0f} сут назад"


def length(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 90:
        return f"{seconds:.0f} с"
    if seconds < 5400:
        return f"{seconds / 60:.0f} мин"
    return f"{seconds / 3600:.1f} ч".replace(".", ",")


def _section(label: str) -> str:
    return banner(label) or f"<b>{esc(label)}</b>"


def _clock(epoch: float, tz: str, seconds: bool = False, now: float | None = None) -> str:
    """Время по часам бота; не сегодняшнее — с датой."""
    moment = datetime.fromtimestamp(epoch, ZoneInfo(tz))
    if now is not None and moment.date() != datetime.fromtimestamp(now, ZoneInfo(tz)).date():
        return moment.strftime("%d.%m %H:%M")
    return moment.strftime("%H:%M:%S" if seconds else "%H:%M")


class LocalHost:
    """Живые ресурсы машины бота (основной сервер) по /proc: CPU — по
    разности со своим прошлым чтением. Без прошлого чтения или со старым —
    два чтения через секунду. Никакого фонового опроса."""

    def __init__(self, proc: Path = Path("/proc"), sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.time) -> None:
        self.proc, self.sleep, self.clock = proc, sleep, clock
        self.previous: dict[str, Any] | None = None

    async def read(self) -> dict[str, Any]:
        current = hostinfo.counters(self.proc, self.clock)
        if self.previous is None or current["at"] - self.previous["at"] > 120:
            await self.sleep(1.0)
            self.previous, current = current, hostinfo.counters(self.proc, self.clock)
        result: dict[str, Any] = hostinfo.rates(self.previous, current)
        self.previous = current
        try:
            memory = hostinfo.memory((self.proc / "meminfo").read_text())
            result["load"] = [float(value) for value in (self.proc / "loadavg").read_text().split()[:3]]
        except (OSError, ValueError):
            memory, result["load"] = {}, []
        total, available = memory.get("total"), memory.get("available")
        result["memoryTotalBytes"] = total
        result["memoryUsedBytes"] = total - available if total and available is not None else None
        return result


@dataclass
class Live:
    chat_id: int
    message_id: int
    server: str
    until: float
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class ServerMonitor:
    """Вид серверов для бота: кэш, кулдаун кнопок и живые сеансы."""

    def __init__(self, store: Any, clock: Callable[[], float] = time.time, tz: str = "Europe/Moscow",
                 local: LocalHost | None = None, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.store, self.clock, self.tz = store, clock, tz
        self.local = local or LocalHost()
        self.monotonic = monotonic
        self._cache: dict[str, tuple[float, Message]] = {}
        self._servers: tuple[float, list[dict]] | None = None
        self._presses: dict[int, float] = {}
        self.live: dict[int, Live] = {}

    # --- данные --------------------------------------------------------

    async def servers(self) -> list[dict]:
        """Подключённые серверы и основной с их состоянием; кэш — как у основного."""
        if self._servers is not None and self.monotonic() - self._servers[0] < CACHE_SECONDS["main"]:
            return self._servers[1]
        rows = await self.store.server_nodes()
        now = self.clock()
        last_main = None
        if any(row["role"] == "main" for row in rows):
            marks = await self.store.main_marks(600)
            last_main = marks[-1][0] if marks else None
        items = [{**monitor.server_item(row, now, last_main if row["role"] == "main" else None), "row": row}
                 for row in rows]
        self._servers = (self.monotonic(), items)
        return items

    def pressed_too_often(self, chat_id: int) -> bool:
        """Кулдаун кнопок чата; заодно забывает старые нажатия."""
        now = self.monotonic()
        last = self._presses.get(chat_id)
        if last is not None and now - last < PRESS_COOLDOWN_SECONDS:
            return True
        self._presses = {chat: at for chat, at in self._presses.items() if now - at < 60}
        self._presses[chat_id] = now
        return False

    async def message(self, server: str, live_until: float | None = None) -> Message | None:
        """Сообщение о сервере; None — такого сервера нет (кнопка устарела)."""
        items = await self.servers()
        item = next((entry for entry in items if entry["id"] == server), None)
        if item is None:
            return None
        kind = "main" if item["role"] == "main" else "node"
        cached = self._cache.get(server)
        if cached is None or self.monotonic() - cached[0] >= CACHE_SECONDS[kind]:
            body = await (self._main(item) if kind == "main" else self._node(item))
            cached = (self.monotonic(), Message(body))
            self._cache[server] = cached
        text = cached[1].text
        if live_until is not None:
            text += (f"\n\n<i>вживую до {_clock(live_until, self.tz)} · правка раз в "
                     f"{LIVE_STEP_SECONDS[kind]:.0f} с</i>")
        live_button = ({"text": "⏹ Стоп", "callback_data": server_data("x", server)} if live_until is not None
                       else {"text": "▶ Вживую 2 мин", "callback_data": server_data("v", server)})
        keyboard = [[{"text": "◀ Серверы", "callback_data": LIST_DATA},
                     {"text": "🔄", "callback_data": server_data("s", server)}, live_button]]
        return Message(text, keyboard)

    def _head(self, item: dict, now: float) -> list[str]:
        status = item["status"]
        light = STATE_LIGHT.get(status["state"], "⚪")
        role = "основной · приём и анализ" if item["role"] == "main" else "сборщик · опрос и отправка"
        release = f" · <code>{esc(status['release'])}</code>" if status.get("release") else ""
        since = ""
        if status.get("since") and status["state"] != "ok":
            since = f" · {ago(now - datetime.fromisoformat(status['since']).timestamp())}"
        seen = status.get("seenAt")
        seen_text = ago(now - datetime.fromisoformat(seen).timestamp()) if seen else "отчётов нет"
        lines = [f"{icon('logo')} <b>{esc(item['displayName'])}</b> · {role}",
                 f"{light} <b>{esc(status['label'])}</b>{since}{release} · отчёт {seen_text}"]
        if status["state"] in {"updating", "restarted", "degraded"} and status.get("detail"):
            lines.append(f"<i>{esc(status['detail'])}</i>")
        return lines

    def _load(self, now: float, cpu: float | None, cpu_history: list[float | None], memory_used: float | None,
              memory_total: float | None, disk_free: float | None, disk_total: float | None,
              load: list[float], cores: int | None, net: tuple[float | None, float | None] | None) -> list[str]:
        memory = 100.0 * memory_used / memory_total if memory_used is not None and memory_total else None
        disk = 100.0 * (disk_total - disk_free) / disk_total if disk_free is not None and disk_total else None

        def percent(value: float | None) -> str:
            return "  —" if value is None else f"{value:3.0f}%"

        rows = [
            f"CPU  {bar(cpu)} {percent(cpu)} {sparkline(cpu_history)}",
            f"RAM  {bar(memory)} {percent(memory)} {size(memory_used)} из {size(memory_total)}",
            f"Диск {bar(disk)} {percent(disk)} своб. {size(disk_free)}",
            f"LA   {' '.join(f'{value:.2f}' for value in load) or '—'} · {cores or '—'} ядр.",
        ]
        if net is not None and None not in net:
            rows.append(f"Сеть ↓{size(net[0])}/с ↑{size(net[1])}/с")
        return [_section("НАГРУЗКА") + f" · {_clock(now, self.tz, seconds=True)}",
                "<code>" + esc("\n".join(rows)) + "</code>"]

    def _gaps(self, title: str, found: dict[str, Any], now: float) -> list[str]:
        if not found["count"]:
            return [f"🟢 {title}: пропусков нет"]
        latest = found["items"][0]
        start = datetime.fromisoformat(latest["from"]).timestamp() if latest["from"] else now
        span = (f"{_clock(start, self.tz, now=now)}–{_clock(datetime.fromisoformat(latest['to']).timestamp(), self.tz, now=now)}"
                if latest["to"] else f"с {_clock(start, self.tz, now=now)}, идёт")
        cause = f" · {esc(latest['cause'])}" if latest.get("cause") else ""
        return [f"🟡 {title}: {found['count']}, всего {length(found['seconds'])}",
                f"   последний {span}{cause}"]

    async def _main(self, item: dict) -> str:
        now = self.clock()
        rows = await self.store.status_rows(3600)
        marks = await self.store.main_marks(GAP_WINDOW_SECONDS + 600)
        live = await self.local.read()
        latest = rows[-1]["sample"] if rows else {}
        history = [cpu_percent(before["sample"], after["sample"]) for before, after in zip(rows, rows[1:])]
        disk = latest.get("disk") or {}
        lines = self._head(item, now) + [""]
        lines += self._load(now, live.get("cpuPercent"), history[-(SPARK_POINTS - 1):] + [live.get("cpuPercent")],
                            live.get("memoryUsedBytes"), live.get("memoryTotalBytes"), disk.get("free"),
                            disk.get("total"), live.get("load") or [], latest.get("cores"),
                            (live.get("netRxBytesPerSecond"), live.get("netTxBytesPerSecond")))
        values = pipeline(latest) if latest else {}

        def age(key: str) -> float | None:
            moment = values.get(key)
            return now - datetime.fromisoformat(moment).timestamp() if moment else None

        def light(seconds: float | None, limit: float) -> str:
            return LIGHT["unknown"] if seconds is None else LIGHT["ok"] if seconds <= limit else \
                LIGHT["warn"] if seconds <= 2 * limit else LIGHT["fail"]

        lag = values.get("analysisLagSeconds")
        lines += ["", _section("ПРОЦЕССЫ"),
                  f"{light(age('ingestAcceptedAt'), 1200)} Приём с сборщиков · пакет {ago(age('ingestAcceptedAt'))}",
                  f"{light(lag, 3 * 3600)} Анализ · очередь {values.get('analysisBacklog') or 0:.0f}, "
                  f"отставание {length(lag)}",
                  f"{light(age('normsRunAt'), 26 * 3600)} Пересчёт норм · {ago(age('normsRunAt'))}",
                  f"{light(age('backupAt'), 36 * 3600)} Резервная копия · {ago(age('backupAt'))}"]
        lines += self._tasks(item["row"], now)
        lines += ["", _section("ПРОПУСКИ") + " · сутки",
                  *self._gaps("Снимки сервера", monitor.gaps(marks, now, now - GAP_WINDOW_SECONDS, step=60), now)]
        return "\n".join(lines)

    def _tasks(self, row: dict, now: float) -> list[str]:
        """Что идёт сейчас и что упало — из отчёта агента."""
        tasks = monitor.processes(row).get("tasks") or []
        running = [task for task in tasks if task.get("active") == "activating"]
        failed = [task for task in tasks if task.get("active") == "failed"]
        lines = []
        for task in running:
            started = task.get("startedAt")
            lines.append(f"🔵 идёт {esc(task['unit'])}"
                         + (f" · {length(now - started)}" if isinstance(started, (int, float)) else ""))
        lines += [f"🔴 упала {esc(task['unit'])}" for task in failed]
        if not tasks:
            lines.append("⚪ службы: агент не прислал список")
        elif not failed:
            services = sum(1 for task in tasks if not task.get("scheduled"))
            lines.append(f"🟢 службы: {services} работают, упавших нет")
        return lines

    async def _node(self, item: dict) -> str:
        now = self.clock()
        row = item["row"]
        samples = await self.store.node_samples(item["id"], GAP_WINDOW_SECONDS + 600)
        points = [monitor.node_point(sample) for sample in samples]
        host = monitor.host_view(row, points[-1] if points else None)
        latest = points[-1] if points else {}
        lines = self._head(item, now) + [""]
        lines += self._load(now, host["cpuPercent"], [point["cpu"] for point in points], host["memoryUsedBytes"],
                            host["memoryTotalBytes"], host["diskFreeBytes"], host["diskTotalBytes"], host["load"],
                            host["cores"], (latest.get("netRxBytesPerSecond"), latest.get("netTxBytesPerSecond")))
        found = monitor.processes(row)
        collectors = found.get("collectors") if isinstance(found.get("collectors"), dict) else {}
        platforms = monitor.collector_platforms(row)
        lines += ["", _section("ПРОЦЕССЫ")]
        for platform in platforms:
            entry = collectors.get(platform) or {}
            last = entry.get("lastSuccessAt")
            age = now - last if isinstance(last, (int, float)) else None
            limit = PROFILE_B_FRESHNESS.get(platform, 2700)
            light = LIGHT["unknown"] if age is None else LIGHT["ok"] if age <= limit else \
                LIGHT["warn"] if age <= 2 * limit else LIGHT["fail"]
            lines.append(f"{icon(platform)} {light} успешный {ago(age)} · цикл {length(entry.get('cycleSeconds'))}"
                         f" · отставание {length(entry.get('scheduleLagSeconds'))}")
        transfer = found.get("transfer") if isinstance(found.get("transfer"), dict) else {}
        backlog = transfer.get("backlog")
        lines.append(f"{LIGHT['unknown'] if backlog is None else LIGHT['ok'] if backlog <= 50 else LIGHT['warn']}"
                     f" Отправка пачек · в очереди {'—' if backlog is None else f'{backlog:.0f}'}")
        lines += self._tasks(row, now)
        starts = await self.store.collection_starts(platforms, GAP_WINDOW_SECONDS + max(PROFILE_B_FRESHNESS.values()))
        cycles = monitor.cycle_gaps(starts, platforms, now, now - GAP_WINDOW_SECONDS)
        collection = [gap for items in cycles.values() for gap in items]
        collection.sort(key=lambda gap: gap["from"] or "", reverse=True)
        lines += ["", _section("ПРОПУСКИ") + " · сутки",
                  *self._gaps("Точки агента", monitor.gaps(
                      [(sample["observed_at"].timestamp(), sample.get("release")) for sample in samples],
                      now, now - GAP_WINDOW_SECONDS), now),
                  *self._gaps("Сбор", {"count": len(collection), "seconds": sum(gap["seconds"] for gap in collection),
                                       "items": collection}, now)]
        return "\n".join(lines)

    # --- живые сеансы --------------------------------------------------

    def start_live(self, chat_id: int, message_id: int, server: str, kind: str,
                   edit: Callable[[Message], Awaitable[None]]) -> bool:
        """Запустить правку сообщения; False — лимит сеансов исчерпан."""
        self.stop_live(chat_id)
        if len(self.live) >= LIVE_LIMIT:
            return False
        session = Live(chat_id, message_id, server, self.clock() + LIVE_SECONDS)
        session.task = asyncio.create_task(self._run_live(session, LIVE_STEP_SECONDS[kind], edit),
                                           name=f"server-live-{chat_id}")
        self.live[chat_id] = session
        return True

    def stop_live(self, chat_id: int) -> bool:
        session = self.live.pop(chat_id, None)
        if session is None:
            return False
        if session.task is not None and session.task is not asyncio.current_task():
            session.task.cancel()
        return True

    async def _run_live(self, session: Live, step: float, edit: Callable[[Message], Awaitable[None]]) -> None:
        try:
            while True:
                await asyncio.sleep(step)
                if self.live.get(session.chat_id) is not session:
                    return
                final = self.clock() + step > session.until
                message = await self.message(session.server, None if final else session.until)
                if message is None:
                    return
                await edit(message)
                if final:
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 — сбой правки останавливает только этот сеанс
            log.warning("живое обновление сервера остановлено: %s", type(error).__name__)
        finally:
            if self.live.get(session.chat_id) is session:
                self.live.pop(session.chat_id, None)

    async def aclose(self) -> None:
        for chat_id in list(self.live):
            self.stop_live(chat_id)

