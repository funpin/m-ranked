#!/usr/bin/env python3
"""Тревоги Сервера 2: раз в минуту, без отдельного стека мониторинга.

Читает то, что уже пишется на машине: хвост журнала nginx с классом клиента
и исходом кэша (формат m_ranked_traffic), файлы метрик служб, свободное место,
нагрузку и упавшие юниты m-ranked. В базу не ходит: сбор по площадкам, p95
страниц и ресурсы Сервера 1 берутся из файла alert-inputs.json, который раз в
минуту пишет ops-sample. Событие рождается при входе в проблему, при выходе из
неё и повторно раз в REPEAT_SECONDS, пока проблема держится.

Сюда в сеть не ходим: событие печатается в журнал службы и, если есть каталог
очереди ALERTS_BOT_SPOOL_DIR, кладётся туда JSON-файлом для Telegram-бота.

Состояние (позиция в журнале, поминутные счётчики, открытые тревоги) лежит в
STATE_DIR.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Literal

BOT_CLASSES = ("ai_user", "ai_search", "ai_training", "crawler")
WINDOW_MINUTES = 5
HISTORY_MINUTES = 15  # сколько минутных корзин хранить: для роботов нужно 5 законченных минут
LOAD_MINUTES = 15
REPEAT_SECONDS = 6 * 3600
SPOOL_LIMIT = 500  # файлов очереди; при переполнении самые старые отбрасываются
# Обычный ритм сбора, секунд (как порог свежести в api/routes/health.py): дольше без
# успешного опроса — тревога. У Rutube цикл длинный.
FRESH_SECONDS = {"telegram": 2700, "vk": 2700, "max": 2700, "rutube": 5400}
PLATFORM_NAMES = {"telegram": "Telegram", "vk": "ВКонтакте", "max": "MAX", "rutube": "Rutube"}
BASELINE_SHARE = 0.3  # за час успешных опросов меньше этой доли обычного для часа недели
FAILURE_SHARE = 0.2  # доля ошибок за час выше этой
FAILURE_MIN_RESULTS = 20  # меньше результатов за час — долю не проверяем
NODE_SILENT_SECONDS = 30 * 60  # узел не присылал снимка ресурсов
NODE_LOAD_FACTOR = 3  # load1 выше стольких ядер
INPUTS_MAX_AGE = 300  # файл ops-sample старше — не верим (пишется раз в минуту)
INPUTS_PATH = "/var/lib/m-ranked/ops-sample/alert-inputs.json"

# 127.0.0.1 [25/Sep/2026:22:55:35 +0300] "GET / HTTP/1.1" 200 724 0.000 human HIT "UA"
LINE = re.compile(
    r'^\S+ \[[^\]]+\] "(?P<request>[^"]*)" (?P<status>\d{3}) \d+ (?P<seconds>[\d.]+) '
    r'(?P<klass>\w+) (?P<cache>\S+) "')


@dataclass(frozen=True)
class Rule:
    key: str
    firing: bool
    text: str
    urgent: bool = False


@dataclass(frozen=True)
class Event:
    key: str
    kind: Literal["open", "repeat", "resolve"]
    urgent: bool
    text: str
    since: float


@dataclass(frozen=True)
class Host:
    """Что видно на самой машине; ряды — по одному значению в минуту, старые первыми."""
    disk_free: int
    disk_total: int
    load5_series: list[float]
    cpu_series: list[float]
    memory_used_share: float | None
    swap_used_bytes: int | None
    failed: list[str]
    dump_mtime: float | None
    bots_per_minute: list[int]


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw.isdecimal() else default


def read_inputs(path: Path, now: float, max_age: float = INPUTS_MAX_AGE) -> dict | None:
    """Файл ops-sample; None, если его нет, он испорчен или старше max_age секунд."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    written = data.get("at") if isinstance(data, dict) else None
    if isinstance(written, bool) or not isinstance(written, (int, float)) or now - written > max_age:
        return None
    return data


def parse_line(line: str) -> dict | None:
    match = LINE.match(line)
    if not match:
        return None
    request = match["request"].split(" ")
    path = request[1] if len(request) > 1 else ""
    return {"status": int(match["status"]), "klass": match["klass"], "cache": match["cache"],
            "seconds": float(match["seconds"]), "static": path.startswith("/_next/static/")}


def empty_bucket() -> dict:
    return {"requests": 0, "human_5xx": 0, "bot_requests": 0, "bot_503": 0, "hits": 0,
            "cacheable": 0, "misses": {}}


def add(bucket: dict, item: dict) -> None:
    bucket["requests"] += 1
    bot = item["klass"] in BOT_CLASSES
    if item["status"] >= 500 and not bot:
        bucket["human_5xx"] += 1
    if bot:
        bucket["bot_requests"] += 1
        if item["status"] == 503:
            bucket["bot_503"] += 1
    if item["static"] or item["cache"] == "-":
        return
    bucket["cacheable"] += 1
    if item["cache"] in ("HIT", "STALE", "UPDATING", "REVALIDATED"):
        bucket["hits"] += 1
    elif item["cache"] in ("MISS", "EXPIRED", "BYPASS"):
        bucket["misses"][item["klass"]] = bucket["misses"].get(item["klass"], 0) + 1


def read_log(path: Path, state: dict, minute: int) -> None:
    """Дочитать журнал с прошлой позиции и сложить строки в корзину текущей минуты."""
    buckets = state.setdefault("buckets", {})
    try:
        stat = path.stat()
    except FileNotFoundError:
        return
    position = state.get("log", {})
    offset = position.get("offset", 0) if position.get("inode") == stat.st_ino else 0
    if offset > stat.st_size:  # журнал усечён или повёрнут на месте
        offset = 0
    if not position:
        offset = stat.st_size  # первый запуск: история не нужна, считаем с этой минуты
    bucket = buckets.setdefault(str(minute), empty_bucket())
    with path.open("rb") as stream:
        stream.seek(offset)
        # Не больше 64 МБ за проход: после простоя старый хвост не считаем.
        data = stream.read(64 * 1024 * 1024)
        offset += len(data)
    for raw in data.decode("utf-8", "replace").splitlines():
        item = parse_line(raw)
        if item:
            add(bucket, item)
    state["log"] = {"inode": stat.st_ino, "offset": offset}
    for key in [key for key in buckets if int(key) <= minute - HISTORY_MINUTES]:
        del buckets[key]


def window(state: dict) -> dict:
    """Сумма за последние WINDOW_MINUTES минут: от самой свежей корзины назад."""
    buckets = state.get("buckets", {})
    total = empty_bucket()
    latest = max((int(key) for key in buckets), default=0)
    for key, bucket in buckets.items():
        if int(key) <= latest - WINDOW_MINUTES:
            continue
        for key in ("requests", "human_5xx", "bot_requests", "bot_503", "hits", "cacheable"):
            total[key] += bucket[key]
        for klass, count in bucket["misses"].items():
            total["misses"][klass] = total["misses"].get(klass, 0) + count
    return total


def metrics(directory: Path) -> dict[str, float]:
    values: dict[str, float] = {}
    for path in directory.glob("*.prom"):
        try:
            text = path.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if line.startswith("#") or " " not in line:
                continue
            name, _, value = line.rpartition(" ")
            try:
                values[name] = float(value)
            except ValueError:
                pass
    return values


def newest_dump(directory: Path) -> float | None:
    dumps = [path.stat().st_mtime for path in directory.glob("mranked-*.dump")]
    return max(dumps) if dumps else None


def failed_units() -> list[str]:
    result = subprocess.run(
        ["systemctl", "list-units", "--failed", "--plain", "--no-legend", "m-ranked-*"],
        capture_output=True, text=True, check=False)
    return [line.split()[0] for line in result.stdout.splitlines() if line.strip()]


def bots_per_minute(state: dict, minute: int, count: int) -> list[int]:
    """Запросы роботов за последние count законченных минут, старые первыми; пропущенная минута — 0."""
    buckets = state.get("buckets", {})
    return [buckets.get(str(number), {}).get("bot_requests", 0) for number in range(minute - count, minute)]


def push_series(state: dict, name: str, value: float, keep: int) -> list[float]:
    """Добавить значение в ряд state["series"][name] и оставить последние keep значений."""
    series = state.setdefault("series", {})
    values = (series.get(name, []) + [value])[-keep:]
    series[name] = values
    return values


def read_cpu_times(path: str | Path = "/proc/stat") -> tuple[int, int] | None:
    """(всего тактов, тактов простоя) по первой строке /proc/stat; None, если файла нет."""
    try:
        fields = Path(path).read_text().splitlines()[0].split()
        numbers = [int(field) for field in fields[1:9]]  # guest уже входит в user и nice
    except (OSError, IndexError, ValueError):
        return None
    if fields[0] != "cpu" or len(numbers) < 5:
        return None
    return sum(numbers), numbers[3] + numbers[4]


def cpu_busy_percent(state: dict) -> float | None:
    """Занятость процессора с прошлого запуска; None на первом запуске и если счётчик не сдвинулся."""
    current = read_cpu_times()
    if current is None:
        return None
    previous = state.get("cpu_prev")
    state["cpu_prev"] = list(current)
    if not previous or current[0] <= previous[0] or current[1] < previous[1]:
        return None
    return 100 * (1 - (current[1] - previous[1]) / (current[0] - previous[0]))


def read_memory(path: str | Path = "/proc/meminfo") -> tuple[float | None, int | None]:
    """(доля занятой памяти без кэша, занято подкачки в байтах); (None, None), если файла нет."""
    try:
        text = Path(path).read_text()
        kib = {name: int(value.split()[0]) for name, _, value in
               (line.partition(":") for line in text.splitlines() if ":" in line)}
        total, available = kib["MemTotal"], kib["MemAvailable"]
        swap = (kib["SwapTotal"] - kib["SwapFree"]) * 1024
    except (OSError, KeyError, ValueError, IndexError):
        return None, None
    return (1 - available / total if total else None), swap


def evaluate(now: float, traffic: dict, values: dict[str, float], host: Host, inputs: dict | None,
             limits: dict) -> list[Rule]:
    disk_free, disk_total = host.disk_free, host.disk_total
    failed, dump_mtime = host.failed, host.dump_mtime
    rules: list[Rule] = []
    minutes = WINDOW_MINUTES
    backup = values.get("mranked_backup_last_success_unixtime") or dump_mtime
    age = (now - backup) / 3600 if backup else None
    rules.append(Rule("backup", age is None or age > limits["backup_hours"],
                      "Бэкапа нет" if age is None else f"Последний бэкап {age:.0f} ч назад"))
    free_share = disk_free / disk_total if disk_total else 1
    disk_text = f"Свободно на диске {disk_free / 1e9:.1f} ГБ ({free_share:.0%})"
    rules.append(Rule("disk", disk_free < limits["disk_free_bytes"] or free_share < 0.12, disk_text))
    rules.append(Rule("disk_urgent", free_share < limits["disk_urgent_share"], disk_text, urgent=True))
    load_series = host.load5_series[-LOAD_MINUTES:]
    load15 = sum(load_series) / len(load_series) if load_series else 0.0
    rules.append(Rule("load", len(load_series) >= LOAD_MINUTES and load15 > limits["load15"],
                      f"Load average в среднем за {LOAD_MINUTES} минут {load15:.1f}"))
    cpu_series = host.cpu_series[-limits["cpu_minutes"]:]
    cpu = sum(cpu_series) / len(cpu_series) if cpu_series else 0.0
    cpu_busy = len(cpu_series) >= limits["cpu_minutes"] and cpu > limits["cpu_percent"]
    rules.append(Rule("cpu", cpu_busy, f"Процессор {cpu:.0f}% в среднем за {limits['cpu_minutes']} мин"))
    page_p95 = inputs.get("pageP95Median15m") if inputs is not None else None
    rules.append(Rule("cpu_slow", cpu_busy and page_p95 is not None and page_p95 > limits["page_p95_seconds"],
                      f"Процессор {cpu:.0f}% и страницы медленные: p95 {page_p95:.1f} с"
                      if page_p95 is not None else "Страницы отвечают в норме", urgent=True))
    memory_share, swap = host.memory_used_share, host.swap_used_bytes
    memory_full = memory_share is not None and memory_share * 100 > limits["memory_percent"]
    swap_full = swap is not None and swap > limits["swap_bytes"]
    memory_text = "Память в порядке" if memory_share is None else (
        f"Память занята {memory_share:.0%}, подкачка {(swap or 0) / 1e9:.1f} ГБ")
    rules.append(Rule("memory", memory_full or swap_full, memory_text))
    bots = host.bots_per_minute[-limits["bot_minutes"]:]
    surge = len(bots) >= limits["bot_minutes"] and min(bots) > limits["bots_per_minute"]
    rules.append(Rule("bots", surge,
                      f"Роботы шлют больше {limits['bots_per_minute']} запросов в минуту уже "
                      f"{limits['bot_minutes']} мин (сейчас {bots[-1] if bots else 0})", urgent=True))
    rules.append(Rule("units", bool(failed), "Упали юниты: " + ", ".join(failed) if failed else "Юниты в порядке",
                      urgent=True))
    accepted = values.get('mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}')
    ingest_age = (now - accepted) / 60 if accepted else None
    rules.append(Rule("ingest", ingest_age is not None and ingest_age > limits["ingest_minutes"],
                      f"Пакеты с Сервера 1 не приходят {ingest_age:.0f} мин" if ingest_age else "Приём пакетов в порядке"))
    lag = values.get("mranked_anomaly_queue_lag_seconds")
    rules.append(Rule("analysis", lag is not None and lag > limits["analysis_lag_seconds"],
                      f"Очередь анализа отстаёт на {lag / 60:.0f} мин" if lag else "Анализ в порядке"))
    reference_accounts = values.get("mranked_anomaly_reference_accounts", 0)
    reference_expiry = values.get("mranked_anomaly_reference_expires_at_unixtime")
    remaining = reference_expiry - now if reference_expiry is not None and math.isfinite(reference_expiry) else None
    needs_reference = reference_accounts > 0 and (remaining is None or remaining < 3 * 86400)
    if reference_accounts <= 0:
        reference_text = "Ограниченный эталон MAX отключён"
    elif remaining is None:
        reference_text = "Неизвестен срок активного эталона MAX: нужна проверка"
    elif remaining <= 0:
        reference_text = "Окно новых публикаций эталона MAX завершилось: нужна проверенная замена"
    else:
        reference_text = f"До конца окна новых публикаций эталона MAX {remaining / 86400:.1f} сут; замена требует проверки"
    rules.append(Rule("analysis_reference", needs_reference, reference_text))
    # Профиль позднего отклика считается раз в сутки; метрики нет до первого запуска.
    tail_run = values.get("mranked_anomaly_tail_last_run_unixtime")
    tail_age = (now - tail_run) / 86400 if tail_run is not None else None
    rules.append(Rule("analysis_tail", tail_age is not None and tail_age > 2,
                      f"Профиль позднего отклика не обновлялся {tail_age:.1f} сут" if tail_age is not None
                      else "Профиль позднего отклика ещё не считался"))
    reclaimable = values.get("mranked_host_docker_reclaimable_bytes")
    rules.append(Rule("docker", reclaimable is not None and reclaimable > limits["docker_bytes"],
                      f"Docker может освободить {reclaimable / 1e9:.1f} ГБ — нужна ручная чистка"
                      if reclaimable else "Docker в порядке"))
    rules.append(Rule("human_5xx", traffic["human_5xx"] >= limits["human_5xx"],
                      f"Людям {traffic['human_5xx']} ответов 5xx за {minutes} мин", urgent=True))
    bot_share = traffic["bot_503"] / traffic["bot_requests"] if traffic["bot_requests"] else 0
    rules.append(Rule("bot_503", traffic["bot_requests"] >= 100 and bot_share > limits["bot_503_share"],
                      f"Роботам 503 в {bot_share:.0%} запросов ({traffic['bot_503']} из {traffic['bot_requests']})"))
    misses = sum(traffic["misses"].values())
    rate = misses / (minutes * 60)
    detail = ", ".join(f"{klass} {count}" for klass, count in sorted(traffic["misses"].items(), key=lambda x: -x[1]))
    rules.append(Rule("misses", rate > limits["misses_per_second"],
                      f"Промахов кэша {rate:.1f}/с (цель ≤ {limits['misses_per_second']}): {detail}"))
    hit_ratio = traffic["hits"] / traffic["cacheable"] if traffic["cacheable"] else 1
    rules.append(Rule("hit_ratio", traffic["cacheable"] >= 300 and hit_ratio < limits["hit_ratio"],
                      f"Доля попаданий в кэш {hit_ratio:.0%} из {traffic['cacheable']} страниц"))
    if inputs is None:
        rules.append(Rule("inputs_stale", True,
                          "Файл замеров ops-sample не обновляется: тревоги по сбору площадок, входу MAX и "
                          "Серверу 1 временно не проверяются"))
    else:
        rules.append(Rule("inputs_stale", False, "Файл замеров ops-sample обновляется"))
        rules.extend(collection_rules(now, inputs.get("collection")))
        rules.extend(node_rules(now, inputs.get("nodes") or {}, limits))
    return suppress(rules)


def minutes_text(age: float | None) -> str:
    return "более 3 ч" if age is None else f"{age / 60:.0f} мин"


def collection_rules(now: float, collection: dict | None) -> list[Rule]:
    """Сбор по площадкам. Нет успешных опросов дольше ритма, мало успешных за час
    против обычного или много ошибок — «collection_<площадка>». У MAX ни одного
    результата вообще — не сбой сбора, а отозванный вход: «max_auth»."""
    if collection is None:
        return []
    rules: list[Rule] = []
    for platform, limit in FRESH_SECONDS.items():
        entry = collection.get(platform) or {}
        name = PLATFORM_NAMES[platform]
        last_ok, last_result = entry.get("lastOk"), entry.get("lastResult")
        ok_age = now - last_ok if last_ok is not None else None
        reasons = []
        if ok_age is None or ok_age > limit:
            reasons.append(f"нет успешных опросов {minutes_text(ok_age)} (обычно чаще, чем раз в {limit // 60} мин)")
        hour_ok, baseline = entry.get("hourOk", 0), entry.get("baselineOk")
        if baseline is not None and hour_ok < BASELINE_SHARE * baseline:
            reasons.append(f"за час успешных опросов {hour_ok} при обычных {baseline:.0f}")
        results, failed = entry.get("hourResults", 0), entry.get("hourFailed", 0)
        if results >= FAILURE_MIN_RESULTS and failed / results > FAILURE_SHARE:
            reasons.append(f"ошибок {failed / results:.0%} за час ({failed} из {results})")
        rules.append(Rule(f"collection_{platform}", bool(reasons),
                          f"Сбор {name}: " + "; ".join(reasons) if reasons else f"Сбор {name} в порядке",
                          urgent=True))
        if platform == "max":
            result_age = now - last_result if last_result is not None else None
            rules.append(Rule("max_auth", result_age is None or result_age > limit,
                              f"MAX: нет ни одного результата опроса {minutes_text(result_age)} — вероятно, MAX "
                              "отозвал вход. Нужна переавторизация: operations/scripts/reauth-max-session.sh "
                              "на сервере сборщиков" if result_age is None or result_age > limit
                              else "Вход MAX в порядке", urgent=True))
    return rules


def node_rules(now: float, nodes: dict, limits: dict) -> list[Rule]:
    """Ресурсы узлов, кроме Сервера 2: диск, память и load1 по последнему снимку
    агента узла (пороги те же, что для Сервера 2) и молчание агента."""
    rules: list[Rule] = []
    for node_id, node in sorted(nodes.items()):
        name = node.get("name") or node_id
        prefix = f"node_{node_id}_"
        observed = node.get("observedAt")
        silent_for = now - observed if observed is not None else None
        rules.append(Rule(prefix + "silent", silent_for is None or silent_for > NODE_SILENT_SECONDS,
                          f"{name}: снимка ресурсов нет {minutes_text(silent_for)}"
                          if silent_for is None or silent_for > NODE_SILENT_SECONDS
                          else f"{name}: снимки ресурсов приходят"))
        total, free = node.get("diskTotal"), node.get("diskFree")
        share = free / total if total and free is not None else None
        disk_text = (f"{name}: свободно на диске {free / 1e9:.1f} ГБ ({share:.0%})"
                     if share is not None else f"{name}: диск в порядке")
        rules.append(Rule(prefix + "disk", share is not None and (free < limits["disk_free_bytes"] or share < 0.12),
                          disk_text))
        rules.append(Rule(prefix + "disk_urgent", share is not None and share < limits["disk_urgent_share"],
                          disk_text, urgent=True))
        memory_total, available = node.get("memoryTotal"), node.get("memoryAvailable")
        used = 1 - available / memory_total if memory_total and available is not None else None
        rules.append(Rule(prefix + "memory", used is not None and used * 100 > limits["memory_percent"],
                          f"{name}: память занята {used:.0%}" if used is not None else f"{name}: память в порядке"))
        load1, cpus = node.get("load1"), node.get("cpus")
        loaded = load1 is not None and bool(cpus) and load1 > NODE_LOAD_FACTOR * cpus
        rules.append(Rule(prefix + "load", loaded,
                          f"{name}: load average {load1:.1f} на {cpus} яд." if loaded else f"{name}: нагрузка в порядке"))
    return rules


def suppress(rules: list[Rule]) -> list[Rule]:
    """Одна причина — одно сообщение. Приём пакетов с Сервера 1 стоит — молчат
    сбор площадок и вход MAX; вход MAX отозван — молчит сбор MAX; узел молчит —
    молчат его устаревшие ресурсы. Подавленное правило остаётся в списке с
    firing=False, чтобы уже открытая тревога закрылась."""
    firing = {rule.key for rule in rules if rule.firing}
    muted: set[str] = set()
    if "ingest" in firing:
        muted.update(rule.key for rule in rules if rule.key.startswith("collection_") or rule.key == "max_auth")
    if "max_auth" in firing:
        muted.add("collection_max")
    for key in firing:
        if key.startswith("node_") and key.endswith("_silent"):
            prefix = key[:-len("silent")]
            muted.update(rule.key for rule in rules if rule.key.startswith(prefix) and rule.key != key)
    return [replace(rule, firing=False) if rule.firing and rule.key in muted else rule for rule in rules]


def transitions(rules: list[Rule], state: dict, now: float) -> list[Event]:
    """Что произошло: вход в тревогу, выход из неё и напоминание раз в REPEAT_SECONDS."""
    active = state.setdefault("active", {})
    events = []
    for rule in rules:
        opened = active.get(rule.key)
        if rule.firing and opened is None:
            active[rule.key] = {"since": now, "sent": now}
            events.append(Event(rule.key, "open", rule.urgent, rule.text, now))
        elif rule.firing and now - opened["sent"] >= REPEAT_SECONDS:
            opened["sent"] = now
            events.append(Event(rule.key, "repeat", rule.urgent, rule.text, opened["since"]))
        elif not rule.firing and opened is not None:
            del active[rule.key]
            events.append(Event(rule.key, "resolve", rule.urgent, rule.text, opened["since"]))
    return events


def format_event(event: Event) -> str:
    if event.kind == "open":
        return f"🔴 {event.text}"
    if event.kind == "repeat":
        return f"🔴 Всё ещё: {event.text} (с {time.strftime('%d.%m %H:%M', time.localtime(event.since))})"
    return f"🟢 Прошло: {event.text}"


def write_event(spool: Path, event: Event, server: str, now: float) -> None:
    """Положить событие в очередь бота: временный файл, затем атомарное переименование.

    Служба работает с UMask=0077, а бот читает очередь от своего пользователя,
    поэтому права файла выставляются явно.
    """
    existing = sorted(path.name for path in spool.glob("*.json"))
    for name in existing[:max(0, len(existing) - SPOOL_LIMIT + 1)]:
        (spool / name).unlink(missing_ok=True)
    name = f"{time.time_ns()}-{event.key}.json"
    payload = {"version": 1, "server": server, "key": event.key, "kind": event.kind, "urgent": event.urgent,
               "text": event.text, "since": event.since, "at": now}
    temporary = spool / f".{name}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o644)
            json.dump(payload, stream, ensure_ascii=False)
        os.replace(temporary, spool / name)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    now = time.time()
    state_dir = Path(os.environ.get("ALERTS_STATE_DIR", "/var/lib/m-ranked/alerts"))
    state_path = state_dir / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (FileNotFoundError, ValueError):
        state = {}
    minute = int(now // 60)
    read_log(Path(os.environ.get("ALERTS_ACCESS_LOG", "/var/log/nginx/m-ranked-access.log")), state, minute)
    disk = shutil.disk_usage(os.environ.get("ALERTS_DISK_PATH", "/"))
    limits = {
        "backup_hours": env_int("ALERTS_BACKUP_HOURS", 36),
        "disk_free_bytes": env_int("ALERTS_DISK_FREE_GB", 6) * 10**9,
        "load15": env_int("ALERTS_LOAD15_X10", 60) / 10,
        "cpu_percent": env_int("ALERTS_CPU_PERCENT", 90),
        "cpu_minutes": max(1, env_int("ALERTS_CPU_MINUTES", 45)),
        "page_p95_seconds": float(env_int("ALERTS_PAGE_P95_SECONDS", 3)),
        "memory_percent": env_int("ALERTS_MEMORY_PERCENT", 90),
        "swap_bytes": env_int("ALERTS_SWAP_MB", 1000) * 10**6,
        "disk_urgent_share": env_int("ALERTS_DISK_URGENT_PERCENT", 7) / 100,
        "bots_per_minute": env_int("ALERTS_BOTS_PER_MINUTE", 150),
        "bot_minutes": max(1, env_int("ALERTS_BOT_MINUTES", 5)),
        "ingest_minutes": max(1, env_int("ALERTS_INGEST_MINUTES", 20)),
        "analysis_lag_seconds": max(1, env_int("ALERTS_ANALYSIS_LAG_MINUTES", 180)) * 60,
        "docker_bytes": env_int("ALERTS_DOCKER_GB", 5) * 10**9,
        "human_5xx": env_int("ALERTS_HUMAN_5XX", 20),
        "bot_503_share": env_int("ALERTS_BOT_503_PERCENT", 50) / 100,
        "misses_per_second": env_int("ALERTS_MISSES_PER_SECOND", 20),
        "hit_ratio": env_int("ALERTS_HIT_RATIO_PERCENT", 30) / 100,
    }
    load5_series = push_series(state, "load5", os.getloadavg()[1], LOAD_MINUTES)
    cpu = cpu_busy_percent(state)
    cpu_series = (push_series(state, "cpu", cpu, limits["cpu_minutes"]) if cpu is not None
                  else state.get("series", {}).get("cpu", []))
    memory_share, swap = read_memory()
    host = Host(disk_free=disk.free, disk_total=disk.total, load5_series=load5_series, cpu_series=cpu_series,
                memory_used_share=memory_share, swap_used_bytes=swap, failed=failed_units(),
                dump_mtime=newest_dump(Path(os.environ.get("ALERTS_BACKUP_DIR", "/var/backups/m-ranked"))),
                bots_per_minute=bots_per_minute(state, minute, limits["bot_minutes"]))
    inputs = read_inputs(Path(os.environ.get("ALERTS_INPUTS_PATH", INPUTS_PATH)), now)
    rules = evaluate(now, window(state), metrics(Path(os.environ.get(
        "ALERTS_METRICS_DIR", "/var/lib/node_exporter/textfile_collector"))), host, inputs, limits)
    spool = Path(os.environ.get("ALERTS_BOT_SPOOL_DIR", "/var/lib/m-ranked/telegram-bot/inbox"))
    server = os.environ.get("ALERTS_SERVER_NAME", "Сервер 2")
    before = {key: dict(entry) for key, entry in state.get("active", {}).items()}
    for event in transitions(rules, state, now):
        print(format_event(event), flush=True)
        if not spool.is_dir():
            continue
        try:
            write_event(spool, event, server, now)
        except OSError as error:
            print(f"spool write failed class={type(error).__name__}", file=sys.stderr)
            # Не удалось записать — вернуть отметку как была, чтобы попробовать в следующую минуту.
            if event.kind == "open":
                state["active"].pop(event.key, None)
            elif event.kind == "repeat":
                state["active"][event.key]["sent"] = before[event.key]["sent"]
            else:
                state["active"][event.key] = before[event.key]
    state_dir.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    os.replace(temporary, state_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
