"""Pruebas de la validación de unicidad nombre+país en el alta de comercios.

Cubren todos los criterios de aceptación del requerimiento:
  CA-1  Alta duplicada (mismo nombre, mismo país) → 409 con mensaje claro.
  CA-2  La comparación no distingue mayúsculas ni espacios extremos.
  CA-3  El mismo nombre en otro país sí se permite → 201.
  CA-4  Las altas sin duplicados siguen funcionando igual → 201.

También cubren:
  - DuplicateMerchantError en domain.py.
  - find_by_name_country en InMemoryMerchantRepository.
  - find_by_name_country en DynamoDBMerchantRepository (con tabla falsa).
  - MerchantService.create() lanza DuplicateMerchantError cuando hay colisión.

No usan red ni AWS real.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from merchants_api import handler
from merchants_api.adapters.dynamodb import DynamoDBMerchantRepository
from merchants_api.adapters.memory import InMemoryMerchantRepository
from merchants_api.domain import DuplicateMerchantError, Merchant, now_iso
from merchants_api.service import MerchantService


# ---------------------------------------------------------------------------
# Tabla falsa en memoria compatible con DynamoDBMerchantRepository
# (misma interfaz que FakeDynamoTable en test_dynamodb_adapter.py)
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
# Fixtures
# ---------------------------------------------------------------------------

GOOD = {"name": "Panadería La Esquina", "mcc": "5462", "country": "AR"}


@pytest.fixture()
def memory_repo() -> InMemoryMerchantRepository:
    return InMemoryMerchantRepository()


@pytest.fixture()
def memory_service(memory_repo: InMemoryMerchantRepository) -> MerchantService:
    return MerchantService(memory_repo)


@pytest.fixture()
def fake_dynamo_table() -> FakeDynamoTable:
    return FakeDynamoTable()


@pytest.fixture()
def dynamo_repo(fake_dynamo_table: FakeDynamoTable) -> DynamoDBMerchantRepository:
    return DynamoDBMerchantRepository(table_name="merchants-table", _table=fake_dynamo_table)


@pytest.fixture()
def dynamo_service(dynamo_repo: DynamoDBMerchantRepository) -> MerchantService:
    return MerchantService(dynamo_repo)


@pytest.fixture(autouse=True)
def fresh_handler_service():
    """Cada prueba del handler arranca con un repositorio en memoria limpio."""
    handler.reset_service(MerchantService(InMemoryMerchantRepository()))
    yield
    handler.reset_service(None)


def _call(method: str, path: str, body: Any = None, query: dict | None = None) -> tuple[int, Any]:
    event: dict[str, Any] = {
        "body": json.dumps(body) if isinstance(body, (dict, list)) else body,
        "queryStringParameters": query,
        "path": path,
        "httpMethod": method,
    }
    result = handler.lambda_handler(event)
    return result["statusCode"], (json.loads(result["body"]) if result["body"] else None)


def _merchant(name: str = "Comercio Test", country: str = "AR") -> Merchant:
    ts = now_iso()
    return Merchant(
        id="mer_aabbccddeeff",
        name=name,
        mcc="5411",
        country=country,
        status="active",
        created_at=ts,
        updated_at=ts,
    )


# ===========================================================================
# CA-1: Alta duplicada → 409 con mensaje claro
# ===========================================================================

class TestDuplicateReturns409:
    """CA-1: mismo nombre y país → 409."""

    def test_handler_duplicate_returns_409(self):
        """El handler responde 409 cuando ya existe un comercio con el mismo nombre y país."""
        status1, _ = _call("POST", "/merchants", GOOD)
        assert status1 == 201

        status2, body2 = _call("POST", "/merchants", GOOD)
        assert status2 == 409
        assert "error" in body2

    def test_handler_409_message_is_clear(self):
        """El mensaje de error del 409 menciona el conflicto de nombre y país."""
        _call("POST", "/merchants", GOOD)
        _, body = _call("POST", "/merchants", GOOD)
        assert body["error"] == "ya existe un comercio con ese nombre en ese país"

    def test_service_raises_duplicate_merchant_error(self, memory_service: MerchantService):
        """MerchantService.create() lanza DuplicateMerchantError en colisión."""
        memory_service.create(GOOD)
        with pytest.raises(DuplicateMerchantError):
            memory_service.create(GOOD)

    def test_duplicate_merchant_error_carries_country(self, memory_service: MerchantService):
        """DuplicateMerchantError expone el country del conflicto."""
        memory_service.create(GOOD)
        with pytest.raises(DuplicateMerchantError) as exc_info:
            memory_service.create(GOOD)
        assert exc_info.value.country == GOOD["country"]

    def test_dynamo_service_raises_duplicate_merchant_error(self, dynamo_service: MerchantService):
        """MerchantService con DynamoDB también lanza DuplicateMerchantError."""
        dynamo_service.create(GOOD)
        with pytest.raises(DuplicateMerchantError):
            dynamo_service.create(GOOD)


# ===========================================================================
# CA-2: Comparación sin distinción de mayúsculas ni espacios extremos
# ===========================================================================

class TestNameNormalization:
    """CA-2: strip().lower() en la comparación."""

    @pytest.mark.parametrize("variant", [
        "PANADERÍA LA ESQUINA",
        "panadería la esquina",
        "  Panadería La Esquina  ",
        "  PANADERÍA LA ESQUINA  ",
        "Panadería La Esquina",   # igual al original
    ])
    def test_handler_case_and_spaces_are_normalized(self, variant: str):
        """Variantes de mayúsculas y espacios extremos del mismo nombre → 409."""
        _call("POST", "/merchants", GOOD)
        status, body = _call("POST", "/merchants", {**GOOD, "name": variant})
        assert status == 409, f"Se esperaba 409 para variante {variant!r}, body={body}"

    @pytest.mark.parametrize("variant", [
        "PANADERÍA LA ESQUINA",
        "panadería la esquina",
        "  Panadería La Esquina  ",
    ])
    def test_memory_find_by_name_country_normalizes(
        self, memory_repo: InMemoryMerchantRepository, variant: str
    ):
        """InMemoryMerchantRepository.find_by_name_country normaliza correctamente."""
        m = _merchant(name="Panadería La Esquina", country="AR")
        memory_repo.put(m)
        result = memory_repo.find_by_name_country(variant, "AR")
        assert result is not None, f"Debería encontrar el comercio con variante {variant!r}"

    @pytest.mark.parametrize("variant", [
        "PANADERÍA LA ESQUINA",
        "panadería la esquina",
        "  Panadería La Esquina  ",
    ])
    def test_dynamo_find_by_name_country_normalizes(
        self, dynamo_repo: DynamoDBMerchantRepository, variant: str
    ):
        """DynamoDBMerchantRepository.find_by_name_country normaliza correctamente."""
        dynamo_repo.put(_merchant(name="Panadería La Esquina", country="AR"))
        result = dynamo_repo.find_by_name_country(variant, "AR")
        assert result is not None, f"Debería encontrar el comercio con variante {variant!r}"

    def test_memory_find_returns_none_when_no_match(self, memory_repo: InMemoryMerchantRepository):
        """find_by_name_country devuelve None cuando no hay coincidencia."""
        m = _merchant(name="Panadería La Esquina", country="AR")
        memory_repo.put(m)
        assert memory_repo.find_by_name_country("Otro Comercio", "AR") is None

    def test_dynamo_find_returns_none_when_no_match(self, dynamo_repo: DynamoDBMerchantRepository):
        """find_by_name_country en DynamoDB devuelve None cuando no hay coincidencia."""
        dynamo_repo.put(_merchant(name="Panadería La Esquina", country="AR"))
        assert dynamo_repo.find_by_name_country("Otro Comercio", "AR") is None


# ===========================================================================
# CA-3: El mismo nombre en otro país sí se permite
# ===========================================================================

class TestSameNameDifferentCountryAllowed:
    """CA-3: mismo nombre, distinto país → 201."""

    def test_handler_same_name_different_country_is_201(self):
        """El mismo nombre en otro país no es duplicado."""
        status1, _ = _call("POST", "/merchants", {**GOOD, "country": "AR"})
        assert status1 == 201

        status2, body2 = _call("POST", "/merchants", {**GOOD, "country": "UY"})
        assert status2 == 201, f"Se esperaba 201 para otro país, body={body2}"

    def test_handler_same_name_different_country_creates_distinct_ids(self):
        """Dos comercios con el mismo nombre en distintos países tienen IDs distintos."""
        _, m_ar = _call("POST", "/merchants", {**GOOD, "country": "AR"})
        _, m_uy = _call("POST", "/merchants", {**GOOD, "country": "UY"})
        assert m_ar["id"] != m_uy["id"]

    def test_memory_find_by_name_country_respects_country(self, memory_repo: InMemoryMerchantRepository):
        """find_by_name_country no confunde países distintos."""
        m_ar = _merchant(name="Acme", country="AR")
        m_uy = Merchant(
            id="mer_112233445566",
            name="Acme",
            mcc="5411",
            country="UY",
            status="active",
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        memory_repo.put(m_ar)
        memory_repo.put(m_uy)

        result_ar = memory_repo.find_by_name_country("Acme", "AR")
        result_uy = memory_repo.find_by_name_country("Acme", "UY")
        result_br = memory_repo.find_by_name_country("Acme", "BR")

        assert result_ar is not None and result_ar.country == "AR"
        assert result_uy is not None and result_uy.country == "UY"
        assert result_br is None

    def test_dynamo_find_by_name_country_respects_country(self, dynamo_repo: DynamoDBMerchantRepository):
        """DynamoDB find_by_name_country no confunde países distintos."""
        m_ar = _merchant(name="Acme", country="AR")
        m_uy = Merchant(
            id="mer_112233445566",
            name="Acme",
            mcc="5411",
            country="UY",
            status="active",
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        dynamo_repo.put(m_ar)
        dynamo_repo.put(m_uy)

        assert dynamo_repo.find_by_name_country("Acme", "AR") is not None
        assert dynamo_repo.find_by_name_country("Acme", "UY") is not None
        assert dynamo_repo.find_by_name_country("Acme", "BR") is None

    def test_service_same_name_different_country_does_not_raise(self, memory_service: MerchantService):
        """MerchantService no lanza error para el mismo nombre en distinto país."""
        memory_service.create({**GOOD, "country": "AR"})
        # No debe lanzar DuplicateMerchantError
        result = memory_service.create({**GOOD, "country": "UY"})
        assert result.country == "UY"


# ===========================================================================
# CA-4: Las altas sin duplicados siguen funcionando igual
# ===========================================================================

class TestNoDuplicateStillWorks:
    """CA-4: altas sin duplicados → 201, comportamiento sin cambios."""

    def test_first_create_returns_201(self):
        status, body = _call("POST", "/merchants", GOOD)
        assert status == 201
        assert body["id"].startswith("mer_")
        assert body["name"] == GOOD["name"].strip()
        assert body["status"] == "active"

    def test_different_names_same_country_both_succeed(self):
        status1, _ = _call("POST", "/merchants", {**GOOD, "name": "Comercio Alfa"})
        status2, _ = _call("POST", "/merchants", {**GOOD, "name": "Comercio Beta"})
        assert status1 == 201
        assert status2 == 201

    def test_create_after_delete_succeeds(self):
        """Tras eliminar un comercio, se puede crear otro con el mismo nombre y país."""
        _, created = _call("POST", "/merchants", GOOD)
        _call("DELETE", f"/merchants/{created['id']}")

        status, body = _call("POST", "/merchants", GOOD)
        assert status == 201, f"Debería poder crear tras borrar, body={body}"

    def test_memory_find_by_name_country_empty_repo(self, memory_repo: InMemoryMerchantRepository):
        """find_by_name_country sobre repositorio vacío devuelve None."""
        assert memory_repo.find_by_name_country("Cualquier Nombre", "AR") is None

    def test_dynamo_find_by_name_country_empty_table(self, dynamo_repo: DynamoDBMerchantRepository):
        """find_by_name_country sobre tabla vacía devuelve None."""
        assert dynamo_repo.find_by_name_country("Cualquier Nombre", "AR") is None

    def test_service_create_returns_merchant_with_correct_fields(self, memory_service: MerchantService):
        """create() devuelve un Merchant con los campos correctos."""
        m = memory_service.create(GOOD)
        assert m.name == GOOD["name"].strip()
        assert m.mcc == GOOD["mcc"]
        assert m.country == GOOD["country"]
        assert m.status == "active"
        assert m.id.startswith("mer_")


# ===========================================================================
# Casos borde
# ===========================================================================

class TestEdgeCases:
    """Casos borde adicionales."""

    def test_duplicate_error_message_is_a_string(self):
        """DuplicateMerchantError tiene un mensaje de texto legible."""
        err = DuplicateMerchantError("Acme", "AR")
        assert "Acme" in str(err) or "AR" in str(err)

    def test_duplicate_after_multiple_creates(self):
        """El 409 se detecta aunque haya otros comercios en la tabla."""
        _call("POST", "/merchants", {**GOOD, "name": "Comercio Uno"})
        _call("POST", "/merchants", {**GOOD, "name": "Comercio Dos"})
        _call("POST", "/merchants", {**GOOD, "name": "Comercio Tres"})

        # Intentar duplicar el segundo
        status, body = _call("POST", "/merchants", {**GOOD, "name": "Comercio Dos"})
        assert status == 409

    def test_name_with_only_spaces_stripped_is_duplicate(self):
        """'  Acme  ' y 'Acme' se tratan como el mismo nombre."""
        _call("POST", "/merchants", {**GOOD, "name": "Acme"})
        status, _ = _call("POST", "/merchants", {**GOOD, "name": "  Acme  "})
        assert status == 409

    def test_409_does_not_create_the_merchant(self):
        """Tras un 409, el comercio duplicado no se crea (la lista no crece)."""
        _call("POST", "/merchants", GOOD)
        _call("POST", "/merchants", GOOD)  # 409

        _, list_body = _call("GET", "/merchants")
        names = [m["name"] for m in list_body["items"]]
        # Solo debe haber una entrada con ese nombre
        assert names.count(GOOD["name"]) == 1

    def test_dynamo_find_by_name_country_with_handler(self):
        """El handler con DynamoDB también responde 409 en duplicado."""
        fake_table = FakeDynamoTable()
        repo = DynamoDBMerchantRepository(table_name="merchants-table", _table=fake_table)
        handler.reset_service(MerchantService(repo))

        status1, _ = _call("POST", "/merchants", GOOD)
        assert status1 == 201

        status2, body2 = _call("POST", "/merchants", GOOD)
        assert status2 == 409
        assert body2["error"] == "ya existe un comercio con ese nombre en ese país"

    def test_memory_find_by_name_country_returns_none_on_empty(self, memory_repo):
        """find_by_name_country en repo vacío siempre devuelve None."""
        assert memory_repo.find_by_name_country("", "AR") is None
        assert memory_repo.find_by_name_country("Cualquier cosa", "XX") is None
