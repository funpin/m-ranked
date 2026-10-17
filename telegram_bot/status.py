"""Текст /status: главные проверки из тех же снимков и той же арифметики, что
панель администратора (api/system_overview.status_summary)."""
from __future__ import annotations

from api.system_overview import PROFILE_B_FRESHNESS, status_summary

from .render import esc

# Окно снимков для /status: три часа проверок сбора плюс запас на опорный снимок.
STATUS_WINDOW_SECONDS = 3 * 3600 + 900
COLLECTION_SPAN_SECONDS = 3 * 3600
ICONS = {"ok": "🟢", "warn": "🟡", "fail": "🔴", "unknown": "⚪"}
_RANK = {"ok": 0, "unknown": 1, "warn": 2, "fail": 3}
# Порядок строк после сбора; «sample» появляется вместо них, если снимки устарели.
LINE_KEYS = ("ingest", "analysis", "units", "disk", "memory", "sample")


def _worst(states: list[str]) -> str:
    return max(states, key=lambda state: _RANK.get(state, 1)) if states else "unknown"


def render_status(rows: list[dict], now: float) -> str:
    summary = status_summary(rows, now, lambda platform: PROFILE_B_FRESHNESS[platform],
                             span=COLLECTION_SPAN_SECONDS)
    checks = summary["checks"]
    collection = [check for check in checks if check["key"].startswith("collection.")]
    parts = []
    for check in collection:
        name = check["label"].split(" · ", 1)[-1]
        part = f"{name} {ICONS.get(check['state'], '⚪')}"
        if check["state"] != "ok":
            part += f" ({check['detail']})"
        parts.append(part)
    ok = sum(entry["ok"] for entry in summary["collection"])
    failed = sum(entry["failed"] for entry in summary["collection"])
    first = (f"{ICONS[_worst([check['state'] for check in collection])]} Сбор: "
             f"{'; '.join(parts)}. За 3 ч успешно {ok}, ошибок {failed}")
    lines = [esc(first)]
    by_key = {check["key"]: check for check in checks}
    for key in LINE_KEYS:
        check = by_key.get(key)
        if check is not None:
            lines.append(esc(f"{ICONS.get(check['state'], '⚪')} {check['label']}: {check['detail']}"))
    return "\n".join(lines)
