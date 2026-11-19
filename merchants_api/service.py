"""Casos de uso del ABM de comercios. Solo conoce el puerto, no la tecnología de persistencia."""

from __future__ import annotations

from .domain import Merchant, new_id, now_iso
from .ports import MerchantRepository

MAX_LIST = 100


class MerchantService:
    def __init__(self, repository: MerchantRepository) -> None:
        self.repository = repository

    def create(self, fields: dict[str, str]) -> Merchant:
        ts = now_iso()
        merchant = Merchant(id=new_id(), name=fields["name"], mcc=fields["mcc"], country=fields["country"],
                            status=fields.get("status", "active"), created_at=ts, updated_at=ts)
        self.repository.put(merchant)
        return merchant

    def get(self, merchant_id: str) -> Merchant | None:
        return self.repository.get(merchant_id)

    def list(self, limit: int = 50) -> list[Merchant]:
        return self.repository.list(max(1, min(limit, MAX_LIST)))

    def update(self, merchant_id: str, changes: dict[str, str]) -> Merchant | None:
        current = self.repository.get(merchant_id)
        if current is None:
            return None
        updated = current.updated(changes)
        self.repository.put(updated)
        return updated

    def delete(self, merchant_id: str) -> bool:
        return self.repository.delete(merchant_id)
