# Agente LangGraph base (Brasaland)

Agente que responde preguntas sobre la base de conocimiento de Brasaland **reutilizando** el pipeline RAG
(`retrieve()` y `generate_answer()` de `data/pipelines/rag.py`); no duplica lógica y ningún nodo llama a `query()`.

## Grafo

```
START → receive_question ──(válida)──→ retrieve_context ──(hay contexto)──→ generate_answer → END
              │                                │
              └─(vacía / >1000 car.)→ reject_question → END
                                               └─(nada supera el umbral)→ no_information → END
```

| Nodo | Responsabilidad única |
|---|---|
| `receive_question` | Normaliza (recorta) y valida la pregunta |
| `retrieve_context` | Llama a `retrieve()` y guarda el contexto |
| `generate_answer` | Llama a `generate_answer(question, context)` |
| `no_information` | Respuesta honesta "no tengo información"; **no genera** |
| `reject_question` | Error claro para pregunta vacía o demasiado larga |

**Estado mínimo** (`services/agent/state.py`): `question`, `context`, `answer`, `status`. Sin historial de
conversación: cada pregunta es independiente (una corrida = una pregunta), así que un historial solo añadiría
estado que nadie usa.

**Aristas condicionales**: tras `receive_question` (¿válida?) y tras `retrieve_context` (¿hay contexto sobre el umbral?).

## Compilación
`compile_graph()` compila de forma explícita al crear `AgentService` (al arrancar la API, no en la primera
petición) y lanza `AgentGraphError` si hay un nodo sin conexión, una arista a un nodo inexistente, falta el punto de
entrada o falta algún nodo esperado. (LangGraph por sí solo no avisa de nodos huérfanos; se añadió `check_connectivity`.)

## Checkpointing
Cada transición de estado deja un checkpoint con `thread_id = run_id`. Por defecto en memoria; con
`AGENT_CHECKPOINT_DB=ruta.sqlite` se guardan en SQLite y sobreviven a un reinicio (una corrida se puede inspeccionar
o retomar desde un checkpoint, p. ej. repetir solo la generación sin volver a recuperar).

## Trace
Cada corrida guarda `data/traces/agent/<run_id>.json` (o `AGENT_TRACE_DIR`): pregunta, estado final, orden de nodos,
por cada nodo entrada/salida/duración/error, y los checkpoints. El contexto se guarda como **referencias**
(documento, sección, chunk), no el texto. `data/traces/` está en `.gitignore`; para el PR se exporta un ejemplo.

## Endpoint
`POST /agent/query` con `{"question": "..."}` → `{"answer", "status", "run_id"}`.
Errores: 422 (pregunta vacía/larga/forma inválida), 503 (agente sin configurar), 502 (fallo de un nodo; mensaje
genérico + `run_id` para encontrar el trace). Nunca se devuelve un stack trace.

## Cómo ejecutarlo
```bash
python -m services.agent "¿Cuántos puntos necesito para el nivel Oro?" --export docs/agent/example-trace.json
python -m pytest tests/pipelines                       # tests RAG + grafo + evals
AGENT_EVAL_RESULTS=docs/agent/eval-results.json python -m pytest tests/pipelines/test_agent_evals.py -v
```

## Evals (`tests/pipelines/test_agent_evals.py`)
Se evalúan contra el **trace**, sin red ni claves (Qdrant en memoria con la base real, generador extractivo):
1. Respuestas ancladas en el BRIEFING: 4 preguntas; el dato esperado aparece en la respuesta **y** en el documento fuente, y el documento está entre los recuperados.
2. Pregunta fuera de tema → `no_information`, sin pasar por `generate_answer`.
3. Pregunta vacía → `reject_question`, sin recuperar ni generar.
4. Trace completo y coherente con los checkpoints.
5. La generación recibe exactamente el contexto recuperado.

---

# Parte 2 — Tools externas (tickets e inventario)

El agente ya no solo busca en el RAG: **decide por sí mismo** si la pregunta necesita el conocimiento (RAG), un dato
operativo en vivo (tool) o ambos, sin que el usuario lo indique.

> **¿Por qué no indexar los tickets en el RAG?** Los tickets cambian de estado en tiempo real y el RAG está pensado para
> conocimiento estable (políticas, procedimientos). Una tool que llama al gestor de incidentes siempre devuelve el dato
> actual; una copia indexada se queda desactualizada en cuanto alguien cambia el estado.

## Grafo (Parte 2)

```
START → receive_question ─(válida)→ route_question ─(según la pregunta, en este orden)→
          │                           lookup_tickets? → lookup_inventory? → retrieve_context?
          └─(vacía/larga)→ reject            │
                                             ├─ hay evidencia (RAG o tool OK) → generate_answer → END
                                             ├─ una tool falló, sin más evidencia → tool_fallback → END
                                             └─ el RAG no superó el umbral → no_information → END
```

**Enrutamiento** (`services/agent/routing.py`, función pura `plan_route`): datos en vivo → tool (estado de un ticket
concreto, listados por estado, stock de un producto); conocimiento → RAG; las dos cosas → ambos (primero la tool, luego
el RAG). Sin señal de datos en vivo → RAG. Es determinista y deja su `reason` en el trace; se puede sustituir por un
clasificador con LLM vía `AgentDependencies.router_fn` sin tocar el grafo.

## Tools: el agente consume el servidor MCP (`services/agent/mcp_tools.py`)

Desde el ticket "MCP Server con OAuth" el agente **ya no llama al gestor de incidentes ni al de inventario**. Hay un único
camino: `nodo → McpTicketTool / McpInventoryTool → McpGateway → servidor MCP (HTTP + Bearer OAuth) → backend`.
Las tools directas (`TicketTool`, `InventoryTool`, `BackendClient`) se **eliminaron**; `tools.py` conserva solo el contrato.

| Tool del agente | Tool MCP que invoca | Entrada → salida (pydantic, sin cambios) |
|---|---|---|
| `McpTicketTool` | `incidents_get_ticket` / `incidents_list_tickets` | `TicketQuery(ticket_id \| status, limit)` → `TicketsResult(outcome, tickets[...], total, error)` |
| `McpInventoryTool` | `inventory_get_stock` | `InventoryQuery(product_id \| product_name, limit)` → `InventoryResult(outcome, products[...], total, error)` |

- **Cliente:** `langchain-mcp-adapters` (`MultiServerMCPClient`, transporte Streamable HTTP) con discovery real de las tools.
- **OAuth:** `TokenProvider` pide un token por *client credentials* al proveedor (Auth0) y lo cachea hasta que caduca.
  Solo solicita `tickets:read inventory:read` (mínimo privilegio). Variables: `MCP_SERVER_URL`, `AGENT_MCP_TOKEN_URL`,
  `AGENT_MCP_CLIENT_ID`, `AGENT_MCP_CLIENT_SECRET` (`AGENT_MCP_AUDIENCE`, `AGENT_MCP_SCOPES` opcionales). Nada hardcodeado.
- **Solo lectura.** El agente solo invoca tools de lectura; el servidor además rechaza escrituras de inventario.
- **Timeout explícito:** `CALL_TIMEOUT_SECONDS = 8.0` por invocación completa (token + conexión + tool).
- **Nunca lanzan.** Los códigos del servidor (`[NOT_FOUND]`, `[FORBIDDEN_SCOPE]`, `[BACKEND_TIMEOUT]`...) se traducen a
  `outcome` (`not_found`, `unauthorized`, `timeout`, `unavailable`, `invalid`) con un mensaje sin URLs ni stack traces.
- **Enrutamiento intacto:** `routing.py` y los nodos no cambian; solo cambia qué hay detrás de `ticket_fn` / `inventory_fn`.
- Los nodos son síncronos y el cliente MCP es asíncrono: `McpGateway` ejecuta cada llamada con `asyncio.run` (o en un hilo si ya hay un bucle).

Documentación del servidor (transporte, scopes, errores, Auth0, Playground): [`mcps/brasaland_mcp/README.md`](../../mcps/brasaland_mcp/README.md).

## Fallback (ruta explícita, sin inventar)
Si una tool agota el timeout, el servicio está caído, no hay credenciales o el recurso no existe, el grafo **no se
rompe**: pasa a `tool_fallback` (sin llamar al modelo) y responde, p. ej., *"No pude confirmar el estado del ticket 482
ahora mismo: el gestor de incidentes no está disponible o no respondió a tiempo."* o *"No encuentro el ticket 9999…"*.
En una pregunta mixta, si falla la tool pero el RAG responde, se contesta la parte de conocimiento y se añade el aviso.

## Trace (extendido)
Además de lo de la Parte 1, cada trace incluye `route` (fuentes elegidas y motivo) y `sources_used`: las fuentes
realmente consultadas **en orden de ejecución** (`tool:tickets`, `tool:inventory`, `rag`) con su resultado. La respuesta
de `POST /agent/query` incluye `sources`. Ejemplos en `docs/agent/example-trace-tool.json` y `example-trace-rag.json`.

## Cómo ejecutarlo
```bash
# 1) API en marcha (puerto 8000), servidor MCP en marcha (puerto 8001) y las variables de mcps/brasaland_mcp/.env.example
python -m services.agent "¿En qué estado está el ticket 1?" --export docs/agent/example-trace-tool.json
python -m services.agent "¿Cuántos puntos necesito para el nivel Oro?" --export docs/agent/example-trace-rag.json
# 2) Evals de enrutamiento y fallback (sin red ni claves)
AGENT_TOOLS_EVAL_RESULTS=docs/agent/tools-eval-results.json python -m pytest tests/pipelines/test_agent_tools_evals.py -v
# 3) Todo
python -m pytest tests/pipelines
```

## Evals nuevos (`tests/pipelines/test_agent_tools_evals.py`, contra el trace)
1. Pregunta de datos en vivo → solo `tool:tickets`; el RAG no se consulta.
2. Pregunta de conocimiento → solo `rag`; no se llama al backend.
3. Pregunta mixta → `tool:tickets` y luego `rag`, con una sola generación.
4. Fallback (timeout / servicio caído / 500) → `tool_fallback`, sin generar y sin inventar un estado.
5. Ticket inexistente → "No encuentro el ticket…"; pregunta mixta con la tool caída → se responde el RAG y se avisa.
6. Solo lectura: ninguna petición del run es distinta de GET (salvo el login).
7. (Extra) Inventario: enrutamiento y fallback con las mismas reglas.

Además, `services/api/tests/test_agent_tools_integration.py` ejecuta las tools contra los **routers y repositorios reales**
(incidentes sobre TinyDB, inventario sobre SQLModel/SQLite) para detectar si el contrato de la API cambia.

## Memoria (Hito 8, Parte 1)
El agente ahora aprende de la conversación con confirmación del usuario y registro auditable: propone recordar un dato
operativo repetible en la misma respuesta, clasifica la decisión del usuario y solo guarda lo aprobado. Diseño, política de lo que
nunca entra, consolidación y las decisiones del ticket en **[`memory.md`](./memory.md)**; dos ciclos completos en
[`memory-evidence.md`](./memory-evidence.md). El grafo gana `resolve_pending`, `acknowledge_memory`, `recall_memory` y
`propose_memory`; `POST /agent/query` acepta `conversation_id` y `user` y devuelve `conversation_id` y `memory`.

## Guardrails y harness (Hito 8 · Parte 2, #SEC-114)
El agente se asegura con varias capas independientes (detector de cambio de instrucciones, datos confidenciales con estado por
conversación, uso personal, small talk con reconducción obligatoria, aislamiento del contenido externo, guardia de salida y
monitor por tipo de fallo). Diseño, pruebas por criterio, variantes de jailbreak documentadas y límites en
[`guardrails.md`](guardrails.md); tabla de intentos en [`guardrails-evidence.md`](guardrails-evidence.md).

- **Recepción de RFPs (Hito 9 · Parte 1):** [`rfp-intake.md`](rfp-intake.md) — grafo `rfp_intake`, tickets en PostgreSQL, handoff a la Parte 2.
- **Generación de respuestas a RFPs (Hito 9 · Parte 2):** [`rfp-response.md`](rfp-response.md) — generadores por departamento, 3 evaluadores en paralelo, bucle con feedback, `needs_human_review`.
