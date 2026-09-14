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
        response = operation["responses"][status]
        if "$ref" in response:
            response_ref = response["$ref"]
            response = contract
            for part in response_ref.removeprefix("#/").split("/"):
                response = response[part]
        content = response.get("content", {})
        schema = (content.get("application/json", {}).get("schema")
                  or content.get("application/problem+json", {}).get("schema"))
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
    ("/api/v1/rating", "get", "200", "/api/v1/rating?entityLimit=5"),
    ("/api/v1/rating", "get", "200", "/api/v1/rating?platform=vk&period=7d&entityLimit=5"),
    ("/api/v1/rating", "get", "200", "/api/v1/rating?platform=rutube&period=30d&entityLimit=5"),
    ("/api/v1/compare/candidates", "get", "200",
     "/api/v1/compare/candidates?platform=telegram&limit=5"),
    ("/api/v1/compare/candidates", "get", "200",
     "/api/v1/compare/candidates?platform=vk&limit=5"),
    ("/api/v1/compare/candidates", "get", "200",
     "/api/v1/compare/candidates?platform=max&limit=5"),
    ("/api/v1/compare/candidates", "get", "200",
     "/api/v1/compare/candidates?platform=rutube&limit=5"),
    ("/api/v1/compare", "get", "200",
     "/api/v1/compare?platform=telegram&horizonHours=24&institutionLimit=2"),
    ("/api/v1/compare", "get", "200",
     "/api/v1/compare?platform=vk&horizonHours=24&institutionLimit=2"),
    ("/api/v1/compare", "get", "200",
     "/api/v1/compare?platform=max&horizonHours=24&institutionLimit=2"),
    ("/api/v1/compare", "get", "200",
     "/api/v1/compare?platform=rutube&horizonHours=24&institutionLimit=2"),
    ("/api/v1/publications/{legacyId}/anomaly-analysis", "get", "200",
     "/api/v1/publications/99269506-1466-5e18-a215-a3db2688d786/anomaly-analysis?limit=5"),
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


def assert_contract_response(response, validator_for, path: str, status: str = "200",
                             method: str = "get") -> dict:
    assert str(response.status_code) == status, response.text
    body = response.json()
    errors = sorted(validator_for(path, method, status).iter_errors(body),
                    key=lambda error: list(error.path))
    assert not errors, "\n".join(
        f"  {'/'.join(str(part) for part in error.path) or '<корень>'}: {error.message}"
        for error in errors)
    return body


@requires_database
def test_detail_response_group_matches_contract(client, validator_for) -> None:
    """Шесть связанных чтений проверяются одной реальной цепочкой идентификаторов."""
    institution = assert_contract_response(
        client.get("/api/v1/institutions/1"), validator_for,
        "/api/v1/institutions/{legacyId}")
    assert institution["legacyId"] == 1

    accounts = assert_contract_response(
        client.get("/api/v1/institutions/1/accounts?limit=10"), validator_for,
        "/api/v1/institutions/{legacyId}/accounts")
    assert accounts["items"]

    chosen_account = None
    publications = None
    for candidate in accounts["items"]:
        response = client.get(f"/api/v1/accounts/{candidate['accountId']}/publications?limit=3")
        candidate_page = assert_contract_response(
            response, validator_for, "/api/v1/accounts/{legacyId}/publications")
        if candidate_page["items"]:
            chosen_account, publications = candidate, candidate_page
            break
    assert chosen_account is not None and publications is not None, "у тестового учреждения нет публикаций"

    account = assert_contract_response(
        client.get(f"/api/v1/accounts/{chosen_account['accountId']}"), validator_for,
        "/api/v1/accounts/{legacyId}")
    assert account["accountId"] == chosen_account["accountId"]

    chosen_publication = publications["items"][0]
    publication = assert_contract_response(
        client.get(f"/api/v1/publications/{chosen_publication['publicationId']}"), validator_for,
        "/api/v1/publications/{legacyId}")
    assert publication["publicationId"] == chosen_publication["publicationId"]

    history = assert_contract_response(
        client.get(f"/api/v1/publications/{publication['publicationId']}/history?limit=5"),
        validator_for, "/api/v1/publications/{legacyId}/history")
    assert history["publication"]["publicationId"] == publication["publicationId"]
    for snapshot in history["items"]:
        assert len(snapshot["rawEvidence"]["sourceFingerprint"]) == 64


@requires_database
def test_detail_paging_cursor_is_scoped_and_stable(client) -> None:
    first = client.get("/api/v1/institutions/1/accounts?limit=1")
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["nextCursor"]
    second = client.get(
        "/api/v1/institutions/1/accounts?limit=1",
        params={"cursor": first_body["nextCursor"]})
    assert second.status_code == 200
    assert first_body["items"][0]["accountId"] != second.json()["items"][0]["accountId"]

    wrong_dimensions = client.get(
        "/api/v1/institutions/1/accounts",
        params={"platform": "vk", "limit": 1, "cursor": first_body["nextCursor"]})
    assert wrong_dimensions.status_code == 400


@requires_database
def test_detail_legacy_ids_and_continuations(client, validator_for) -> None:
    accounts = client.get("/api/v1/institutions/1/accounts?limit=10").json()["items"]
    chosen = next(item for item in accounts if item["publicationCount"] > 0)
    by_legacy = assert_contract_response(
        client.get(f"/api/v1/accounts/{chosen['legacyId']}",
                   params={"legacyType": chosen["legacyType"]}),
        validator_for, "/api/v1/accounts/{legacyId}")
    assert by_legacy["accountId"] == chosen["accountId"]

    first_page = client.get(f"/api/v1/accounts/{chosen['accountId']}/publications?limit=1").json()
    assert first_page["items"] and first_page["nextCursor"]
    second_page = client.get(
        f"/api/v1/accounts/{chosen['accountId']}/publications",
        params={"limit": 1, "cursor": first_page["nextCursor"]}).json()
    assert second_page["items"][0]["publicationId"] != first_page["items"][0]["publicationId"]

    selected = first_page["items"][0]
    by_legacy = assert_contract_response(
        client.get(f"/api/v1/publications/{selected['legacyId']}",
                   params={"legacyType": selected["legacyType"]}),
        validator_for, "/api/v1/publications/{legacyId}")
    assert by_legacy["publicationId"] == selected["publicationId"]

    history_first = client.get(
        f"/api/v1/publications/{selected['publicationId']}/history?limit=1").json()
    if history_first["nextCursor"]:
        history_second = client.get(
            f"/api/v1/publications/{selected['publicationId']}/history",
            params={"limit": 1, "cursor": history_first["nextCursor"]}).json()
        history_pair = client.get(
            f"/api/v1/publications/{selected['publicationId']}/history?limit=2").json()
        assert [history_first["items"][0]["snapshotId"], history_second["items"][0]["snapshotId"]] == [
            item["snapshotId"] for item in history_pair["items"]]


@requires_database
def test_detail_problems_match_contract(client, validator_for) -> None:
    for path, response, status in (
        ("/api/v1/accounts/{legacyId}", client.get("/api/v1/accounts/not-an-id"), "400"),
        ("/api/v1/publications/{legacyId}",
         client.get("/api/v1/publications/9223372036854775807?legacyType=posts"), "404"),
    ):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-type"].startswith("application/problem+json")
        assert_contract_response(response, validator_for, path, status)


@requires_database
def test_rating_normalization_and_cursor(client) -> None:
    normalized = client.get(
        "/api/v1/rating?platform=nonsense&period=nonsense&channel_sort=nonsense&post_sort=nonsense&entityLimit=3")
    defaulted = client.get(
        "/api/v1/rating?platform=telegram&period=1d&channel_sort=engagement&post_sort=reactions&entityLimit=3")
    assert normalized.status_code == 200
    assert normalized.headers["etag"] == defaulted.headers["etag"]

    first = client.get("/api/v1/rating?platform=vk&entityLimit=2").json()
    assert first["nextEntityCursor"]
    second = client.get("/api/v1/rating", params={
        "platform": "vk", "entityLimit": 2, "entityCursor": first["nextEntityCursor"],
    }).json()
    assert not ({row["entityId"] for row in first["entities"]}
                & {row["entityId"] for row in second["entities"]})
    assert second["entityOffset"] == first["entityOffset"] + len(first["entities"])

    stale_dimensions = client.get("/api/v1/rating", params={
        "platform": "rutube", "entityLimit": 2, "entityCursor": first["nextEntityCursor"],
    })
    assert stale_dimensions.status_code == 400


@requires_database
def test_compare_selection_and_cursor_semantics(client, validator_for) -> None:
    candidates = client.get(
        "/api/v1/compare/candidates?platform=telegram&limit=3").json()
    assert len(candidates["items"]) == 3
    selected = [item["selectionLegacyId"] for item in candidates["items"]]

    response = client.get("/api/v1/compare", params=[
        ("platform", "telegram"), ("horizonHours", "24"),
        ("includePartial", "true"), ("institutionLimit", "2"),
        ("channels", str(selected[0])), ("channels", str(selected[0])),
        ("channels", str(selected[1])), ("institutions", "not-an-id"),
    ])
    assert response.status_code == 200, response.text
    body = assert_contract_response(
        response, validator_for, "/api/v1/compare")
    assert [item["selectionLegacyId"] for item in body["series"]] == selected[:2]
    assert body["nextSelectionCursor"] is None
    for series in body["series"]:
        assert all(point["hourOffset"] <= 24 for point in series["points"])
        assert all(point["hourOffset"] >= 1 for point in series["engagementPoints"])

    first = client.get(
        "/api/v1/compare?platform=telegram&horizonHours=24&institutionLimit=1").json()
    assert first["nextSelectionCursor"]
    second = client.get("/api/v1/compare", params={
        "platform": "telegram", "horizonHours": 24, "institutionLimit": 1,
        "selectionCursor": first["nextSelectionCursor"],
    }).json()
    assert first["series"][0]["selectionId"] != second["series"][0]["selectionId"]
    wrong_dimensions = client.get("/api/v1/compare", params={
        "platform": "vk", "horizonHours": 24, "institutionLimit": 1,
        "selectionCursor": first["nextSelectionCursor"],
    })
    assert wrong_dimensions.status_code == 400


@requires_database
def test_compare_rejects_invalid_relevant_selection(client) -> None:
    assert client.get("/api/v1/compare", params={
        "platform": "telegram", "channels": "0",
    }).status_code == 400
    assert client.get("/api/v1/compare", params={
        "platform": "vk", "institutions": "9223372036854775808",
    }).status_code == 400


@requires_database
def test_publication_csv_headers_and_bytes(client) -> None:
    response = client.get("/api/v1/exports/publications.csv?platform=telegram")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="publications-telegram.csv"')
    assert int(response.headers["x-dataset-revision"]) > 0
    assert response.content.startswith(
        b"platform,institution,publication_id,published_at,observed_at,views,")
    assert b"\r\n" in response.content
    assert not response.content.startswith(b"\xef\xbb\xbf")


@requires_database
def test_legacy_csv_fails_closed_without_lexemes(client, validator_for) -> None:
    response = client.get("/api/v1/legacy-exports/posts.csv", params=[
        ("platform", "vk"), ("platform", "tg"), ("ignored", "1")])
    body = assert_contract_response(
        response, validator_for, "/api/v1/legacy-exports/{kind}.csv", "409")
    assert response.headers["cache-control"] == "no-store"
    assert body["code"] == "LEXEMES_MISSING"


@requires_database
def test_emoji_validation_and_success_headers(client, validator_for, monkeypatch) -> None:
    from api.emoji_proxy import Asset
    from api.routes import emoji

    class FakeCache:
        async def get(self, identifier: str) -> Asset:
            assert identifier == "42"
            return Asset(b"\x89PNG\r\n", "image/png")

    monkeypatch.setattr(emoji, "CACHE", FakeCache())
    response = client.get("/api/v1/emoji/42")
    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=21600"

    invalid = client.get("/api/v1/emoji/not-a-number")
    assert_contract_response(invalid, validator_for, "/api/v1/emoji/{emojiId}", "404")


@requires_database
def test_analysis_cursor_and_admin_security(client, validator_for, monkeypatch) -> None:
    import bcrypt

    from api.security import AuthConfig, issue_csrf

    publication = "99269506-1466-5e18-a215-a3db2688d786"
    analysis = assert_contract_response(
        client.get(f"/api/v1/publications/{publication}/anomaly-analysis?limit=1"),
        validator_for, "/api/v1/publications/{legacyId}/anomaly-analysis")
    if analysis["nextCursor"]:
        page = client.get(f"/api/v1/publications/{publication}/anomaly-analysis", params={
            "limit": 1, "cursor": analysis["nextCursor"],
        })
        assert page.status_code == 200
        assert not ({item["id"] for item in analysis["findings"]}
                    & {item["id"] for item in page.json()["findings"]})

    path = f"/api/v1/admin/publications/{publication}/anomaly-signals"
    unauthorized = client.post(path, json={})
    assert_contract_response(
        unauthorized, validator_for,
        "/api/v1/admin/publications/{publicationId}/anomaly-signals", "401", "post")
    assert unauthorized.headers["www-authenticate"].startswith("Basic")

    password_hash = bcrypt.hashpw(b"test-password", bcrypt.gensalt(rounds=4))
    auth = AuthConfig({"analysis-admin": (password_hash, frozenset({"ADMIN"}))}, b"test-secret")
    monkeypatch.setattr(client.app.state, "auth", auth)

    async def fake_create(_sql, values):
        assert values["actor"] == "analysis-admin"
        return {"result": {"findingId": str(uuid.uuid4()), "analysisRevision": 523}}

    import uuid
    monkeypatch.setattr(client.app.state.db, "admin_fetch_one", fake_create)
    csrf = issue_csrf(auth)
    client.cookies.set("XSRF-TOKEN", csrf, path="/api/v1/admin")
    response = client.post(path, auth=("analysis-admin", "test-password"), headers={
        "X-XSRF-TOKEN": csrf, "Idempotency-Key": str(uuid.uuid4()),
    }, json={
        "metric": "views", "severity": "medium", "explanationCode": "manual_check",
        "suspiciousStartAt": "2026-09-11T10:00:00Z",
        "suspiciousEndAt": "2026-09-11T11:00:00Z", "evidence": {"ticket": 42},
    })
    assert_contract_response(
        response, validator_for,
        "/api/v1/admin/publications/{publicationId}/anomaly-signals", method="post")
    assert response.headers["cache-control"] == "no-store"

    missing_csrf = client.post(path, auth=("analysis-admin", "test-password"), headers={
        "Idempotency-Key": str(uuid.uuid4()),
    }, json={
        "metric": "views", "severity": "medium", "explanationCode": "manual_check",
        "suspiciousStartAt": "2026-09-11T10:00:00Z",
        "suspiciousEndAt": "2026-09-11T11:00:00Z", "evidence": {},
    })
    assert missing_csrf.status_code == 403


@requires_database
def test_admin_reads_and_background_export(client, validator_for, monkeypatch) -> None:
    import time
    import bcrypt

    from api.security import AuthConfig

    password_hash = bcrypt.hashpw(b"admin-password", bcrypt.gensalt(rounds=4))
    monkeypatch.setattr(client.app.state, "auth", AuthConfig({
        "api-admin": (password_hash, frozenset({"ADMIN"})),
    }, b"admin-test-secret"))
    auth = ("api-admin", "admin-password")

    unauthorized = client.get("/api/v1/admin/jobs")
    assert_contract_response(unauthorized, validator_for, "/api/v1/admin/jobs", "401")

    csrf_response = client.get("/api/v1/admin/csrf", auth=auth)
    csrf = assert_contract_response(csrf_response, validator_for, "/api/v1/admin/csrf")
    assert "XSRF-TOKEN=" in csrf_response.headers["set-cookie"]
    session = client.get("/api/v1/admin/catalog/session", auth=auth)
    csrf = assert_contract_response(session, validator_for, "/api/v1/admin/catalog/session")
    status = client.get("/api/v1/admin/catalog/status", auth=auth)
    assert_contract_response(status, validator_for, "/api/v1/admin/catalog/status")

    institutions = client.get("/api/v1/admin/catalog/institutions?limit=2", auth=auth)
    page = assert_contract_response(
        institutions, validator_for, "/api/v1/admin/catalog/institutions")
    assert page["items"]
    institution_id = page["items"][0]["id"]
    accounts = client.get(
        f"/api/v1/admin/catalog/institutions/{institution_id}/accounts?limit=2", auth=auth)
    account_page = assert_contract_response(
        accounts, validator_for, "/api/v1/admin/catalog/institutions/{id}/accounts")
    if account_page["items"]:
        account_id = account_page["items"][0]["id"]
        state = client.get(f"/api/v1/admin/platform-accounts/{account_id}", auth=auth)
        assert_contract_response(
            state, validator_for, "/api/v1/admin/platform-accounts/{accountId}")

    jobs = client.get("/api/v1/admin/jobs?limit=2", auth=auth)
    jobs_page = assert_contract_response(jobs, validator_for, "/api/v1/admin/jobs")
    if jobs_page["items"]:
        job_id = jobs_page["items"][0]["jobId"]
        detail = client.get(f"/api/v1/admin/jobs/{job_id}?accountResultLimit=2", auth=auth)
        assert_contract_response(detail, validator_for, "/api/v1/admin/jobs/{jobId}")

    created = client.post("/api/v1/admin/exports", auth=auth,
                          headers={"X-XSRF-TOKEN": csrf["token"]}, json={"platform": "rutube"})
    export = assert_contract_response(
        created, validator_for, "/api/v1/admin/exports", "202", "post")
    assert created.headers["location"].endswith(export["id"])
    for _ in range(100):
        current = client.get(f"/api/v1/admin/exports/{export['id']}", auth=auth)
        export = assert_contract_response(
            current, validator_for, "/api/v1/admin/exports/{id}")
        if export["state"] not in ("queued", "running"):
            break
        time.sleep(0.02)
    assert export["state"] == "succeeded", export
    download = client.get(f"/api/v1/admin/exports/{export['id']}/download", auth=auth)
    assert download.status_code == 200
    assert download.headers["x-dataset-revision"] == str(export["datasetRevision"])
    assert download.content.startswith(b"platform,institution,publication_id,")
    cancelled = client.delete(f"/api/v1/admin/exports/{export['id']}", auth=auth,
                              headers={"X-XSRF-TOKEN": csrf["token"]})
    assert_contract_response(cancelled, validator_for, "/api/v1/admin/exports/{id}",
                             method="delete")


def test_catalog_command_normalization_and_contract(client, validator_for, monkeypatch) -> None:
    import bcrypt
    import uuid

    from api.routes import admin
    from api.security import AuthConfig, issue_csrf

    password_hash = bcrypt.hashpw(b"editor-password", bcrypt.gensalt(rounds=4))
    config = AuthConfig({"api-editor": (password_hash, frozenset({"EDITOR"}))},
                        b"catalog-test-secret")
    monkeypatch.setattr(client.app.state, "auth", config)
    correlation = uuid.uuid4()
    target = uuid.uuid4()
    token = issue_csrf(config)
    client.cookies.clear()
    client.cookies.set("XSRF-TOKEN", token, path="/api/v1/admin")

    async def fake_command(_request, action, command_target, expected, body, actor,
                           supplied_correlation, connection=None):
        assert action == "account.upsert"
        assert command_target is None and expected is None and connection is None
        assert body["externalKey"] == "example_channel"
        assert body["url"] == "https://t.me/Example_Channel"
        assert body["expectedAccountVersions"] == {}
        assert actor == "api-editor" and supplied_correlation == correlation
        return {"outcome": "succeeded", "targetId": str(target), "legacyId": 123,
                "datasetRevision": 456, "rowVersion": 0,
                "correlationId": str(correlation)}

    monkeypatch.setattr(admin, "_catalog_command", fake_command)
    response = client.post("/api/v1/admin/catalog/accounts", auth=("api-editor", "editor-password"),
                           headers={"X-XSRF-TOKEN": token,
                                    "X-Correlation-Id": str(correlation)}, json={
                               "institutionId": str(uuid.uuid4()), "platform": "telegram",
                               "reference": "https://t.me/Example_Channel/",
                           })
    assert_contract_response(response, validator_for, "/api/v1/admin/catalog/accounts",
                             method="post")
    forbidden = client.delete(
        f"/api/v1/admin/catalog/accounts/{target}?expectedRowVersion=0",
        auth=("api-editor", "editor-password"),
        headers={"X-XSRF-TOKEN": token, "X-Correlation-Id": str(correlation)})
    assert_contract_response(forbidden, validator_for,
                             "/api/v1/admin/catalog/accounts/{id}", "403", "delete")


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


@requires_database
def test_detail_routes_pin_the_requested_dataset_revision(client) -> None:
    """Страница детали собирается из нескольких запросов по одному снимку.

    Ревизия набора данных на проде меняется каждые две секунды — её двигает
    каждая запись коллектора. Без закрепления примерно каждый тринадцатый
    просмотр складывал страницу из двух снимков, и расхождение приводило к
    экрану «Сервис временно недоступен».
    """
    overview = client.get("/api/v1/overview?platform=telegram&limit=1").json()
    current = int(overview["datasetRevision"])
    account_id = overview["items"][0]["accounts"][0]["accountId"]

    pinned = current - 1
    response = client.get(f"/api/v1/accounts/{account_id}?revision={pinned}")
    assert response.status_code == 200
    assert response.json()["datasetRevision"] == pinned

    publications = client.get(
        f"/api/v1/accounts/{account_id}/publications?limit=1&revision={pinned}")
    assert publications.status_code == 200
    assert publications.json()["datasetRevision"] == pinned

    # Неизвестная ревизия не ошибка: ответ приходит по текущей, и клиент
    # видит это в самом поле, а не получает отказ.
    unknown = client.get(f"/api/v1/accounts/{account_id}?revision=999999999")
    assert unknown.status_code == 200
    assert unknown.json()["datasetRevision"] != 999999999

    assert client.get(f"/api/v1/accounts/{account_id}?revision=0").status_code == 400
