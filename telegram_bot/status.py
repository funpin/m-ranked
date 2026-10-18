"""Текст /status: главные проверки из тех же снимков и той же арифметики, что
панель администратора (api/system_overview.status_summary).

Вердикт первой строкой, проблемы сверху, потом сбор по площадкам и сервер.
Картинки нет: ответ должен приходить мгновенно и копироваться текстом."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from api.system_overview import PROFILE_B_FRESHNESS, status_summary

from .emoji import banner, icon
from .render import Message, esc

# Окно снимков для /status: три часа проверок сбора плюс запас на опорный снимок.
STATUS_WINDOW_SECONDS = 3 * 3600 + 900
COLLECTION_SPAN_SECONDS = 3 * 3600
REFRESH_DATA = "st|r"
REFRESH_KEYBOARD = [[{"text": "🔄 Обновить", "callback_data": REFRESH_DATA}]]
# Кружки состояния — светофор, не бренд: слотов у них нет.
ICONS = {"ok": "🟢", "warn": "🟡", "fail": "🔴", "unknown": "⚪"}
# Порядок проверок сервера; «sample» отдельно — это строка о самом снимке.
SERVER_KEYS = ("ingest", "analysis", "units", "disk", "memory", "backup", "errors")
PLATFORM_SLOTS = ("telegram", "vk", "max", "rutube")


def _thousands(value: int) -> str:
    """Точный счёт с пробелом между тысячами: 2916 → «2 916»."""
    return f"{value:,}".replace(",", " ")


def _light(state: str) -> str:
    return ICONS.get(state, ICONS["unknown"])


def _snapshot_time(sampled_at: str | None, tz: str) -> str | None:
    if not sampled_at:
        return None
    try:
        moment = datetime.fromisoformat(sampled_at)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def _verdict(states: list[str]) -> str:
    failed, warned = states.count("fail"), states.count("warn")
    if failed:
        tail = f", предупреждений: {warned}" if warned else ""
        return f"🔴 <b>Проблем: {failed}{tail}</b>"
    if warned:
        return f"🟡 <b>Предупреждений: {warned}</b>"
    if "unknown" in states:
        return "⚪ <b>Часть проверок без данных</b>"
    return "🟢 <b>Всё в порядке</b>"


def render_status(rows: list[dict], now: float, tz: str = "Europe/Moscow") -> Message:
    summary = status_summary(rows, now, lambda platform: PROFILE_B_FRESHNESS[platform],
                             span=COLLECTION_SPAN_SECONDS)
    checks = summary["checks"]
    by_key = {check["key"]: check for check in checks}
    snapshot = _snapshot_time(summary["sampledAt"], tz)
    head = f"{icon('logo')} <b>Состояние m-ranked</b> · "
    head += f"снимок {snapshot}" if snapshot else "снимков нет"
    if summary["sampledAt"] is None:
        # Без снимков остальные строки только вводят в заблуждение: один вердикт.
        return Message("\n".join([head, "🔴 <b>Снимков сервера нет</b>"]), REFRESH_KEYBOARD)

    lines = [head, _verdict([check["state"] for check in checks])]
    if by_key.get("sample", {}).get("state") == "fail":
        lines.append("снимок сервера устарел — данные ниже могут быть старыми")

    problems = [check for state in ("fail", "warn") for check in checks if check["state"] == state]
    if problems:
        lines += ["", banner("ПРОБЛЕМЫ") or f"{icon('alert_urgent')} <b>ПРОБЛЕМЫ</b>"]
        lines += [f"{_light(check['state'])} <b>{esc(check['label'])}</b>: {esc(check['detail'])}"
                  for check in problems]

    lines += ["", banner("СБОР") or "<b>СБОР</b>"]
    for platform in PLATFORM_SLOTS:
        check = by_key.get(f"collection.{platform}")
        if check is not None:
            lines.append(f"{icon(platform)} {_light(check['state'])} {esc(check['detail'])}")
    ok = sum(entry["ok"] for entry in summary["collection"])
    failed = sum(entry["failed"] for entry in summary["collection"])
    lines.append(f"<i>за 3 ч: успешно {_thousands(ok)}, ошибок {_thousands(failed)}</i>")

    server = [by_key[key] for key in SERVER_KEYS if key in by_key]
    if server:
        lines += ["", banner("СЕРВЕР 2") or "<b>СЕРВЕР 2</b>"]
        lines += [f"{_light(check['state'])} {esc(check['label'])} · {esc(check['detail'])}"
                  for check in server]
    return Message("\n".join(lines), REFRESH_KEYBOARD)
