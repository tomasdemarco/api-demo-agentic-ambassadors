import json

import pytest

from merchants_api import handler
from merchants_api.adapters import build_repository
from merchants_api.adapters.memory import InMemoryMerchantRepository
from merchants_api.service import MerchantService

GOOD = {"name": "Panadería La Esquina", "mcc": "5462", "country": "AR"}


@pytest.fixture(autouse=True)
def fresh_service():
    handler.reset_service(MerchantService(InMemoryMerchantRepository()))
    yield
    handler.reset_service(None)


def call(method, path, body=None, query=None, v2=False):
    event = {"body": json.dumps(body) if isinstance(body, (dict, list)) else body, "queryStringParameters": query}
    if v2:
        event.update(rawPath=path, requestContext={"http": {"method": method}})
    else:
        event.update(path=path, httpMethod=method)
    result = handler.lambda_handler(event)
    return result["statusCode"], (json.loads(result["body"]) if result["body"] else None)


def create(**overrides):
    status, body = call("POST", "/merchants", {**GOOD, **overrides})
    assert status == 201, body
    return body


def test_create_and_get():
    created = create()
    assert created["id"].startswith("mer_") and created["status"] == "active"
    status, body = call("GET", f"/merchants/{created['id']}")
    assert status == 200 and body == created


def test_list():
    a, b = create(name="Comercio A"), create(name="Comercio B")
    status, body = call("GET", "/merchants")
    assert status == 200 and {m["id"] for m in body["items"]} == {a["id"], b["id"]}
    status, body = call("GET", "/merchants", query={"limit": "1"})
    assert len(body["items"]) == 1


def test_update_is_partial_and_touches_updated_at():
    created = create()
    status, body = call("PUT", f"/merchants/{created['id']}", {"status": "inactive"})
    assert status == 200
    assert body["status"] == "inactive" and body["name"] == GOOD["name"]
    assert body["created_at"] == created["created_at"]


def test_delete():
    created = create()
    assert call("DELETE", f"/merchants/{created['id']}") == (204, None)
    assert call("GET", f"/merchants/{created['id']}")[0] == 404
    assert call("DELETE", f"/merchants/{created['id']}")[0] == 404


def test_http_api_v2_events():
    created = create()
    assert call("GET", f"/merchants/{created['id']}", v2=True)[0] == 200


@pytest.mark.parametrize("change,field", [
    ({"name": "x"}, "name"),
    ({"mcc": "54"}, "mcc"),
    ({"mcc": 5411}, "mcc"),
    ({"country": "arg"}, "country"),
    ({"status": "borrado"}, "status"),
])
def test_validation_errors(change, field):
    status, body = call("POST", "/merchants", {**GOOD, **change})
    assert status == 400 and field in body["details"]


def test_missing_fields_and_unknown_fields():
    status, body = call("POST", "/merchants", {"pan": "4111111111111111"})
    assert status == 400
    assert {"name", "mcc", "country", "body"} <= set(body["details"])


def test_empty_update_is_400():
    created = create()
    assert call("PUT", f"/merchants/{created['id']}", {})[0] == 400


def test_invalid_json_and_body_size():
    assert call("POST", "/merchants", "{no json")[0] == 400
    assert call("POST", "/merchants", "x" * 20_000)[0] == 413


def test_unknown_routes_and_methods():
    assert call("GET", "/otra")[0] == 404
    assert call("GET", "/merchants/a/b")[0] == 404
    assert call("PATCH", "/merchants")[0] == 405
    assert call("GET", "/merchants/../../etc")[0] == 404
    assert call("GET", "/merchants/no-es-un-id")[0] == 404


def test_health_reports_storage(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "memory")
    assert call("GET", "/health") == (200, {"status": "ok", "storage": "memory"})


def test_default_repository_is_memory(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    assert isinstance(build_repository(), InMemoryMerchantRepository)


def test_unknown_storage_backend_is_503_not_a_crash(monkeypatch):
    """Hoy no hay adaptador de base de datos: el servicio lo informa en lugar de fallar."""
    monkeypatch.setenv("STORAGE_BACKEND", "algo-que-no-existe")
    handler.reset_service(None)
    status, body = call("GET", "/merchants")
    assert status == 503 and "STORAGE_BACKEND" in body["detail"]
