# Servidor MCP de Brasaland (`mcps/brasaland_mcp`)

Servidor [Model Context Protocol](https://modelcontextprotocol.io) en Python (FastMCP) que expone la **gestión de tickets**
y la **consulta de inventario** de Brasaland a cualquier cliente MCP (MCP Playground, el agente LangGraph, otros agentes).
La autenticación OAuth 2.1 la hace **MCP Auth** (`mcpauth`), no la capa de auth de FastMCP.

## Transporte elegido: Streamable HTTP, en modo *stateless*

| Criterio | Streamable HTTP (elegido) | stdio |
|---|---|---|
| Clientes | Varios clientes remotos a la vez (Playground, agente, otros) | Un solo cliente local que lanza el proceso |
| Autenticación | **OAuth 2.1 se define sobre HTTP** (Bearer + metadata del recurso protegido) | Solo variables de entorno, sin flujo OAuth |
| Despliegue | Servicio de red detrás de la URL pública de Codespaces | Imposible alcanzarlo desde fuera de la máquina |
| Escalado | `stateless_http=True`: sin sesión en memoria → réplicas detrás de un balanceador | No aplica |

Cada petición lleva su propio `Authorization: Bearer ...` y se valida sola, sin estado de sesión que se pueda secuestrar.
(El transporte SSE clásico está deprecado en la especificación.)

## Ejecutarlo

```bash
cp mcps/brasaland_mcp/.env.example .env      # rellenar (ver "Auth0" abajo) y `set -a; source .env; set +a`
uv sync
python -m mcps.brasaland_mcp --port 8001      # /mcp (protegido), /healthz y /.well-known/oauth-protected-resource/mcp
```
Requiere la API (`services/api`, puerto 8000) en marcha y un usuario de servicio (`MCP_BACKEND_EMAIL/PASSWORD`).
En Codespaces, el puerto **8001** debe tener visibilidad **Public**; la URL pública es la que se usa en Playground.

## Tools (discovery estándar: `tools/list`)

Los nombres de campo, IDs y valores de dominio son **los de las APIs reales** (`services/api`), y una prueba
(`services/api/tests/test_mcp_integration.py`) falla si dejan de coincidir.

| Tool | Scope | Qué hace | Entrada | Salida |
|---|---|---|---|---|
| `incidents_get_ticket` | `tickets:read` | Consulta un ticket | `ticket_id: int` | `Ticket` |
| `incidents_list_tickets` | `tickets:read` | Lista tickets (filtro por estado) | `status?`, `limit` (1-25) | `{total, tickets[Ticket]}` |
| `incidents_create_ticket` | `tickets:write` | Crea un ticket (`POST /api/incidents`) | `title`, `description`, `category` (Queja \| Solicitud \| Fallo operativo), `origin` (customer \| branch \| internal), `branch` (central o una sede) | `Ticket` |
| `incidents_update_ticket_status` | `tickets:write` | Cambia el estado con el ciclo de vida (`PATCH /api/incidents/{id}/status`) | `ticket_id`, `status` (open \| in_progress \| resolved \| discarded) | `Ticket` |
| `inventory_get_stock` | `inventory:read` | Stock por producto (**solo lectura**) | `product_name?`, `product_id?`, `limit` | `{total, products[{id, name, sku, restaurant, current_stock}]}` |

`Ticket` = `{id, title, description, category, origin, branch, status, created_at, updated_at}`. Cada tool publica su
esquema de entrada y salida, sus *annotations* (`readOnlyHint`, ...) y `meta.required_scope`.
Ciclo de vida: `open → in_progress | discarded`, `in_progress → resolved | discarded`; `resolved` y `discarded` son finales.

### Inventario: solo lectura, rechazada **explícitamente**
No es que falte la tool de escritura: el servidor responde `[READ_ONLY_VIOLATION]` si se intenta
(a) invocar una tool de escritura de inventario (`inventory_update_stock`, `update_inventory`, `restock_...`) o
(b) pasar argumentos de escritura (`quantity`, `set_stock`, `delta`, `operation`...) a `inventory_get_stock`. La petición ni
llega al backend; además `InventoryBackend` solo tiene `get()` y no existe ningún scope de escritura de inventario.

## OAuth (MCP Auth) y mínimo privilegio

* `GET /.well-known/oauth-protected-resource/mcp` → *Protected Resource Metadata* (RFC 9728): `resource`, `authorization_servers`, `scopes_supported`.
* Sin token → **401** con `WWW-Authenticate: Bearer error="missing_auth_header", resource_metadata="..."`; así un cliente descubre dónde autenticarse.
* El JWT se valida contra el JWKS del proveedor OIDC: firma, `iss`, `aud` (= `MCP_PUBLIC_URL`) y caducidad.
* **Scopes por tool**: `tickets:read`, `tickets:write`, `inventory:read`. Un token solo con `tickets:read` puede consultar tickets pero no crear ni leer inventario.
* El agente LangGraph solicita **solo scopes de lectura**.
* El MCP se autentica contra el backend con su propia cuenta de servicio; el token del cliente nunca se reenvía.

## Errores (códigos distintos para autenticación, autorización y validación)

| Familia | Dónde | Código / respuesta |
|---|---|---|
| Autenticación | HTTP | **401** `missing_auth_header`, `invalid_auth_header_format`, `invalid_token`, `invalid_issuer`, `invalid_audience`, token caducado |
| Autorización | HTTP / tool | **403** `missing_required_scopes` (scope global) · `[FORBIDDEN_SCOPE]` (falta el scope de esa tool) |
| Solo lectura | tool | `[READ_ONLY_VIOLATION]` |
| Validación | tool | `[VALIDATION_ERROR]` (tipo, rango, valor de dominio, campo desconocido) · `[INVALID_TRANSITION]` |
| Recurso | tool | `[NOT_FOUND]` |
| Backend | tool | `[BACKEND_UNAUTHORIZED]`, `[BACKEND_TIMEOUT]`, `[BACKEND_UNAVAILABLE]`, `[INTERNAL_ERROR]` |

Los mensajes nunca incluyen URLs internas, tokens ni stack traces.

## Logs de auditoría
Una línea JSON por invocación (también las rechazadas) en `MCP_AUDIT_LOG` (`data/logs/mcp-audit.jsonl`) y en el logger
`brasaland.mcp.audit`: `ts, tool, client_id, subject, scopes, outcome, error_code, duration_ms, arguments` (solo
`ticket_id/status/product_id/limit`; **nunca** tokens ni textos libres).

## Auth0 (proveedor OAuth/OIDC)
1. Tenant en Auth0 → **Applications → APIs → Create API**: *Identifier* = `MCP_PUBLIC_URL` (p. ej. `https://<codespace>-8001.app.github.dev/mcp`), algoritmo RS256. En **Permissions** crear `tickets:read`, `tickets:write`, `inventory:read`. En **Settings** activar *Allow Offline Access* (opcional) y, para Playground, **Enable Dynamic Client Registration** (Tenant Settings → Advanced → OIDC Dynamic Application Registration) y marcar la conexión como *domain-level*.
2. **Aplicación del agente**: *Machine to Machine*, autorizada para esa API con **solo** `tickets:read` e `inventory:read` → `AGENT_MCP_CLIENT_ID/SECRET`.
3. **Aplicación para Playground** (si no usa registro dinámico): *Regular Web App/SPA* con la *Callback URL* que muestre Playground, autorizada para la API con los tres scopes.
4. `OAUTH_ISSUER` = `https://<tenant>.<región>.auth0.com/` (con barra final); `AGENT_MCP_TOKEN_URL` = `https://<tenant>.<región>.auth0.com/oauth/token`.

## Validación en MCP Playground (URL pública, no localhost)
1. API y MCP en marcha; puerto 8001 público; `curl -i https://<codespace>-8001.app.github.dev/mcp` debe dar **401** con `WWW-Authenticate`.
2. Playground → *Add server* → pegar la URL pública `.../mcp` → completar el login OAuth de Auth0 → *Discovery*: 5 tools con sus esquemas.
   [MCP Playground](https://mcpplaygroundonline.com) no hace login OAuth: se pega un token Bearer en *Add auth headers* (`Authorization: Bearer <token>`).
   Sin cabecera, el servidor responde 401 y el Playground muestra "This server requires authentication".
3. Token de pruebas: aplicación M2M `brasaland-playground` autorizada con los tres scopes; se obtiene con `client_credentials` (`POST <issuer>/oauth/token`, `audience` = `MCP_PUBLIC_URL`).
4. Flujo por tool: `incidents_create_ticket` → `incidents_get_ticket` → `incidents_list_tickets` → `incidents_update_ticket_status` (`open → in_progress → resolved`) → `inventory_get_stock`.
5. Transición inválida: pedir `open` sobre un ticket `resolved` → `[INVALID_TRANSITION]`.
6. Intento de escritura sobre inventario: `inventory_get_stock` con `quantity` (o una tool `inventory_update_stock`) → `[READ_ONLY_VIOLATION]`. El formulario del Playground solo envía los campos declarados, así que este caso se lanza con un cliente MCP (`fastmcp.Client`) contra la misma URL pública.
7. Autorización: con el token del agente (solo `tickets:read inventory:read`), `incidents_create_ticket` e `incidents_update_ticket_status` → `[FORBIDDEN_SCOPE]`.

> **Auth0 y los scopes de M2M:** en *client credentials* Auth0 **ignora el parámetro `scope`** y devuelve todos los permisos concedidos a la aplicación. Para probar `FORBIDDEN_SCOPE` hace falta una aplicación con menos permisos (el agente), no pedir menos scopes en la petición.

## Pruebas
```bash
python -m pytest tests/mcps -q                                            # servidor real por HTTP + agente vía MCP
cd services/api && DATABASE_URL=sqlite:// python -m pytest tests -q       # contrato de dominio y routers reales
```

## Estructura
`server.py` (app Starlette: MCP Auth + FastMCP) · `tools.py` (5 tools y esquemas) · `middleware.py` (scopes, guardia de solo lectura, auditoría) · `backend.py` (clientes HTTP del backend) · `errors.py` · `domain.py` · `config.py` · `__main__.py`.
