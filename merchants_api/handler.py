"""Handler AWS Lambda para API Gateway (proxy REST v1 o HTTP API v2).

Handler de Lambda:  merchants_api.handler.lambda_handler

Rutas:
  GET    /merchants            lista comercios (?limit=N, máx. 100)
  POST   /merchants            alta
  GET    /merchants/{id}       consulta
  PUT    /merchants/{id}       modificación parcial
  DELETE /merchants/{id}       baja
  GET    /health               estado del servicio y del adaptador de persistencia
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Any

from .adapters import build_repository
from .domain import is_valid_id, validate
from .service import MerchantService

MAX_BODY_BYTES = 10_000

_service: MerchantService | None = None


def get_service() -> MerchantService:
    """Un servicio por instancia de Lambda (reutiliza conexiones entre invocaciones)."""
    global _service
    if _service is None:
        _service = MerchantService(build_repository())
    return _service


def reset_service(service: MerchantService | None = None) -> None:
    """Para pruebas: reemplaza el servicio (o lo descarta para que se vuelva a construir)."""
    global _service
    _service = service


def _response(status: int, body: Any = None) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": "" if body is None else json.dumps(body, ensure_ascii=False),
    }


def _route(event: dict[str, Any]) -> tuple[str, list[str]]:
    http = (event.get("requestContext") or {}).get("http") or {}
    method = str(http.get("method") or event.get("httpMethod") or "GET").upper()
    path = str(event.get("rawPath") or event.get("path") or "/")
    return method, [p for p in path.split("/") if p]


def _body(event: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None, _response(400, {"error": "cuerpo base64 inválido"})
    if len(raw.encode("utf-8")) > MAX_BODY_BYTES:
        return None, _response(413, {"error": "cuerpo demasiado grande"})
    try:
        return (json.loads(raw) if raw else None), None
    except json.JSONDecodeError:
        return None, _response(400, {"error": "el cuerpo debe ser JSON válido"})


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    method, parts = _route(event)

    if parts == ["health"] and method == "GET":
        return _response(200, {"status": "ok", "storage": os.environ.get("STORAGE_BACKEND", "memory")})

    if not parts or parts[0] != "merchants" or len(parts) > 2:
        return _response(404, {"error": "ruta no encontrada"})

    try:
        service = get_service()
    except NotImplementedError as exc:
        return _response(503, {"error": "persistencia no disponible", "detail": str(exc)})

    if len(parts) == 1:
        if method == "GET":
            params = event.get("queryStringParameters") or {}
            try:
                limit = int(params.get("limit", 50))
            except (TypeError, ValueError):
                return _response(400, {"error": "limit debe ser un número"})
            return _response(200, {"items": [m.to_dict() for m in service.list(limit)]})
        if method == "POST":
            data, error = _body(event)
            if error:
                return error
            fields, errors = validate(data)
            if errors:
                return _response(400, {"error": "solicitud inválida", "details": errors})
            return _response(201, service.create(fields).to_dict())
        return _response(405, {"error": "método no permitido"})

    merchant_id = parts[1]
    if not is_valid_id(merchant_id):
        return _response(404, {"error": "comercio no encontrado"})
    if method == "GET":
        merchant = service.get(merchant_id)
        return _response(200, merchant.to_dict()) if merchant else _response(404, {"error": "comercio no encontrado"})
    if method == "PUT":
        data, error = _body(event)
        if error:
            return error
        fields, errors = validate(data, partial=True)
        if errors:
            return _response(400, {"error": "solicitud inválida", "details": errors})
        merchant = service.update(merchant_id, fields)
        return _response(200, merchant.to_dict()) if merchant else _response(404, {"error": "comercio no encontrado"})
    if method == "DELETE":
        return _response(204) if service.delete(merchant_id) else _response(404, {"error": "comercio no encontrado"})
    return _response(405, {"error": "método no permitido"})
