"""Dominio: comercio adherido (datos sintéticos)."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any

STATUSES = ("active", "inactive")
_MCC = re.compile(r"^\d{4}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_ID = re.compile(r"^mer_[0-9a-f]{12}$")
FIELDS = ("name", "mcc", "country", "status")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return f"mer_{uuid.uuid4().hex[:12]}"


def is_valid_id(value: str) -> bool:
    return bool(_ID.fullmatch(value))


@dataclass(frozen=True)
class Merchant:
    id: str
    name: str
    mcc: str
    country: str
    status: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Merchant":
        return cls(**{k: str(data[k]) for k in ("id", *FIELDS, "created_at", "updated_at")})

    def updated(self, changes: dict[str, str]) -> "Merchant":
        return replace(self, **changes, updated_at=now_iso())


def validate(data: Any, partial: bool = False) -> tuple[dict[str, str], dict[str, str]]:
    """Valida el cuerpo de alta (partial=False) o de modificación (partial=True).

    Devuelve (campos, errores). En una modificación solo se validan los campos presentes.
    """
    if not isinstance(data, dict):
        return {}, {"body": "debe ser un objeto JSON"}
    errors: dict[str, str] = {}
    fields: dict[str, str] = {}

    unknown = sorted(set(data) - set(FIELDS))
    if unknown:
        errors["body"] = f"campos no permitidos: {', '.join(unknown)}"

    def check(name: str, ok: bool, message: str) -> None:
        if name not in data:
            if not partial and name != "status":
                errors[name] = "obligatorio"
            return
        value = data[name]
        if not isinstance(value, str) or not ok:
            errors[name] = message
        else:
            fields[name] = value.strip()

    name = data.get("name")
    check("name", isinstance(name, str) and 2 <= len(name.strip()) <= 80, "texto de 2 a 80 caracteres")
    check("mcc", isinstance(data.get("mcc"), str) and bool(_MCC.fullmatch(data.get("mcc", ""))),
          "código MCC de 4 dígitos")
    check("country", isinstance(data.get("country"), str) and bool(_COUNTRY.fullmatch(data.get("country", ""))),
          "código de país ISO de 2 letras mayúsculas")
    check("status", data.get("status") in STATUSES, f"uno de: {', '.join(STATUSES)}")

    if partial and not fields and not errors:
        errors["body"] = "no hay campos para modificar"
    return fields, errors
