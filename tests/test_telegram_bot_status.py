"""Вид /status: вердикт, проблемы сверху, сбор по площадкам, сервер."""
from __future__ import annotations

from datetime import datetime, timezone

from telegram_bot.emoji import icon
from telegram_bot.status import REFRESH_KEYBOARD, _thousands, render_status

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc).timestamp()  # 18:00 МСК


def healthy_sample(**override) -> dict:
    sample = {
        "collection": {p: {"ok": 700, "failed": 0, "lastOk": NOW - 120}
                       for p in ("telegram", "vk", "max", "rutube")},
        "pipeline": {"ingestAcceptedAt": NOW - 30, "analysisLag": 60, "analysisBacklog": 40,
                     "backupAt": NOW - 3600},
        "units": {"failed": []},
        "disk": {"total": 100 * 10**9, "free": 50 * 10**9},
        "memory": {"total": 100, "available": 50},
    }
    sample.update(override)
    return sample


def rows_for(sample: dict, age: float = 60) -> list[dict]:
    return [{"observed_at": datetime.fromtimestamp(NOW - 600, timezone.utc), "sample": {}},
            {"observed_at": datetime.fromtimestamp(NOW - age, timezone.utc), "sample": sample}]


def lines_of(rows: list[dict]) -> list[str]:
    return render_status(rows, NOW).text.split("\n")


def test_all_ok_verdict_and_layout():
    message = render_status(rows_for(healthy_sample()), NOW)
    lines = message.text.split("\n")
    assert lines[0] == f"{icon('logo')} <b>Состояние m-ranked</b> · снимок 17:59"  # 14:59 UTC, МСК
    assert lines[1] == "🟢 <b>Всё в порядке</b>"
    assert "ПРОБЛЕМЫ" not in message.text
    assert lines.index("<b>СБОР</b>") < lines.index("<b>СЕРВЕР 2</b>")
    assert message.keyboard == REFRESH_KEYBOARD == [[{"text": "🔄 Обновить", "callback_data": "st|r"}]]
    assert message.photo is None


def test_collection_lines_use_platform_slots():
    lines = lines_of(rows_for(healthy_sample()))
    start = lines.index("<b>СБОР</b>")
    block = lines[start + 1:start + 5]
    for line, slot in zip(block, ("telegram", "vk", "max", "rutube")):
        assert line.startswith(f"{icon(slot)} 🟢 последний аккаунт")
    assert lines[start + 5].startswith("<i>за 3 ч: успешно ")


def test_collection_total_with_thousands_separator():
    sample = healthy_sample(collection={p: {"ok": 729, "failed": 0, "lastOk": NOW - 120}
                                        for p in ("telegram", "vk", "max", "rutube")})
    rows = rows_for(sample)
    # collection() считает приросты со второй строки: первая — опорная.
    assert "<i>за 3 ч: успешно 2 916, ошибок 0</i>" in lines_of(rows)
    assert _thousands(0) == "0" and _thousands(999) == "999" and _thousands(1234567) == "1 234 567"


def test_server_block_order():
    lines = lines_of(rows_for(healthy_sample()))
    server = lines[lines.index("<b>СЕРВЕР 2</b>") + 1:]
    names = ["Приём с Сервера 1", "Очередь анализа", "Службы", "Диск", "Память",
             "Резервная копия", "Ошибки для людей", "Пропуски снимков за 3 ч"]
    assert [line.split(" ", 1)[1].split(" · ")[0] for line in server] == names
    assert server[0] == "🟢 Приём с Сервера 1 · последний пакет 0 мин назад"


def test_snapshot_gaps_line_names_an_update():
    """Пропуск снимков виден в /status, даже когда проверки уже зелёные."""
    def row(minutes: float, release: str) -> dict:
        return {"observed_at": datetime.fromtimestamp(NOW - minutes * 60, timezone.utc),
                "sample": {**healthy_sample(), "rel": release}}
    rows = [row(minute, "v2026.10.3") for minute in range(180, 40, -1)]
    rows += [row(minute, "v2026.11.0") for minute in range(30, 0, -1)]
    assert lines_of(rows)[-1] == "🟡 Пропуски снимков за 3 ч · 1, всего 11 мин · обновление v2026.10.3 → v2026.11.0"


def test_warn_only_verdict_and_problem_block_before_collection():
    sample = healthy_sample(memory={"total": 100, "available": 8})
    lines = lines_of(rows_for(sample))
    assert lines[1] == "🟡 <b>Предупреждений: 1</b>"
    assert lines[3] == f"{icon('alert_urgent')} <b>ПРОБЛЕМЫ</b>"
    assert lines[4] == "🟡 <b>Память</b>: занято 92%"
    assert lines.index(lines[3]) < lines.index("<b>СБОР</b>")
    # В своём блоке проблема остаётся, но без жирного.
    assert "🟡 Память · занято 92%" in lines


def test_fail_and_warn_verdict_fail_first():
    sample = healthy_sample(
        memory={"total": 100, "available": 8},
        collection={"telegram": {"ok": 5, "failed": 1, "lastOk": NOW - 120},
                    "vk": {"ok": 5, "failed": 0, "lastOk": NOW - 120},
                    "rutube": {"ok": 5, "failed": 0, "lastOk": NOW - 120}})  # MAX без циклов
    lines = lines_of(rows_for(sample))
    assert lines[1] == "🔴 <b>Проблем: 1, предупреждений: 1</b>"
    start = lines.index(f"{icon('alert_urgent')} <b>ПРОБЛЕМЫ</b>")
    assert lines[start + 1] == "🔴 <b>Сбор · MAX</b>: успешных циклов за 3 часа нет"
    assert lines[start + 2] == "🟡 <b>Память</b>: занято 92%"
    assert f"{icon('max')} 🔴 успешных циклов за 3 часа нет" in lines


def test_fail_only_verdict():
    sample = healthy_sample(units={"failed": ["m-ranked-target-web.service"]})
    lines = lines_of(rows_for(sample))
    assert lines[1] == "🔴 <b>Проблем: 1</b>"


def test_stale_snapshot_warning_under_verdict():
    lines = lines_of(rows_for(healthy_sample(), age=3600))
    assert lines[1].startswith("🔴")
    assert lines[2] == "снимок сервера устарел — данные ниже могут быть старыми"
    assert "<b>Снимок сервера</b>" in "\n".join(lines)
    assert "<b>СЕРВЕР 2</b>" not in lines  # проверок сервера нет


def test_no_snapshots_only_verdict():
    message = render_status([], NOW)
    assert message.text.split("\n") == [
        f"{icon('logo')} <b>Состояние m-ranked</b> · снимков нет", "🔴 <b>Снимков сервера нет</b>"]
    assert message.keyboard == REFRESH_KEYBOARD


def test_snapshot_time_in_requested_zone():
    text = render_status(rows_for(healthy_sample()), NOW, "UTC").text
    assert "снимок 14:59" in text
    assert "снимок 17:59" in render_status(rows_for(healthy_sample()), NOW).text


def test_dynamic_text_is_escaped():
    sample = healthy_sample(units={"failed": ["<b>x</b>&y.service"]})
    text = render_status(rows_for(sample), NOW).text
    assert "<b>x</b>" not in text
    assert "&lt;b&gt;x&lt;/b&gt;&amp;y.service" in text
