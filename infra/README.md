# Especificación de infraestructura — merchants-api

> Generado por el agente Desarrollador. El equipo de Plataforma aplica estos
> valores al crear / actualizar la infraestructura AWS.

## Recursos requeridos

### 1. DynamoDB — `merchants-table` (ARQ-08)

| Parámetro | Valor |
|---|---|
| Nombre de la tabla | `merchants-table` |
| Partition key | `merchant_id` (tipo **String**) |
| Modo de facturación | `PAY_PER_REQUEST` |
| Server-Side Encryption | Habilitado (`AWS_OWNED_KMS`) |
| Point-In-Time Recovery | Habilitado |
| TTL | Sin TTL (registro de negocio permanente) |

### 2. Lambda — `merchants-handler` (ARQ-09)

| Parámetro | Valor |
|---|---|
| Nombre de la función | `merchants-handler` |
| Runtime | `python3.12` |
| Handler | `merchants_api.handler.lambda_handler` |
| Variable de entorno | `STORAGE_BACKEND=dynamodb` |
| Variable de entorno | `TABLE_NAME=merchants-table` |

### 3. IAM Role para la Lambda (ARQ-04 — permisos mínimos)

Acciones permitidas **únicamente** sobre el ARN puntual de `merchants-table`
(sin comodines):

```
dynamodb:GetItem
dynamodb:PutItem
dynamodb:DeleteItem
dynamodb:Scan
```

Política gestionada adicional: `AWSLambdaBasicExecutionRole` (escritura de logs).

### 4. API Gateway REST — `merchants-api` (ARQ-09)

| Parámetro | Valor |
|---|---|
| Nombre | `merchants-api` |
| Tipo de endpoint | `REGIONAL` |
| Integración | Lambda Proxy (`AWS_PROXY`) con `merchants-handler` |
| Recursos | `ANY /{proxy+}` y `ANY /` |
| Stage | `prod` |

### 5. CloudWatch Log Group

| Parámetro | Valor |
|---|---|
| Nombre | `/aws/lambda/merchants-handler` |
| Retención | **14 días** |

> Crear el Log Group **antes** de la Lambda para que Terraform gestione la
> retención; si la Lambda lo crea primero queda con retención indefinida.

### 6. CloudWatch Alarm — `merchants-api-errors-alarm`

| Parámetro | Valor |
|---|---|
| Nombre | `merchants-api-errors-alarm` |
| Métrica | `AWS/Lambda › Errors` (FunctionName=`merchants-handler`) |
| Período | 60 s |
| Estadístico | Sum |
| Umbral | `> 0` en 1 período de evaluación |
| Datos faltantes | `notBreaching` |

## Variables de entorno necesarias en la Lambda

| Variable | Valor | Quién la inyecta |
|---|---|---|
| `STORAGE_BACKEND` | `dynamodb` | Infraestructura (fijo) |
| `TABLE_NAME` | `merchants-table` | Infraestructura (fijo) |

## Notas de operación

- **Cold start**: el cliente `boto3` se inicializa a nivel de módulo en
  `merchants_api/adapters/dynamodb.py` para reutilizarse entre invocaciones.
  El primer arranque puede agregar ~200 ms de latencia; aceptable para este
  volumen.
- **Scan sin paginación completa**: `list()` usa `Scan` con `Limit`. Si los
  ítems evaluados superan 1 MB antes de alcanzar el límite, DynamoDB puede
  devolver menos resultados. Revisar cuando el catálogo crezca.
- **Sin autenticación**: la API queda expuesta sin autorización. Riesgo
  aceptado para QA/demo; revisar antes de producción real.
