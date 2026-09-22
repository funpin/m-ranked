"""Обход страниц назад у публичного предпросмотра Telegram.

Отдельный тест именно на связку «настройка — вызов — запрос»: первая попытка
починки добавила метод, но потеряла его вызов, и сборщик молча продолжал читать
одну страницу. Проверка разбора ссылки этого не ловила.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from collector_runtime.config import Settings
from collector_target.runtime_adapters import TelegramPublicWebCollector


def _page(username: str, ids: list[int], before: int | None) -> str:
    posts = "".join(
        f'<div class="tgme_widget_message" data-post="{username}/{value}">'
        f'<a class="tgme_widget_message_date" href="https://t.me/{username}/{value}">'
        f'<time datetime="2026-09-0{1 + value % 9}T10:00:00+00:00"></time></a>'
        "</div>"
        for value in ids
    )
    more = (f'<a class="tme_messages_more" data-before="{before}">ещё</a>'
            if before is not None else "")
    return f"<html><body>{posts}{more}</body></html>"


@dataclass
class _Response:
    text: str

    def raise_for_status(self) -> None:
        return None


class _Client:
    """Отдаёт три страницы и запоминает, о чём его просили."""

    def __init__(self, username: str) -> None:
        self.username = username
        self.requested: list[str] = []

    async def get(self, url: str) -> _Response:
        self.requested.append(url)
        if "before=30" in url:
            return _Response(_page(self.username, [10, 20], None))
        if "before=50" in url:
            return _Response(_page(self.username, [30, 40], 30))
        return _Response(_page(self.username, [50, 60], 50))


def _collector(pages: int) -> tuple[TelegramPublicWebCollector, _Client]:
    settings = Settings.load(".env.test")
    object.__setattr__(settings, "telegram_history_pages", pages) if getattr(
        type(settings), "__dataclass_params__", None
    ) and type(settings).__dataclass_params__.frozen else setattr(
        settings, "telegram_history_pages", pages)
    client = _Client("example")
    collector = TelegramPublicWebCollector(settings, lambda: None, client=client)  # type: ignore[arg-type]
    return collector, client


def _channel(client: _Client, username: str) -> Any:
    from collector_runtime.public_web import parse_public_channel
    return parse_public_channel(asyncio.run(client.get(f"https://t.me/s/{username}")).text, username)


def test_one_page_keeps_the_previous_behaviour() -> None:
    """Глубина по умолчанию не должна добавлять ни одного лишнего запроса."""
    collector, client = _collector(1)
    channel = _channel(client, "example")
    before = len(client.requested)
    result = asyncio.run(collector._with_history(channel, "example", _page("example", [50, 60], 50)))
    assert len(client.requested) == before
    assert [post.message_id for post in result.posts] == [50, 60]


def test_deeper_budget_follows_the_link_and_orders_the_result() -> None:
    """Обход идёт назад по ссылке и отдаёт посты по возрастанию номера.

    Бюджет 2 — это одна дополнительная страница: единица тратится на ту, что
    сборщик уже прочитал сам.
    """
    collector, client = _collector(2)
    channel = _channel(client, "example")
    client.requested.clear()
    result = asyncio.run(collector._with_history(channel, "example", _page("example", [50, 60], 50)))
    assert [post.message_id for post in result.posts] == [30, 40, 50, 60]
    assert client.requested == ["https://t.me/s/example?before=50"]


def test_walk_stops_where_the_channel_ends() -> None:
    """Дойдя до начала ленты, обход обязан остановиться, а не тратить бюджет."""
    collector, client = _collector(10)
    channel = _channel(client, "example")
    client.requested.clear()
    result = asyncio.run(collector._with_history(channel, "example", _page("example", [50, 60], 50)))
    assert [post.message_id for post in result.posts] == [10, 20, 30, 40, 50, 60]
    assert len(client.requested) == 2


def test_history_is_walked_once_per_channel() -> None:
    """Повторный обход той же ленты — чистая трата бюджета цикла.

    Пока этого не было, сорок страниц перечитывались каждые пять минут: на
    проде это 5175 запросов истории против трёх замеров постов за двадцать
    минут. Цикл растягивался с пяти минут до двенадцати, и публикации старше
    двух недель переставали измеряться.
    """
    collector, client = _collector(10)
    channel = _channel(client, "example")
    first_page = _page("example", [50, 60], 50)

    client.requested.clear()
    asyncio.run(collector._with_history(channel, "example", first_page))
    walked = len(client.requested)
    assert walked > 0

    client.requested.clear()
    again = asyncio.run(collector._with_history(channel, "example", first_page))
    assert client.requested == []
    assert [post.message_id for post in again.posts] == [50, 60]
