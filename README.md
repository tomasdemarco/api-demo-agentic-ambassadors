# merchants-api

ABM (CRUD) de comercios adheridos, con datos sintéticos. Es el código de partida de la demo: está listo como lógica de negocio, pero **no tiene base de datos**.

## Arquitectura

Puertos y adaptadores:

| Capa | Archivo | Qué hace |
|---|---|---|
| Dominio | `merchants_api/domain.py` | Comercio y validación de entrada |
| Puerto | `merchants_api/ports.py` | `MerchantRepository`: lo que el dominio necesita para persistir |
| Casos de uso | `merchants_api/service.py` | Alta, baja, modificación y consulta, usando solo el puerto |
| Adaptadores | `merchants_api/adapters/` | Hoy solo `memory` (pruebas y desarrollo local) |
| HTTP | `merchants_api/handler.py` | Handler de Lambda para API Gateway: `merchants_api.handler.lambda_handler` |

El adaptador se elige con `STORAGE_BACKEND`. Con cualquier valor distinto de `memory`, la API responde 503: **falta el adaptador de la base de datos que defina Arquitectura**.

## API

| Método | Ruta | Respuesta |
|---|---|---|
| GET | `/merchants?limit=N` | 200 `{"items": [...]}` |
| POST | `/merchants` | 201 con el comercio creado |
| GET | `/merchants/{id}` | 200 o 404 |
| PUT | `/merchants/{id}` | 200 (modificación parcial) o 404 |
| DELETE | `/merchants/{id}` | 204 o 404 |
| GET | `/health` | 200 `{"status": "ok", "storage": "<STORAGE_BACKEND>"}` |

Cuerpo de alta: `{"name": "...", "mcc": "5411", "country": "AR", "status": "active"}` (`status` es opcional).

## Probarlo

Desde `services/merchants_api`:

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q
..\..\.venv\Scripts\python.exe -m merchants_api
```

`smoke.json` describe la prueba de humo que el agente de Despliegue ejecuta contra la URL desplegada.
