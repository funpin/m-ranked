#!/usr/bin/env python3
"""Тревоги Сервера 2 в Telegram: раз в минуту, без отдельного стека мониторинга.

Читает то, что уже пишется на машине: хвост журнала nginx с классом клиента
и исходом кэша (формат m_ranked_traffic), файлы метрик служб, свободное место,
нагрузку и упавшие юниты m-ranked. Сообщение уходит при входе в проблему, при
выходе из неё и повторно раз в REPEAT_SECONDS, пока проблема держится.

Состояние (позиция в журнале, поминутные счётчики, открытые тревоги) лежит в
STATE_DIR. Без токена бота тревоги только пишутся в журнал службы.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

BOT_CLASSES = ("ai_user", "ai_search", "ai_training", "crawler")
WINDOW_MINUTES = 5
REPEAT_SECONDS = 6 * 3600

# 127.0.0.1 [25/Sep/2026:22:55:35 +0300] "GET / HTTP/1.1" 200 724 0.000 human HIT "UA"
LINE = re.compile(
    r'^\S+ \[[^\]]+\] "(?P<request>[^"]*)" (?P<status>\d{3}) \d+ (?P<seconds>[\d.]+) '
    r'(?P<klass>\w+) (?P<cache>\S+) "')


@dataclass(frozen=True)
class Rule:
    key: str
    firing: bool
    text: str


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw.isdecimal() else default


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
    for key in [key for key in buckets if int(key) <= minute - WINDOW_MINUTES]:
        del buckets[key]


def window(state: dict) -> dict:
    total = empty_bucket()
    for bucket in state.get("buckets", {}).values():
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


def evaluate(now: float, traffic: dict, values: dict[str, float], *, disk_free: int, disk_total: int,
             load5: float, failed: list[str], dump_mtime: float | None, limits: dict) -> list[Rule]:
    rules: list[Rule] = []
    minutes = WINDOW_MINUTES
    backup = values.get("mranked_backup_last_success_unixtime") or dump_mtime
    age = (now - backup) / 3600 if backup else None
    rules.append(Rule("backup", age is None or age > limits["backup_hours"],
                      "Бэкапа нет" if age is None else f"Последний бэкап {age:.0f} ч назад"))
    free_share = disk_free / disk_total if disk_total else 1
    rules.append(Rule("disk", disk_free < limits["disk_free_bytes"] or free_share < 0.12,
                      f"Свободно на диске {disk_free / 1e9:.1f} ГБ ({free_share:.0%})"))
    rules.append(Rule("load", load5 > limits["load5"], f"Load average за 5 минут {load5:.1f}"))
    rules.append(Rule("units", bool(failed), "Упали юниты: " + ", ".join(failed) if failed else "Юниты в порядке"))
    accepted = values.get('mranked_transfer_ingest_last_accepted_unixtime{producer="server-1/default"}')
    ingest_age = (now - accepted) / 60 if accepted else None
    rules.append(Rule("ingest", ingest_age is not None and ingest_age > limits["ingest_minutes"],
                      f"Пакеты с Сервера 1 не приходят {ingest_age:.0f} мин" if ingest_age else "Приём пакетов в порядке"))
    lag = values.get("mranked_anomaly_queue_lag_seconds")
    rules.append(Rule("analysis", lag is not None and lag > limits["analysis_lag_seconds"],
                      f"Очередь анализа отстаёт на {lag / 60:.0f} мин" if lag else "Анализ в порядке"))
    reclaimable = values.get("mranked_host_docker_reclaimable_bytes")
    rules.append(Rule("docker", reclaimable is not None and reclaimable > limits["docker_bytes"],
                      f"Docker может освободить {reclaimable / 1e9:.1f} ГБ — нужна ручная чистка"
                      if reclaimable else "Docker в порядке"))
    rules.append(Rule("human_5xx", traffic["human_5xx"] >= limits["human_5xx"],
                      f"Людям {traffic['human_5xx']} ответов 5xx за {minutes} мин"))
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
    return rules


def transitions(rules: list[Rule], state: dict, now: float) -> list[str]:
    """Что отправить: вход в тревогу, выход из неё и напоминание раз в REPEAT_SECONDS."""
    active = state.setdefault("active", {})
    messages = []
    for rule in rules:
        opened = active.get(rule.key)
        if rule.firing and opened is None:
            active[rule.key] = {"since": now, "sent": now}
            messages.append(f"🔴 {rule.text}")
        elif rule.firing and now - opened["sent"] >= REPEAT_SECONDS:
            opened["sent"] = now
            messages.append(f"🔴 Всё ещё: {rule.text} (с {time.strftime('%d.%m %H:%M', time.localtime(opened['since']))})")
        elif not rule.firing and opened is not None:
            del active[rule.key]
            messages.append(f"🟢 Прошло: {rule.text}")
    return messages


def send(token: str, chat: str, text: str) -> None:
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def token() -> str:
    """Токен бота — файл 0600, который кладёт владелец; без него тревоги только в журнал."""
    path = Path(os.environ.get("ALERTS_TELEGRAM_TOKEN_FILE", "/etc/m-ranked/credentials/alerts-telegram-token"))
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def main() -> int:
    now = time.time()
    state_dir = Path(os.environ.get("ALERTS_STATE_DIR", "/var/lib/m-ranked/alerts"))
    state_path = state_dir / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (FileNotFoundError, ValueError):
        state = {}
    read_log(Path(os.environ.get("ALERTS_ACCESS_LOG", "/var/log/nginx/m-ranked-access.log")), state, int(now // 60))
    disk = shutil.disk_usage(os.environ.get("ALERTS_DISK_PATH", "/"))
    limits = {
        "backup_hours": env_int("ALERTS_BACKUP_HOURS", 36),
        "disk_free_bytes": env_int("ALERTS_DISK_FREE_GB", 6) * 10**9,
        "load5": env_int("ALERTS_LOAD5_X10", 40) / 10,
        "ingest_minutes": env_int("ALERTS_INGEST_MINUTES", 20),
        "analysis_lag_seconds": env_int("ALERTS_ANALYSIS_LAG_MINUTES", 180) * 60,
        "docker_bytes": env_int("ALERTS_DOCKER_GB", 5) * 10**9,
        "human_5xx": env_int("ALERTS_HUMAN_5XX", 20),
        "bot_503_share": env_int("ALERTS_BOT_503_PERCENT", 50) / 100,
        "misses_per_second": env_int("ALERTS_MISSES_PER_SECOND", 20),
        "hit_ratio": env_int("ALERTS_HIT_RATIO_PERCENT", 30) / 100,
    }
    rules = evaluate(now, window(state), metrics(Path(os.environ.get(
        "ALERTS_METRICS_DIR", "/var/lib/node_exporter/textfile_collector"))),
        disk_free=disk.free, disk_total=disk.total, load5=os.getloadavg()[1], failed=failed_units(),
        dump_mtime=newest_dump(Path(os.environ.get("ALERTS_BACKUP_DIR", "/var/backups/m-ranked"))),
        limits=limits)
    messages = transitions(rules, state, now)
    bot, chat = token(), os.environ.get("ALERTS_TELEGRAM_CHAT_ID", "")
    unsent = []
    for message in messages:
        print(message, flush=True)
        if bot and chat:
            try:
                send(bot, chat, f"m-ranked · Сервер 2\n{message}")
            except OSError as error:
                print(f"telegram send failed class={type(error).__name__}", file=sys.stderr)
                unsent.append(message)
    if unsent:
        # Не удалось отправить — откатить отметку, чтобы попробовать в следующую минуту.
        for rule in rules:
            if any(rule.text in message for message in unsent) and rule.firing:
                state["active"].pop(rule.key, None)
    state_dir.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    os.replace(temporary, state_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
