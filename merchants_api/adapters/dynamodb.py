"""Adaptador DynamoDB para MerchantRepository.

Usa boto3 (disponible en el runtime de Lambda; no se agrega a requirements).
El cliente boto3 se inicializa a nivel de módulo para reutilizarlo entre
invocaciones y reducir el cold start (ver riesgo documentado en el diseño).

Tabla esperada:
  - Partition key: merchant_id (String)
  - Modo de facturación: PAY_PER_REQUEST
  - SSE + PITR habilitados (configuración de infraestructura, no de código)

Variable de entorno requerida:
  TABLE_NAME  — nombre de la tabla DynamoDB (inyectado por infraestructura, ARQ-02)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..domain import Merchant

if TYPE_CHECKING:
    # Solo para type-checking estático; en runtime se importa dentro del __init__
    import boto3  # noqa: F401


class DynamoDBMerchantRepository:
    """Implementación de MerchantRepository sobre DynamoDB."""

    def __init__(self, table_name: str, *, _table: Any = None) -> None:
        """
        Args:
            table_name: Nombre de la tabla DynamoDB (valor de TABLE_NAME).
            _table: Inyección de dependencia para pruebas (tabla falsa en memoria).
                    Si es None se construye el recurso real con boto3.
        """
        self._table_name = table_name
        if _table is not None:
            self._table = _table
        else:
            # boto3 se importa aquí para que no falle en entornos sin AWS
            # cuando se usa la inyección de dependencia en pruebas.
            import boto3  # noqa: PLC0415

            dynamodb = boto3.resource("dynamodb")
            self._table = dynamodb.Table(table_name)

    # ------------------------------------------------------------------
    # MerchantRepository protocol
    # ------------------------------------------------------------------

    def get(self, merchant_id: str) -> Merchant | None:
        response = self._table.get_item(Key={"merchant_id": merchant_id})
        item = response.get("Item")
        if item is None:
            return None
        return self._from_item(item)

    def list(self, limit: int = 50) -> list[Merchant]:
        # Scan con Limit: DynamoDB puede devolver menos ítems si los ítems
        # evaluados superan 1 MB antes de alcanzar el límite; para el volumen
        # esperado en esta etapa es suficiente (ver riesgo en el diseño).
        response = self._table.scan(Limit=limit)
        return [self._from_item(item) for item in response.get("Items", [])]

    def put(self, merchant: Merchant) -> None:
        item = merchant.to_dict()
        # DynamoDB usa 'merchant_id' como PK; el dominio lo llama 'id'
        item["merchant_id"] = item.pop("id")
        self._table.put_item(Item=item)

    def delete(self, merchant_id: str) -> bool:
        """Elimina el ítem y devuelve True si existía, False si no."""
        response = self._table.delete_item(
            Key={"merchant_id": merchant_id},
            ReturnValues="ALL_OLD",
        )
        return "Attributes" in response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _from_item(item: dict[str, Any]) -> Merchant:
        """Convierte un ítem de DynamoDB al dataclass Merchant."""
        data = dict(item)
        # Renombrar la PK de DynamoDB al campo 'id' del dominio
        data["id"] = data.pop("merchant_id")
        return Merchant.from_dict(data)
