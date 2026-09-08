"""Ответы API проверяются против схем контракта.

Сверка множества путей ловит пропущенный эндпоинт, но не ловит неверную форму
ответа. Здесь каждый ответ валидируется схемой из
contracts/openapi/m-ranked-v1.yaml — той же, из которой фронт генерирует
свой типизированный клиент.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from conftest import requires_api_database as requires_database

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "contracts/openapi/m-ranked-v1.yaml"


@pytest.fixture(scope="module")
def contract() -> dict:
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator_for(contract: dict):
    """OpenAPI 3.1 совместим с JSON Schema 2020-12, поэтому схемы применимы как есть."""
    resource = Resource.from_contents(contract, default_specification=DRAFT202012)
    registry = Registry().with_resource("urn:contract", resource)

    def build(path: str, method: str, status: str):
        operation = contract["paths"][path][method]
        schema = (operation["responses"][status]
                  .get("content", {}).get("application/json", {}).get("schema"))
        if schema is None:
            return None
        # Ссылки внутри контракта разрешаются относительно того же документа.
        rebased = ({"$ref": "urn:contract" + schema["$ref"]} if "$ref" in schema
                   else {**schema, "$id": "urn:contract"})
        return Draft202012Validator(rebased, registry=registry)

    return build


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.config import Settings

    # TestClient поднимает lifespan приложения, поэтому пул соединений и
    # слушатель инвалидации работают так же, как под uvicorn.
    with TestClient(create_app(Settings())) as http:
        yield http


CASES = [
    ("/api/v1/health/live", "get", "200", "/api/v1/health/live"),
    ("/api/v1/health/ready", "get", "200", "/api/v1/health/ready"),
    ("/api/v1/health/legacy", "get", "200", "/api/v1/health/legacy"),
    ("/api/v1/revision", "get", "200", "/api/v1/revision"),
    ("/api/v1/overview", "get", "200", "/api/v1/overview"),
    ("/api/v1/overview", "get", "200", "/api/v1/overview?platform=vk&period=7d&limit=5"),
    ("/api/v1/overview", "get", "200", "/api/v1/overview?sort=views&direction=asc&limit=3"),
    ("/api/v1/overview", "get", "200", "/api/v1/overview?q=университет&limit=2"),
    ("/api/v1/overview", "get", "200", "/api/v1/overview?platform=telegram&period=30d&limit=4"),
]


@requires_database
@pytest.mark.parametrize("path,method,status,url", CASES)
def test_response_matches_contract(client, validator_for, path, method, status, url) -> None:
    response = client.request(method.upper(), url)
    assert str(response.status_code) == status, response.text
    validator = validator_for(path, method, status)
    if validator is None:
        pytest.skip("у ответа нет схемы JSON")
    errors = sorted(validator.iter_errors(response.json()), key=lambda error: list(error.path))
    assert not errors, "\n".join(
        f"  {'/'.join(str(part) for part in error.path) or '<корень>'}: {error.message}"
        for error in errors)


@requires_database
def test_no_store_on_operational_endpoints(client) -> None:
    for url in ("/api/v1/health/live", "/api/v1/health/ready", "/api/v1/revision"):
        assert client.get(url).headers.get("cache-control") == "no-store", url


@requires_database
def test_overview_paging_is_stable(client) -> None:
    """Курсор ведёт к следующей странице без повторов и пропусков."""
    first = client.get("/api/v1/overview?limit=5").json()
    assert len(first["items"]) == 5
    assert first["nextCursor"]

    second = client.get(f"/api/v1/overview?limit=5&cursor={first['nextCursor']}").json()
    assert len(second["items"]) == 5

    first_ids = [item["entityId"] for item in first["items"]]
    second_ids = [item["entityId"] for item in second["items"]]
    assert not set(first_ids) & set(second_ids), "страницы пересекаются"

    whole = client.get("/api/v1/overview?limit=10").json()
    assert [item["entityId"] for item in whole["items"]] == first_ids + second_ids


@requires_database
def test_overview_etag_returns_304(client) -> None:
    response = client.get("/api/v1/overview?limit=3")
    etag = response.headers["etag"]
    assert etag
    again = client.get("/api/v1/overview?limit=3", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.headers["etag"] == etag


@requires_database
def test_overview_rejects_broken_cursor(client) -> None:
    assert client.get("/api/v1/overview?cursor=%%%%%%").status_code == 400


@requires_database
def test_overview_normalizes_unsupported_sort(client) -> None:
    """Неподдерживаемая сортировка не ошибка: прежний HTML откатывался к умолчанию."""
    fallback = client.get("/api/v1/overview?platform=all&sort=posts&limit=3")
    default = client.get("/api/v1/overview?platform=all&sort=m_rating&limit=3")
    assert fallback.status_code == 200
    assert fallback.headers["etag"] == default.headers["etag"]
