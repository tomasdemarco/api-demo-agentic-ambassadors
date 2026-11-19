"""Pruebas del adaptador DynamoDB.

No usan red ni AWS real. Se inyecta una tabla falsa en memoria que simula
las operaciones de boto3 Resource (get_item, put_item, delete_item, scan)
incluyendo el comportamiento de ReturnValues='ALL_OLD' en delete_item.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from merchants_api.adapters.dynamodb import DynamoDBMerchantRepository
from merchants_api.domain import Merchant, now_iso


# ---------------------------------------------------------------------------
# Tabla falsa en memoria que imita la interfaz de boto3 DynamoDB Table
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

@pytest.fixture()
def fake_table() -> FakeDynamoTable:
    return FakeDynamoTable()


@pytest.fixture()
def repo(fake_table: FakeDynamoTable) -> DynamoDBMerchantRepository:
    return DynamoDBMerchantRepository(table_name="merchants-table", _table=fake_table)


def _merchant(suffix: str = "aabbccddeeff") -> Merchant:
    ts = now_iso()
    return Merchant(
        id=f"mer_{suffix[:12]}",
        name="Comercio Test",
        mcc="5411",
        country="AR",
        status="active",
        created_at=ts,
        updated_at=ts,
    )


# ---------------------------------------------------------------------------
# Criterio de aceptación: alta y consulta (persistencia real simulada)
# ---------------------------------------------------------------------------

def test_put_and_get_roundtrip(repo: DynamoDBMerchantRepository) -> None:
    """Un comercio guardado con put() se puede recuperar con get()."""
    m = _merchant()
    repo.put(m)
    result = repo.get(m.id)
    assert result == m


def test_get_nonexistent_returns_none(repo: DynamoDBMerchantRepository) -> None:
    """get() devuelve None si el comercio no existe."""
    assert repo.get("mer_000000000000") is None


# ---------------------------------------------------------------------------
# Criterio de aceptación: listado
# ---------------------------------------------------------------------------

def test_list_returns_all_merchants(repo: DynamoDBMerchantRepository) -> None:
    """list() devuelve todos los comercios almacenados."""
    m1 = _merchant("aabbccddeeff")
    m2 = _merchant("112233445566")
    repo.put(m1)
    repo.put(m2)
    items = repo.list()
    assert {i.id for i in items} == {m1.id, m2.id}


def test_list_respects_limit(repo: DynamoDBMerchantRepository) -> None:
    """list(limit=1) devuelve como máximo 1 comercio."""
    repo.put(_merchant("aabbccddeeff"))
    repo.put(_merchant("112233445566"))
    items = repo.list(limit=1)
    assert len(items) == 1


def test_list_empty_table(repo: DynamoDBMerchantRepository) -> None:
    """list() sobre tabla vacía devuelve lista vacía."""
    assert repo.list() == []


# ---------------------------------------------------------------------------
# Criterio de aceptación: baja
# ---------------------------------------------------------------------------

def test_delete_existing_returns_true(repo: DynamoDBMerchantRepository) -> None:
    """delete() devuelve True cuando el comercio existía."""
    m = _merchant()
    repo.put(m)
    assert repo.delete(m.id) is True


def test_delete_removes_merchant(repo: DynamoDBMerchantRepository) -> None:
    """Tras delete(), get() devuelve None."""
    m = _merchant()
    repo.put(m)
    repo.delete(m.id)
    assert repo.get(m.id) is None


def test_delete_nonexistent_returns_false(repo: DynamoDBMerchantRepository) -> None:
    """delete() devuelve False cuando el comercio no existía."""
    assert repo.delete("mer_000000000000") is False


# ---------------------------------------------------------------------------
# Criterio de aceptación: modificación (put reemplaza)
# ---------------------------------------------------------------------------

def test_put_overwrites_existing(repo: DynamoDBMerchantRepository) -> None:
    """put() con el mismo id reemplaza el comercio existente."""
    m = _merchant()
    repo.put(m)
    updated = m.updated({"status": "inactive"})
    repo.put(updated)
    result = repo.get(m.id)
    assert result is not None
    assert result.status == "inactive"
    assert result.id == m.id


# ---------------------------------------------------------------------------
# Mapeo de claves: 'id' del dominio ↔ 'merchant_id' en DynamoDB
# ---------------------------------------------------------------------------

def test_dynamodb_pk_is_merchant_id(fake_table: FakeDynamoTable) -> None:
    """El ítem almacenado en DynamoDB usa 'merchant_id', no 'id'."""
    repo = DynamoDBMerchantRepository(table_name="merchants-table", _table=fake_table)
    m = _merchant()
    repo.put(m)
    # Acceso directo a la tabla falsa para verificar el nombre de la clave
    stored_keys = list(fake_table._items.values())[0].keys()
    assert "merchant_id" in stored_keys
    assert "id" not in stored_keys


# ---------------------------------------------------------------------------
# Integración con build_repository(): el backend 'dynamodb' se registra
# ---------------------------------------------------------------------------

def test_build_repository_dynamodb_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_repository() instancia DynamoDBMerchantRepository cuando STORAGE_BACKEND=dynamodb."""
    monkeypatch.setenv("STORAGE_BACKEND", "dynamodb")
    monkeypatch.setenv("TABLE_NAME", "merchants-table")

    # Parcheamos boto3.resource para que no intente conectarse a AWS
    import unittest.mock as mock
    import merchants_api.adapters.dynamodb as dyn_mod

    fake_table = FakeDynamoTable()
    fake_resource = mock.MagicMock()
    fake_resource.Table.return_value = fake_table

    with mock.patch("boto3.resource", return_value=fake_resource):
        from merchants_api.adapters import build_repository
        repo = build_repository()

    assert isinstance(repo, DynamoDBMerchantRepository)
    fake_resource.Table.assert_called_once_with("merchants-table")


def test_build_repository_dynamodb_missing_table_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_repository() lanza KeyError si TABLE_NAME no está definida."""
    monkeypatch.setenv("STORAGE_BACKEND", "dynamodb")
    monkeypatch.delenv("TABLE_NAME", raising=False)

    import unittest.mock as mock

    with mock.patch("boto3.resource"):
        from merchants_api.adapters import build_repository
        with pytest.raises(KeyError):
            build_repository()


# ---------------------------------------------------------------------------
# La implementación real (con boto3 real simulado) también se prueba
# ---------------------------------------------------------------------------

def test_real_implementation_uses_boto3_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    """DynamoDBMerchantRepository sin _table llama a boto3.resource('dynamodb').Table(name)."""
    import unittest.mock as mock

    fake_table = FakeDynamoTable()
    fake_resource = mock.MagicMock()
    fake_resource.Table.return_value = fake_table

    with mock.patch("boto3.resource", return_value=fake_resource) as mock_boto3:
        repo = DynamoDBMerchantRepository(table_name="my-table")

    mock_boto3.assert_called_once_with("dynamodb")
    fake_resource.Table.assert_called_once_with("my-table")

    # Verificar que las operaciones funcionan sobre la tabla inyectada
    m = _merchant()
    repo.put(m)
    assert repo.get(m.id) == m


def test_real_implementation_delete_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    """La implementación real devuelve True al borrar un ítem existente."""
    import unittest.mock as mock

    fake_table = FakeDynamoTable()
    fake_resource = mock.MagicMock()
    fake_resource.Table.return_value = fake_table

    with mock.patch("boto3.resource", return_value=fake_resource):
        repo = DynamoDBMerchantRepository(table_name="my-table")

    m = _merchant()
    repo.put(m)
    assert repo.delete(m.id) is True
    assert repo.get(m.id) is None


def test_real_implementation_delete_nonexistent(monkeypatch: pytest.MonkeyPatch) -> None:
    """La implementación real devuelve False al borrar un ítem inexistente."""
    import unittest.mock as mock

    fake_table = FakeDynamoTable()
    fake_resource = mock.MagicMock()
    fake_resource.Table.return_value = fake_table

    with mock.patch("boto3.resource", return_value=fake_resource):
        repo = DynamoDBMerchantRepository(table_name="my-table")

    assert repo.delete("mer_000000000000") is False
