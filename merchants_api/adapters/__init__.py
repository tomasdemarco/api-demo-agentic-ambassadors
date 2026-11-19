"""Adaptadores de persistencia. Se elige uno con la variable de entorno STORAGE_BACKEND.

  memory    InMemoryMerchantRepository  (por defecto; pruebas y desarrollo local)
  dynamodb  DynamoDBMerchantRepository  (producción en AWS; requiere TABLE_NAME)
"""

from __future__ import annotations

import os

from ..ports import MerchantRepository
from .memory import InMemoryMerchantRepository


def build_repository() -> MerchantRepository:
    backend = os.environ.get("STORAGE_BACKEND", "memory").strip().lower()
    if backend == "memory":
        return InMemoryMerchantRepository()
    if backend == "dynamodb":
        from .dynamodb import DynamoDBMerchantRepository  # noqa: PLC0415

        table_name = os.environ["TABLE_NAME"]
        return DynamoDBMerchantRepository(table_name=table_name)
    raise NotImplementedError(f"no hay adaptador de persistencia para STORAGE_BACKEND={backend!r}")
