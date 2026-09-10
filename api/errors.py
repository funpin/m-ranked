"""Ошибки в формате application/problem+json, как их описывает контракт."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

PROBLEM = "application/problem+json"


class ApiProblem(Exception):
    def __init__(self, status: int, title: str, detail: str | None = None,
                 type_: str = "about:blank", headers: dict[str, str] | None = None,
                 **extra: object) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_
        self.headers = headers or {}
        self.extra = extra


class NotFound(ApiProblem):
    def __init__(self, detail: str) -> None:
        super().__init__(404, "Not Found", detail)


class BadRequest(ApiProblem):
    def __init__(self, detail: str) -> None:
        super().__init__(400, "Bad Request", detail)


def problem_response(problem: ApiProblem, instance: str = "/") -> JSONResponse:
    body: dict[str, object] = {
        "type": problem.type, "title": problem.title, "status": problem.status,
        "instance": instance,
    }
    if problem.detail is not None:
        body["detail"] = problem.detail
    body.update(problem.extra)
    return JSONResponse(body, status_code=problem.status, media_type=PROBLEM,
                        headers={"Cache-Control": "no-store", **problem.headers})


async def handle(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiProblem)
    return problem_response(exc, request.url.path)
