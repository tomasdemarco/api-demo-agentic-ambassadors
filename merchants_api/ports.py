"""Puertos: lo que el dominio necesita del exterior, sin depender de una tecnología."""

from __future__ import annotations

from typing import Protocol

from .domain import Merchant


class MerchantRepository(Protocol):
    """Persistencia de comercios. Cada adaptador (memoria, base de datos...) implementa esto."""

    def get(self, merchant_id: str) -> Merchant | None:
        """Devuelve el comercio o None si no existe."""

    def list(self, limit: int = 50) -> list[Merchant]:
        """Devuelve hasta `limit` comercios (sin orden garantizado)."""

    def put(self, merchant: Merchant) -> None:
        """Crea o reemplaza el comercio."""

    def delete(self, merchant_id: str) -> bool:
        """Elimina el comercio. Devuelve False si no existía."""
