"""Adaptador en memoria: para pruebas y desarrollo local. No persiste entre procesos."""

from __future__ import annotations

import threading

from ..domain import Merchant


class InMemoryMerchantRepository:
    def __init__(self) -> None:
        self._items: dict[str, Merchant] = {}
        self._lock = threading.Lock()

    def get(self, merchant_id: str) -> Merchant | None:
        with self._lock:
            return self._items.get(merchant_id)

    def list(self, limit: int = 50) -> list[Merchant]:
        with self._lock:
            return list(self._items.values())[:limit]

    def put(self, merchant: Merchant) -> None:
        with self._lock:
            self._items[merchant.id] = merchant

    def delete(self, merchant_id: str) -> bool:
        with self._lock:
            return self._items.pop(merchant_id, None) is not None

    def find_by_name_country(self, name: str, country: str) -> Merchant | None:
        """Devuelve el primer comercio cuyo nombre normalizado y país coincidan, o None.

        La normalización aplicada es strip().lower(), igual que en el adaptador DynamoDB.
        """
        normalized = name.strip().lower()
        with self._lock:
            for merchant in self._items.values():
                if merchant.name.strip().lower() == normalized and merchant.country == country:
                    return merchant
        return None
