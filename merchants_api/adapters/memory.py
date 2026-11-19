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
