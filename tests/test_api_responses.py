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

from api.params import statistics_query
from conftest import requires_api_database as requires_database

CONTRACT = pathlib.Path(__file__).resolve().parents[1] / "contracts/openapi/m-ranked-v1.yaml"


def test_statistics_query_normalizes_all_dimensions() -> None:
    query = statistics_query("entities", "max", None, "  @Alpha  ", "bad", "asc", "views", None)
    assert query.platform == "max"
    assert query.view == "entities"
    assert query.search == "@Alpha"
    assert query.publication_sort == "erv"
    assert query.publication_direction == "asc"
    assert query.entity_sort == "views"


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
    # https в базовом адресе: иначе клиент не сохранит куку сессии,
    # помеченную Secure, и ни один административный тест не пройдёт.
    with TestClient(create_app(Settings()), base_url="https://testserver") as http:
        yield http



TEST_TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
TEST_PASSWORD = "admin-test-password"


def sign_in(client, monkeypatch, username: str, *roles: str) -> str:
    """Открыть настоящую сессию и вернуть привязанный к ней CSRF-токен."""
    import base64
    import bcrypt

    from api.security import AuthConfig, AuthUser, totp_code

    secret = base64.b32decode(TEST_TOTP_SECRET)
    config = AuthConfig({username: AuthUser(
        bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=10)),
        frozenset(roles), secret)}, b"0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(client.app.state, "auth", config)
    client.cookies.clear()
    opened = client.post("/api/v1/admin/session", json={
        "username": username, "password": TEST_PASSWORD,
        "otp": totp_code(secret, int(client.app.state.clock()//30)),
    })
    assert opened.status_code == 201, opened.text
    return opened.json()["token"]


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
    ("/api/v1/statistics", "get", "200", "/api/v1/statistics?limit=5"),
    ("/api/v1/statistics", "get", "200", "/api/v1/statistics?platform=vk&period=7d&limit=5"),
    ("/api/v1/statistics", "get", "200", "/api/v1/statistics?view=entities&platform=rutube&period=30d&limit=5"),
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
     "/api/v1/publications/99269506-1466-5e18-a215-a3db2688d786/anomaly-analysis"),
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
def test_statistics_normalization_and_cursor(client) -> None:
    normalized = client.get(
        "/api/v1/statistics?platform=nonsense&period=nonsense&publication_sort=nonsense&limit=3")
    defaulted = client.get(
        "/api/v1/statistics?platform=all&period=30d&publication_sort=erv&limit=3")
    assert normalized.status_code == 200
    assert normalized.headers["etag"] == defaulted.headers["etag"]

    first = client.get("/api/v1/statistics?platform=vk&view=entities&limit=2").json()
    assert first["nextCursor"]
    second = client.get("/api/v1/statistics", params={
        "platform": "vk", "view": "entities", "limit": 2, "cursor": first["nextCursor"],
    }).json()
    assert not ({row["institutionId"] for row in first["entities"]}
                & {row["institutionId"] for row in second["entities"]})
    assert second["offset"] == first["offset"] + len(first["entities"])

    max_statistics = client.get("/api/v1/statistics?platform=max&limit=2")
    assert max_statistics.status_code == 200
    assert max_statistics.json()["platform"] == "max"

    stale_dimensions = client.get("/api/v1/statistics", params={
        "platform": "rutube", "view": "entities", "limit": 2, "cursor": first["nextCursor"],
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
    publication = "99269506-1466-5e18-a215-a3db2688d786"
    analysis = assert_contract_response(
        client.get(f"/api/v1/publications/{publication}/anomaly-analysis"),
        validator_for, "/api/v1/publications/{legacyId}/anomaly-analysis")
    # Ответ v2 — одна строка на пост: страниц и курсора больше нет.
    assert "nextCursor" not in analysis and len(analysis["signals"]) <= 6

    path = f"/api/v1/admin/publications/{publication}/anomaly-signals"
    unauthorized = client.post(path, json={})
    assert_contract_response(
        unauthorized, validator_for,
        "/api/v1/admin/publications/{publicationId}/anomaly-signals", "401", "post")
    assert "www-authenticate" not in unauthorized.headers


    async def fake_create(_sql, values):
        assert values["actor"] == "analysis-admin"
        return {"result": {"findingId": str(uuid.uuid4()), "analysisRevision": 523}}

    import uuid
    csrf = sign_in(client, monkeypatch, "analysis-admin", "ADMIN")
    monkeypatch.setattr(client.app.state.db, "admin_fetch_one", fake_create)
    response = client.post(path, headers={
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

    missing_csrf = client.post(path, headers={
        "Idempotency-Key": str(uuid.uuid4()),
    }, json={
        "metric": "views", "severity": "medium", "explanationCode": "manual_check",
        "suspiciousStartAt": "2026-09-11T10:00:00Z",
        "suspiciousEndAt": "2026-09-11T11:00:00Z", "evidence": {},
    })
    assert missing_csrf.status_code == 403


@requires_database
def test_admin_reads(client, validator_for, monkeypatch) -> None:
    unauthorized = client.get("/api/v1/admin/jobs")
    assert_contract_response(unauthorized, validator_for, "/api/v1/admin/jobs", "401")

    sign_in(client, monkeypatch, "api-admin", "ADMIN")
    csrf_response = client.get("/api/v1/admin/csrf")
    csrf = assert_contract_response(csrf_response, validator_for, "/api/v1/admin/csrf")
    session = client.get("/api/v1/admin/catalog/session")
    csrf = assert_contract_response(session, validator_for, "/api/v1/admin/catalog/session")
    status = client.get("/api/v1/admin/catalog/status")
    assert_contract_response(status, validator_for, "/api/v1/admin/catalog/status")

    institutions = client.get("/api/v1/admin/catalog/institutions?limit=2")
    page = assert_contract_response(
        institutions, validator_for, "/api/v1/admin/catalog/institutions")
    assert page["items"]
    institution_id = page["items"][0]["id"]
    accounts = client.get(
        f"/api/v1/admin/catalog/institutions/{institution_id}/accounts?limit=2")
    account_page = assert_contract_response(
        accounts, validator_for, "/api/v1/admin/catalog/institutions/{id}/accounts")
    if account_page["items"]:
        account_id = account_page["items"][0]["id"]
        state = client.get(f"/api/v1/admin/platform-accounts/{account_id}")
        assert_contract_response(
            state, validator_for, "/api/v1/admin/platform-accounts/{accountId}")

    jobs = client.get("/api/v1/admin/jobs?limit=2")
    jobs_page = assert_contract_response(jobs, validator_for, "/api/v1/admin/jobs")
    if jobs_page["items"]:
        job_id = jobs_page["items"][0]["jobId"]
        detail = client.get(f"/api/v1/admin/jobs/{job_id}?accountResultLimit=2")
        assert_contract_response(detail, validator_for, "/api/v1/admin/jobs/{jobId}")

@requires_database
def test_catalog_command_normalization_and_contract(client, validator_for, monkeypatch) -> None:
    import uuid

    from api.routes import admin

    token = sign_in(client, monkeypatch, "api-editor", "EDITOR")
    correlation = uuid.uuid4()
    target = uuid.uuid4()

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
    response = client.post("/api/v1/admin/catalog/accounts",
                           headers={"X-XSRF-TOKEN": token,
                                    "X-Correlation-Id": str(correlation)}, json={
                               "institutionId": str(uuid.uuid4()), "platform": "telegram",
                               "reference": "https://t.me/Example_Channel/",
                           })
    assert_contract_response(response, validator_for, "/api/v1/admin/catalog/accounts",
                             method="post")
    forbidden = client.delete(
        f"/api/v1/admin/catalog/accounts/{target}?expectedRowVersion=0",
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
