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


def api_routes(app) -> list:
    """Маршруты приложения; FastAPI держит подключённые роутеры вложенными."""
    from fastapi.routing import APIRoute
    found, pending = [], list(app.routes)
    while pending:
        route = pending.pop()
        if isinstance(route, APIRoute):
            found.append(route)
            continue
        nested = getattr(route, "original_router", None)
        pending.extend(getattr(nested or route, "routes", ()))
    return found


def implemented_paths(app) -> set[str]:
    return {route.path for route in api_routes(app)}


def implemented_operations(app) -> set[tuple[str, str]]:
    return {(route.path, method) for route in api_routes(app)
            for method in route.methods if method != "HEAD"}


def test_every_contract_path_is_implemented(contract: dict, app) -> None:
    missing = sorted(set(contract["paths"]) - implemented_paths(app))
    assert not missing, f"не реализовано путей: {len(missing)}\n" + "\n".join(missing)


def test_no_route_outside_the_contract(contract: dict, app) -> None:
    extra = sorted(implemented_paths(app) - set(contract["paths"]))
    assert not extra, f"маршруты вне контракта: {extra}"


def test_every_contract_operation_is_implemented(contract: dict, app) -> None:
    wanted = {
        (path, method.upper())
        for path, operations in contract["paths"].items()
        for method in operations
        if method in ("get", "post", "put", "delete", "patch")
    }
    have = implemented_operations(app)
    missing = sorted(wanted - have)
    assert not missing, f"не реализовано операций: {len(missing)}\n" + "\n".join(
        f"  {method} {path}" for path, method in missing)


DETAIL_GROUP = {
    ("/api/v1/institutions/{legacyId}", "GET"),
    ("/api/v1/institutions/{legacyId}/accounts", "GET"),
    ("/api/v1/accounts/{legacyId}", "GET"),
    ("/api/v1/accounts/{legacyId}/publications", "GET"),
    ("/api/v1/publications/{legacyId}", "GET"),
    ("/api/v1/publications/{legacyId}/history", "GET"),
}

STATISTICS_GROUP = {("/api/v1/statistics", "GET")}

COMPARE_GROUP = {
    ("/api/v1/compare/candidates", "GET"),
    ("/api/v1/compare", "GET"),
}

EXPORT_MEDIA_GROUP = {
    ("/api/v1/exports/publications.csv", "GET"),
    ("/api/v1/legacy-exports/{kind}.csv", "GET"),
    ("/api/v1/emoji/{emojiId}", "GET"),
}

ANALYSIS_GROUP = {
    ("/api/v1/publications/{legacyId}/anomaly-analysis", "GET"),
    ("/api/v1/admin/publications/{publicationId}/anomaly-signals", "POST"),
    ("/api/v1/admin/anomaly-signals/{findingId}/reviews", "POST"),
}

ADMIN_GROUP = {
    ("/api/v1/admin/csrf", "GET"),
    ("/api/v1/admin/catalog/session", "GET"),
    ("/api/v1/admin/catalog/status", "GET"),
    ("/api/v1/admin/catalog/institutions", "GET"),
    ("/api/v1/admin/catalog/institutions", "POST"),
    ("/api/v1/admin/catalog/institutions/{id}", "PUT"),
    ("/api/v1/admin/catalog/institutions/{id}", "DELETE"),
    ("/api/v1/admin/catalog/institutions/{id}/accounts", "GET"),
    ("/api/v1/admin/catalog/accounts", "POST"),
    ("/api/v1/admin/catalog/accounts/{id}", "DELETE"),
    ("/api/v1/admin/catalog/accounts/{id}/enable", "POST"),
    ("/api/v1/admin/catalog/accounts/{id}/disable", "POST"),
    ("/api/v1/admin/catalog/accounts/{id}/native-id", "POST"),
    ("/api/v1/admin/catalog/legacy-command", "POST"),
    ("/api/v1/admin/jobs", "GET"),
    ("/api/v1/admin/jobs/{jobId}", "GET"),
    ("/api/v1/admin/platform-accounts/{accountId}", "GET"),
    ("/api/v1/admin/platform-accounts/{accountId}/enabled", "PUT"),
    ("/api/v1/admin/exports", "POST"),
    ("/api/v1/admin/exports/{id}", "GET"),
    ("/api/v1/admin/exports/{id}", "DELETE"),
    ("/api/v1/admin/exports/{id}/download", "GET"),
}


def test_entity_and_list_group_is_implemented(contract: dict, app) -> None:
    """Промежуточный зелёный гейт, пока полный порт 43 операций ещё не закончен."""
    contract_operations = {
        (path, method.upper())
        for path, operations in contract["paths"].items()
        for method in operations
        if method in ("get", "post", "put", "delete", "patch")
    }
    implemented = implemented_operations(app)
    assert DETAIL_GROUP <= contract_operations
    assert DETAIL_GROUP <= implemented


def test_statistics_group_is_implemented(contract: dict, app) -> None:
    implemented = implemented_operations(app)
    assert STATISTICS_GROUP <= implemented
    assert ("/api/v1/rating", "GET") not in implemented


def test_compare_group_is_implemented(contract: dict, app) -> None:
    implemented = implemented_operations(app)
    assert COMPARE_GROUP <= implemented


def test_export_and_media_group_is_implemented(contract: dict, app) -> None:
    implemented = implemented_operations(app)
    assert EXPORT_MEDIA_GROUP <= implemented


def test_analysis_group_is_implemented(contract: dict, app) -> None:
    implemented = implemented_operations(app)
    assert ANALYSIS_GROUP <= implemented


def test_admin_group_is_implemented(contract: dict, app) -> None:
    implemented = implemented_operations(app)
    assert ADMIN_GROUP <= implemented
