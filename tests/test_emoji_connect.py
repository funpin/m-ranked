import asyncio
import ssl
import time

import pytest

from api import emoji_proxy


def test_ipv6_is_tried_first_and_a_dead_address_does_not_eat_the_budget(monkeypatch) -> None:
    tried = []

    async def fake_open(address, port, **_):
        tried.append(address)
        if ":" not in address:
            await asyncio.sleep(10)  # IPv4 на Сервере 2 не отвечает
        return "reader", "writer"

    monkeypatch.setattr(emoji_proxy.asyncio, "open_connection", fake_open)
    monkeypatch.setattr(emoji_proxy, "CONNECT_ATTEMPT_SECONDS", 0.05)
    started = time.monotonic()
    result = asyncio.run(emoji_proxy._connect(["149.154.167.99", "2001:67c:4e8:f004::9"], "t.me",
                                              ssl.create_default_context(), time.monotonic() + 5))
    assert result == ("reader", "writer") and tried == ["2001:67c:4e8:f004::9"]
    tried.clear()
    # IPv4 тоже пробуется, если IPv6 не ответил, — но не дольше попытки.
    async def v6_down(address, port, **_):
        tried.append(address)
        if ":" in address:
            raise OSError("unreachable")
        return "r", "w"
    monkeypatch.setattr(emoji_proxy.asyncio, "open_connection", v6_down)
    assert asyncio.run(emoji_proxy._connect(["149.154.167.99", "2001:67c:4e8:f004::9"], "t.me",
                                            ssl.create_default_context(), time.monotonic() + 5)) == ("r", "w")
    assert tried == ["2001:67c:4e8:f004::9", "149.154.167.99"]
    assert time.monotonic() - started < 2


def test_all_addresses_down_is_an_upstream_error(monkeypatch) -> None:
    async def down(address, port, **_):
        raise OSError("unreachable")
    monkeypatch.setattr(emoji_proxy.asyncio, "open_connection", down)
    with pytest.raises(emoji_proxy.EmojiUpstream):
        asyncio.run(emoji_proxy._connect(["149.154.167.99"], "t.me", ssl.create_default_context(),
                                         time.monotonic() + 1))
