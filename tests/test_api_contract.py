"""Контракт — арбитр порта.

contracts/openapi/m-ranked-v1.yaml заморожен: фронт редизайна и сгенерированный
из того же файла TS-клиент не правятся. Тест требует, чтобы множество путей
приложения в точности совпадало с множеством путей контракта — ни одного
лишнего, ни одного пропущенного.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "contracts/openapi/m-ranked-v1.yaml"


@pytest.fixture(scope="module")
def contract() -> dict:
    with CONTRACT.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="module")
def app():
    from api.app import create_app
    from api.config import Settings
    import os

    os.environ.setdefault("API_READ_DB_HOST", "")
    return create_app(Settings())


def test_contract_is_openapi_31(contract: dict) -> None:
    assert contract["openapi"] == "3.1.0"
    assert contract["info"]["version"] == "1.0.0"


def implemented_paths(app) -> set[str]:
    from fastapi.routing import APIRoute
    return {route.path for route in app.routes if isinstance(route, APIRoute)}


def test_every_contract_path_is_implemented(contract: dict, app) -> None:
    missing = sorted(set(contract["paths"]) - implemented_paths(app))
    assert not missing, f"не реализовано путей: {len(missing)}\n" + "\n".join(missing)


def test_no_route_outside_the_contract(contract: dict, app) -> None:
    extra = sorted(implemented_paths(app) - set(contract["paths"]))
    assert not extra, f"маршруты вне контракта: {extra}"


def test_every_contract_operation_is_implemented(contract: dict, app) -> None:
    from fastapi.routing import APIRoute
    wanted = {
        (path, method.upper())
        for path, operations in contract["paths"].items()
        for method in operations
        if method in ("get", "post", "put", "delete", "patch")
    }
    have = {
        (route.path, method)
        for route in app.routes if isinstance(route, APIRoute)
        for method in route.methods if method != "HEAD"
    }
    missing = sorted(wanted - have)
    assert not missing, f"не реализовано операций: {len(missing)}\n" + "\n".join(
        f"  {method} {path}" for path, method in missing)
