"""Adaptadores de persistencia. Se elige uno con la variable de entorno STORAGE_BACKEND.

  memory   InMemoryMerchantRepository (por defecto; pruebas y desarrollo local)

Todavía no hay adaptador para una base de datos real: lo define Arquitectura según los
lineamientos de plataforma.
"""

from __future__ import annotations

import os

from ..ports import MerchantRepository
from .memory import InMemoryMerchantRepository


def build_repository() -> MerchantRepository:
    backend = os.environ.get("STORAGE_BACKEND", "memory").strip().lower()
    if backend == "memory":
        return InMemoryMerchantRepository()
    raise NotImplementedError(f"no hay adaptador de persistencia para STORAGE_BACKEND={backend!r}")
