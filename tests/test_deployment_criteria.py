"""Pruebas de los criterios de aceptación del despliegue con persistencia real.

Cubren:
  CA-1  La API expone CRUD con el mismo contrato HTTP usando el backend DynamoDB.
  CA-2  Los comercios se guardan en DynamoDB (adaptador registrado y funcional).
  CA-3  Un comercio creado se puede consultar en una invocación posterior
        (persistencia real simulada: dos instancias de handler comparten la misma tabla).
  CA-4  El adaptador en memoria sigue disponible para pruebas y desarrollo local.

No usan red ni AWS real: se inyecta una tabla falsa en memoria que simula boto3.
"""

from __future__ import annotations

import json
import unittest.mock as mock
from typing import Any

import pytest

from merchants_api import handler
from merchants_api.adapters.dynamodb import DynamoDBMerchantRepository
from merchants_api.adapters.memory import InMemoryMerchantRepository
from merchants_api.service import MerchantService


# ---------------------------------------------------------------------------
# Tabla falsa (misma que en test_dynamodb_adapter.py, copiada para aislamiento)
# ---------------------------------------------------------------------------

class FakeDynamoTable:
    """Simula boto3.resource('dynamodb').Table(...) con almacenamiento en dict."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def get_item(self, *, Key: dict[str, Any]) -> dict[str, Any]:
        merchant_id = Key["merchant_id"]
        item = self._items.get(merchant_id)
        return {"Item": dict(item)} if item is not None else {}

    def put_item(self, *, Item: dict[str, Any]) -> dict[str, Any]:
        merchant_id = Item["merchant_id"]
        self._items[merchant_id] = dict(Item)
        return {}

    def delete_item(self, *, Key: dict[str, Any], ReturnValues: str = "NONE") -> dict[str, Any]:
        merchant_id = Key["merchant_id"]
        old = self._items.pop(merchant_id, None)
        if ReturnValues == "ALL_OLD" and old is not None:
            return {"Attributes": old}
        return {}

    def scan(self, *, Limit: int = 50) -> dict[str, Any]:
        items = list(self._items.values())[:Limit]
        return {"Items": [dict(i) for i in items]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service_with_fake_dynamo(fake_table: FakeDynamoTable) -> MerchantService:
    """Construye un MerchantService respaldado por DynamoDB con tabla falsa."""
    repo = DynamoDBMerchantRepository(table_name="merchants-table", _table=fake_table)
    return MerchantService(repo)


def _call(method: str, path: str, body: Any = None, query: dict | None = None) -> tuple[int, Any]:
    event: dict[str, Any] = {
        "body": json.dumps(body) if isinstance(body, (dict, list)) else body,
        "queryStringParameters": query,
        "path": path,
        "httpMethod": method,
    }
    result = handler.lambda_handler(event)
    return result["statusCode"], (json.loads(result["body"]) if result["body"] else None)


GOOD_MERCHANT = {"name": "Supermercado Central", "mcc": "5411", "country": "AR"}


# ---------------------------------------------------------------------------
# CA-1: Contrato HTTP idéntico con backend DynamoDB
# ---------------------------------------------------------------------------

class TestContractHttpDynamoDB:
    """CA-1: El contrato HTTP (rutas, códigos, formato) no cambia con DynamoDB."""

    @pytest.fixture(autouse=True)
    def setup(self):
        fake_table = FakeDynamoTable()
        handler.reset_service(_make_service_with_fake_dynamo(fake_table))
        yield
        handler.reset_service(None)

    def test_post_returns_201_with_merchant(self):
        status, body = _call("POST", "/merchants", GOOD_MERCHANT)
        assert status == 201
        assert body["id"].startswith("mer_")
        assert body["name"] == GOOD_MERCHANT["name"]
        assert body["status"] == "active"

    def test_get_existing_returns_200(self):
        _, created = _call("POST", "/merchants", GOOD_MERCHANT)
        status, body = _call("GET", f"/merchants/{created['id']}")
        assert status == 200
        assert body == created

    def test_get_nonexistent_returns_404(self):
        status, body = _call("GET", "/merchants/mer_000000000000")
        assert status == 404
        assert "error" in body

    def test_list_returns_200_with_items(self):
        _call("POST", "/merchants", GOOD_MERCHANT)
        status, body = _call("GET", "/merchants")
        assert status == 200
        assert "items" in body
        assert len(body["items"]) >= 1

    def test_list_respects_limit_param(self):
        _call("POST", "/merchants", {**GOOD_MERCHANT, "name": "Comercio Uno"})
        _call("POST", "/merchants", {**GOOD_MERCHANT, "name": "Comercio Dos"})
        status, body = _call("GET", "/merchants", query={"limit": "1"})
        assert status == 200
        assert len(body["items"]) == 1

    def test_put_returns_200_with_updated_merchant(self):
        _, created = _call("POST", "/merchants", GOOD_MERCHANT)
        status, body = _call("PUT", f"/merchants/{created['id']}", {"status": "inactive"})
        assert status == 200
        assert body["status"] == "inactive"
        assert body["name"] == GOOD_MERCHANT["name"]

    def test_put_nonexistent_returns_404(self):
        status, _ = _call("PUT", "/merchants/mer_000000000000", {"status": "inactive"})
        assert status == 404

    def test_delete_returns_204(self):
        _, created = _call("POST", "/merchants", GOOD_MERCHANT)
        status, body = _call("DELETE", f"/merchants/{created['id']}")
        assert status == 204
        assert body is None

    def test_delete_nonexistent_returns_404(self):
        status, _ = _call("DELETE", "/merchants/mer_000000000000")
        assert status == 404

    def test_health_with_dynamodb_backend(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "dynamodb")
        status, body = _call("GET", "/health")
        assert status == 200
        assert body == {"status": "ok", "storage": "dynamodb"}


# ---------------------------------------------------------------------------
# CA-2: Los comercios se guardan en DynamoDB (adaptador registrado)
# ---------------------------------------------------------------------------

class TestDynamoDBAdapterRegistered:
    """CA-2: build_repository() devuelve DynamoDBMerchantRepository con STORAGE_BACKEND=dynamodb."""

    def test_build_repository_returns_dynamodb_instance(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "dynamodb")
        monkeypatch.setenv("TABLE_NAME", "merchants-table")

        fake_table = FakeDynamoTable()
        fake_resource = mock.MagicMock()
        fake_resource.Table.return_value = fake_table

        with mock.patch("boto3.resource", return_value=fake_resource):
            from merchants_api.adapters import build_repository
            repo = build_repository()

        assert isinstance(repo, DynamoDBMerchantRepository)

    def test_dynamodb_adapter_stores_and_retrieves(self):
        """El adaptador DynamoDB guarda y recupera un comercio correctamente."""
        fake_table = FakeDynamoTable()
        repo = DynamoDBMerchantRepository(table_name="merchants-table", _table=fake_table)
        service = MerchantService(repo)

        created = service.create({"name": "Ferretería Norte", "mcc": "5251", "country": "UY"})
        retrieved = service.get(created.id)

        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.name == "Ferretería Norte"
        assert retrieved.mcc == "5251"
        assert retrieved.country == "UY"

    def test_dynamodb_item_uses_merchant_id_as_pk(self):
        """La clave de partición en DynamoDB es 'merchant_id', no 'id'."""
        fake_table = FakeDynamoTable()
        repo = DynamoDBMerchantRepository(table_name="merchants-table", _table=fake_table)
        service = MerchantService(repo)

        created = service.create({"name": "Librería Sur", "mcc": "5942", "country": "AR"})

        # Verificar directamente en la tabla falsa que la PK es merchant_id
        stored = list(fake_table._items.values())[0]
        assert "merchant_id" in stored
        assert "id" not in stored
        assert stored["merchant_id"] == created.id


# ---------------------------------------------------------------------------
# CA-3: Persistencia real — un comercio creado se puede consultar en invocación posterior
# ---------------------------------------------------------------------------

class TestPersistenceAcrossInvocations:
    """CA-3: Dos invocaciones independientes del handler comparten la misma tabla DynamoDB."""

    def test_created_merchant_visible_in_subsequent_invocation(self):
        """
        Simula dos invocaciones Lambda independientes que comparten la misma tabla DynamoDB.
        La primera crea un comercio; la segunda lo consulta sin conocer el estado de la primera.
        """
        # Tabla compartida (simula DynamoDB real que persiste entre invocaciones)
        shared_table = FakeDynamoTable()

        # --- Primera invocación: crear comercio ---
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        status_create, body_create = _call("POST", "/merchants", GOOD_MERCHANT)
        assert status_create == 201
        merchant_id = body_create["id"]

        # --- Segunda invocación: nueva instancia del handler, misma tabla ---
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        status_get, body_get = _call("GET", f"/merchants/{merchant_id}")

        assert status_get == 200
        assert body_get["id"] == merchant_id
        assert body_get["name"] == GOOD_MERCHANT["name"]

        handler.reset_service(None)

    def test_deleted_merchant_not_visible_in_subsequent_invocation(self):
        """Un comercio eliminado en una invocación no aparece en la siguiente."""
        shared_table = FakeDynamoTable()

        # Invocación 1: crear
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        _, body_create = _call("POST", "/merchants", GOOD_MERCHANT)
        merchant_id = body_create["id"]

        # Invocación 2: eliminar
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        status_del, _ = _call("DELETE", f"/merchants/{merchant_id}")
        assert status_del == 204

        # Invocación 3: consultar — debe ser 404
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        status_get, _ = _call("GET", f"/merchants/{merchant_id}")
        assert status_get == 404

        handler.reset_service(None)

    def test_updated_merchant_reflects_in_subsequent_invocation(self):
        """Una modificación en una invocación es visible en la siguiente."""
        shared_table = FakeDynamoTable()

        # Invocación 1: crear
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        _, body_create = _call("POST", "/merchants", GOOD_MERCHANT)
        merchant_id = body_create["id"]

        # Invocación 2: modificar
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        status_put, _ = _call("PUT", f"/merchants/{merchant_id}", {"status": "inactive"})
        assert status_put == 200

        # Invocación 3: consultar — debe reflejar el cambio
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        status_get, body_get = _call("GET", f"/merchants/{merchant_id}")
        assert status_get == 200
        assert body_get["status"] == "inactive"

        handler.reset_service(None)

    def test_list_across_invocations(self):
        """Los comercios creados en una invocación aparecen en el listado de la siguiente."""
        shared_table = FakeDynamoTable()

        # Invocación 1: crear dos comercios
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        _, m1 = _call("POST", "/merchants", {**GOOD_MERCHANT, "name": "Comercio Alfa"})
        _, m2 = _call("POST", "/merchants", {**GOOD_MERCHANT, "name": "Comercio Beta"})

        # Invocación 2: listar — nueva instancia del handler
        handler.reset_service(_make_service_with_fake_dynamo(shared_table))
        status, body = _call("GET", "/merchants")
        assert status == 200
        ids = {item["id"] for item in body["items"]}
        assert m1["id"] in ids
        assert m2["id"] in ids

        handler.reset_service(None)


# ---------------------------------------------------------------------------
# CA-4: El adaptador en memoria sigue disponible
# ---------------------------------------------------------------------------

class TestInMemoryAdapterStillAvailable:
    """CA-4: El adaptador en memoria funciona sin cambios para pruebas y desarrollo local."""

    @pytest.fixture(autouse=True)
    def setup(self):
        handler.reset_service(MerchantService(InMemoryMerchantRepository()))
        yield
        handler.reset_service(None)

    def test_memory_backend_create_and_get(self):
        status, body = _call("POST", "/merchants", GOOD_MERCHANT)
        assert status == 201
        mid = body["id"]
        status2, body2 = _call("GET", f"/merchants/{mid}")
        assert status2 == 200
        assert body2 == body

    def test_memory_backend_is_default(self, monkeypatch):
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        from merchants_api.adapters import build_repository
        repo = build_repository()
        assert isinstance(repo, InMemoryMerchantRepository)

    def test_memory_backend_explicit_env(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "memory")
        from merchants_api.adapters import build_repository
        repo = build_repository()
        assert isinstance(repo, InMemoryMerchantRepository)

    def test_memory_backend_isolation_between_instances(self):
        """Dos instancias InMemoryMerchantRepository son independientes entre sí."""
        repo_a = InMemoryMerchantRepository()
        repo_b = InMemoryMerchantRepository()
        svc_a = MerchantService(repo_a)
        svc_b = MerchantService(repo_b)

        created = svc_a.create({"name": "Solo en A", "mcc": "5411", "country": "AR"})
        assert svc_b.get(created.id) is None

    def test_memory_backend_full_crud(self):
        """CRUD completo con el adaptador en memoria."""
        # Crear
        status, body = _call("POST", "/merchants", GOOD_MERCHANT)
        assert status == 201
        mid = body["id"]

        # Listar
        status, body = _call("GET", "/merchants")
        assert status == 200
        assert any(m["id"] == mid for m in body["items"])

        # Modificar
        status, body = _call("PUT", f"/merchants/{mid}", {"status": "inactive"})
        assert status == 200
        assert body["status"] == "inactive"

        # Eliminar
        status, _ = _call("DELETE", f"/merchants/{mid}")
        assert status == 204

        # Verificar eliminación
        status, _ = _call("GET", f"/merchants/{mid}")
        assert status == 404
