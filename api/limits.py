"""Верхняя граница тела запроса на уровне приложения.

Nginx уже ограничивает тело своим client_max_body_size, но приложение не
должно зависеть от чужой настройки: запущенное напрямую или за другим прокси,
оно обязано само отказываться читать неограниченный поток.
"""
from __future__ import annotations

import json
from typing import Any

PROBLEM = {
    "type": "urn:m-ranked:problem:request-too-large",
    "title": "Payload Too Large",
    "status": 413,
    "detail": "Тело запроса превышает допустимый размер",
}


class BodyLimit:
    """ASGI-обёртка: считает байты и обрывает запрос, а не буферизует его."""

    def __init__(self, app: Any, maximum: int) -> None:
        self.app = app
        self.maximum = maximum

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.maximum:
            await _refuse(send)
            return
        received = 0
        refused = False

        async def counted() -> dict[str, Any]:
            nonlocal received, refused
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.maximum:
                    refused = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded(message: dict[str, Any]) -> None:
            if refused and message["type"] == "http.response.start":
                await _refuse(send)
                return
            if refused and message["type"] == "http.response.body":
                return
            await send(message)

        await self.app(scope, counted, guarded)


def _declared_length(scope: dict[str, Any]) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


async def _refuse(send: Any) -> None:
    body = json.dumps(PROBLEM, ensure_ascii=False).encode("utf-8")
    await send({"type": "http.response.start", "status": 413, "headers": [
        (b"content-type", b"application/problem+json"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"connection", b"close"),
    ]})
    await send({"type": "http.response.body", "body": body})
