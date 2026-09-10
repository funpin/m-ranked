"""SSRF-safe Telegram emoji fetcher with DNS pinning and a weighted TTL cache."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import ssl
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import SplitResult, urljoin, urlsplit


MAX_ASSET_BYTES = 2_000_000
MAX_METADATA_BYTES = 64*1024
MAX_REDIRECTS = 20
DEADLINE_SECONDS = 10
ALLOWED_TYPES = frozenset({"image/webp", "image/png", "image/gif", "image/jpeg"})
BROWSER_TYPES = frozenset({"webp", "png", "gif", "jpg", "jpeg"})


class EmojiMissing(Exception):
    pass


class EmojiUpstream(Exception):
    pass


@dataclass(frozen=True)
class Asset:
    content: bytes
    media_type: str


def allowed_url(value: str) -> SplitResult | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or not host or parsed.username is not None
            or parsed.password is not None or parsed.fragment or port not in (None, 443)):
        return None
    if host != "t.me" and not host.endswith(".telegram.org") and not host.endswith(".telesco.pe"):
        return None
    return parsed


def public_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    return address.is_global and not any((address.is_multicast, address.is_unspecified,
                                          address.is_loopback, address.is_link_local))


async def _bounded(reader: asyncio.StreamReader, maximum: int, deadline: float) -> bytes:
    result = bytearray()
    while len(result) <= maximum:
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise EmojiUpstream("emoji total deadline expired")
        chunk = await asyncio.wait_for(reader.read(min(65536, maximum+1-len(result))), remaining)
        if not chunk:
            break
        result.extend(chunk)
    return bytes(result)


async def _request(url: str, maximum: int, deadline: float) -> tuple[int, str | None, str, bytes]:
    parsed = allowed_url(url)
    if parsed is None:
        raise EmojiMissing()
    remaining = deadline-time.monotonic()
    if remaining <= 0:
        raise EmojiUpstream("emoji total deadline expired")
    loop = asyncio.get_running_loop()
    try:
        answers = await asyncio.wait_for(
            loop.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM), remaining)
    except (OSError, TimeoutError) as error:
        raise EmojiUpstream("Telegram emoji DNS lookup failed") from error
    addresses = list(dict.fromkeys(item[4][0] for item in answers))
    if not addresses or len(addresses) > 32 or not all(public_address(item) for item in addresses):
        raise EmojiUpstream("Telegram emoji DNS answer is prohibited")
    context = ssl.create_default_context()
    writer: asyncio.StreamWriter | None = None
    try:
        remaining = deadline-time.monotonic()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(
            addresses[0], 443, ssl=context, server_hostname=parsed.hostname,
            ssl_handshake_timeout=max(0.001, remaining)), remaining)
        target = parsed.path or "/"
        if parsed.query:
            target += "?" + parsed.query
        request = (f"GET {target} HTTP/1.1\r\nHost: {parsed.hostname}\r\n"
                   "Accept: application/json,image/webp,image/png,image/gif,image/jpeg,*/*\r\n"
                   "Connection: close\r\nUser-Agent: m-ranked-api/1\r\n\r\n")
        writer.write(request.encode("ascii"))
        await asyncio.wait_for(writer.drain(), max(0.001, deadline-time.monotonic()))
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),
                                      max(0.001, deadline-time.monotonic()))
        if len(head) > 64*1024:
            raise EmojiUpstream("Telegram emoji headers are oversized")
        lines = head[:-4].split(b"\r\n")
        if len(lines) > 101 or any(len(line) > 8192 for line in lines):
            raise EmojiUpstream("Telegram emoji headers are invalid")
        status_parts = lines[0].split(b" ", 2)
        if len(status_parts) < 2 or not status_parts[1].isdigit():
            raise EmojiUpstream("Telegram emoji status is invalid")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if b":" not in line:
                raise EmojiUpstream("Telegram emoji header is invalid")
            name, value = line.split(b":", 1)
            headers[name.decode("ascii").lower()] = value.decode("latin-1").strip()
        if headers.get("transfer-encoding", "").lower() == "chunked":
            body = bytearray()
            while True:
                size_line = await asyncio.wait_for(reader.readline(), max(0.001, deadline-time.monotonic()))
                size = int(size_line.split(b";", 1)[0].strip(), 16)
                if size == 0:
                    break
                if len(body)+size > maximum:
                    body.extend(await asyncio.wait_for(
                        reader.readexactly(maximum+1-len(body)), max(0.001, deadline-time.monotonic())))
                    break
                body.extend(await asyncio.wait_for(reader.readexactly(size),
                                                   max(0.001, deadline-time.monotonic())))
                if await asyncio.wait_for(reader.readexactly(2),
                                          max(0.001, deadline-time.monotonic())) != b"\r\n":
                    raise EmojiUpstream("Telegram emoji chunk is invalid")
            content = bytes(body)
        else:
            length = headers.get("content-length")
            if length is not None and length.isdigit():
                wanted = min(int(length), maximum+1)
                content = await asyncio.wait_for(reader.readexactly(wanted),
                                                 max(0.001, deadline-time.monotonic()))
            else:
                content = await _bounded(reader, maximum, deadline)
        return int(status_parts[1]), headers.get("location"), headers.get("content-type", ""), content
    except EmojiMissing:
        raise
    except (OSError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
            TimeoutError) as error:
        raise EmojiUpstream("Telegram emoji request failed") from error
    finally:
        if writer is not None:
            writer.close()


async def _follow(url: str, maximum: int, deadline: float) -> tuple[int, str, bytes]:
    current = url
    for redirect in range(MAX_REDIRECTS+1):
        status, location, content_type, body = await _request(current, maximum, deadline)
        if status not in (301, 302, 303, 307, 308):
            return status, content_type, body
        if location is None:
            return status, content_type, body
        if redirect == MAX_REDIRECTS:
            raise EmojiUpstream("Telegram emoji redirect limit exceeded")
        current = urljoin(current, location)
        if allowed_url(current) is None:
            raise EmojiMissing()
    raise EmojiUpstream("Telegram emoji redirect limit exceeded")


async def fetch(emoji_id: str) -> Asset:
    deadline = time.monotonic()+DEADLINE_SECONDS
    status, _, metadata = await _follow(
        f"https://t.me/i/emoji/{emoji_id}.json", MAX_METADATA_BYTES, deadline)
    if status != 200 or len(metadata) > MAX_METADATA_BYTES:
        raise EmojiMissing()
    try:
        payload = json.loads(metadata)
        if not isinstance(payload, dict):
            raise ValueError
        kind = str(payload.get("type") or "").lower()
        fields = ("emoji", "thumb") if kind in BROWSER_TYPES else ("thumb", "emoji_static")
        target = next((payload.get(field) for field in fields
                       if isinstance(payload.get(field), str) and payload[field]), "")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EmojiUpstream("Telegram emoji metadata is invalid") from error
    if not target or allowed_url(target) is None:
        raise EmojiMissing()
    status, content_type, body = await _follow(target, MAX_ASSET_BYTES, deadline)
    if status != 200 or len(body) > MAX_ASSET_BYTES:
        raise EmojiMissing()
    normalized = content_type.split(";", 1)[0]
    return Asset(body, normalized if normalized in ALLOWED_TYPES else "image/webp")


class EmojiCache:
    def __init__(self) -> None:
        self._items: OrderedDict[str, tuple[float, Asset, int]] = OrderedDict()
        self._weight = 0
        self._lock = asyncio.Lock()

    async def get(self, emoji_id: str) -> Asset:
        async with self._lock:
            now = time.monotonic()
            stale = [key for key, (expires, _, _) in self._items.items() if expires <= now]
            for key in stale:
                _, _, weight = self._items.pop(key)
                self._weight -= weight
            if emoji_id in self._items:
                expires, asset, weight = self._items.pop(emoji_id)
                self._items[emoji_id] = (expires, asset, weight)
                return asset
        asset = await fetch(emoji_id)
        weight = len(emoji_id)*2+len(asset.content)+128
        async with self._lock:
            while self._items and self._weight+weight > 32*1024*1024:
                _, (_, _, removed) = self._items.popitem(last=False)
                self._weight -= removed
            if weight <= 32*1024*1024:
                self._items[emoji_id] = (time.monotonic()+6*3600, asset, weight)
                self._weight += weight
        return asset


CACHE = EmojiCache()
