# Chat en vivo del Manager support agent (WebSocket) — Hito 10 · Parte 2

Mismo agente, otro canal: los tokens salen conforme se generan y el encargado puede **interrumpir y redirigir** a mitad de respuesta. No se cambió la lógica ni las tools del agente (`services/agent/graph.py`, `nodes.py`, tools): solo se añadió un gancho opcional en `rag.complete()` y el canal.

## Contrato

`ws://<api>/agent/chat/ws?session_id=chat_0044&token=<JWT>[&location_id=loc_miami]`

- `session_id` obligatorio (`[A-Za-z0-9_-]{8,64}`). Es el id de la sesión de chat y también el `conversation_id` que recibe el agente (memoria). **Sobre `thread_id`:** el agente usa un `thread_id` de LangGraph por pregunta (`run_id`) y no se tocó; el historial que se rehidrata es el del chat (`ChatStore`), indexado por `session_id`.
- Auth: el **mismo JWT** que el backoffice y el SSE. `?token=` o, si falta, primer frame `{"event":"auth","data":{"token":"…"}}` (5 s). Sin token válido: `?token=` inválido → el handshake se rechaza (403); frame inválido/ausente → cierre `4401`; antes de enviar ningún evento de chat. `session_id` inválido → `4400`. Sesión de otro usuario → `4403` (salvo administrador, que entra **solo lectura**: recibe los eventos pero no puede escribir).
- `ChatSession`: `session_id`, `agent_id` (`manager_support`), `user_id`, `location_id`, `status` (`active` | `interrupted` | `closed`), `created_at`. `interrupted` mientras el último turno quedó abortado; vuelve a `active` al abrirse el turno nuevo. `closed` está en el modelo pero ningún flujo actual lo asigna (no hay «cerrar chat»).

| Dirección | Evento | `data` |
|---|---|---|
| ←  | `session_snapshot` | `{session_id, messages:[{message_id, role, text, status, sequence, created_at}]}` — siempre el primer frame |
| ↔  | `user_message` | `{session_id, text}` (cliente → servidor lleva solo `text`; el servidor lo difunde a toda la sesión) |
| ←  | `token_chunk` | `{session_id, token, sequence}` (`sequence` 1, 2, 3… dentro del mensaje) |
| ↔  | `interrupt_requested` | `{session_id, new_input}` |
| ←  | `generation_interrupted` | `{session_id, message_id, status:"interrupted"}` |
| ←  | `generation_completed` | `{session_id, message_id}` |

Extensiones (no están en el BRIEFING, necesarias para un chat real): `message_corrected {message_id, text}` (ver «Guardrails»), `generation_failed {message_id, status:"failed", detail}`, `error {code, message}` solo a la conexión que lo causó, y `ping`/`pong`.

Orden al interrumpir: `interrupt_requested` → `generation_interrupted` → `user_message` → `token_chunk…` → `generation_completed`.

## Arquitectura

```
cliente WS ──► router.py ──► ChatSessionManager.submit ──► hilo: AgentService.run (sin cambios)
   ▲                │                                          │  rag.complete(stream=True) → StreamSink
   │                ▼                                          ▼
   └──── cola por conexión ◄── ChatBroker.publish("chat.<session_id>") ◄── token_chunk
                                  ChatStore (SQLite): sesiones + mensajes (cada token se anexa)
```

- `data/pipelines/streaming.py`: `StreamSink` + contextvar. Con sink activo `complete()` pide `stream=True`, entrega cada fragmento y devuelve el texto completo (sin sink, comportamiento idéntico al anterior). La contextvar llega hasta los nodos de LangGraph (probado con el grafo real).
- `services/agent/chat/extract.py`: con memoria activa el modelo responde JSON (`{"respuesta":…, "propuesta_memoria":…}`); el extractor muestra solo `respuesta` de forma incremental, tolerando escapes partidos entre fragmentos.
- `broker.py`: pub/sub en memoria, canal `chat.<session_id>`, una cola acotada por conexión. Una conexión lenta se cierra (1013) en vez de perder eventos en silencio: al reconectar se rehidrata.
- `manager.py`: una generación por sesión; cerrojo por sesión que hace atómicos «guardar+publicar token» y «snapshot+suscribirse».
- `store.py`: SQLite (`CHAT_DB_PATH`; por defecto `data/runtime/chat_sessions.sqlite3`, ignorado por git; `:memory:` en pruebas).

## Respuestas de diseño (las del PR)

**1. ¿Por qué WebSocket y no el SSE de la Parte 1?** SSE es unidireccional (servidor → cliente) y la Parte 1 solo notifica. Aquí el cliente tiene que hablar **en mitad de la respuesta** (interrumpir, redirigir) por el mismo canal, con baja latencia y con la sesión viva; con SSE habría que mantener un POST aparte por mensaje, correlacionarlo con el stream y no habría un canal de control ordenado respecto a los tokens. El WebSocket además permite la auth por primer frame y que varios clientes de una sesión compartan el canal. La reconexión se parece (backoff + rehidratación), pero en vez de `Last-Event-ID` se usa `session_snapshot`.

**2. Varios clientes en la misma sesión.** Hay **una ejecución del agente por turno**, no por cliente. El hilo productor publica en `chat.<session_id>`; cada conexión suscrita tiene su cola y recibe exactamente los mismos eventos (probado: dos suscriptores, un solo `question` al proveedor). Un cliente que entra a mitad recibe `session_snapshot` con el texto parcial y a partir de ahí solo tokens posteriores, sin huecos ni duplicados (el cerrojo hace atómico snapshot+suscripción). Un administrador entra como espectador (solo lectura).

**3. Abortar el stream ≠ `interrupt()` de LangGraph.** `interrupt()` es HITL: **pausa** el grafo en un checkpoint y espera una decisión; no corta una llamada en vuelo. Aquí hace falta **abortar la generación**: el manager marca la generación como cancelada, activa el `Event` del sink y `complete()` cierra el stream del proveedor y lanza `GenerationCancelled` en el siguiente fragmento (la corrida termina, no queda pausada). Desde ese instante, bajo el cerrojo de la sesión, el hilo viejo no puede publicar ni guardar un token más. El parcial que ya se mostró **se conserva** como mensaje `interrupted` (nunca se borra ni se sobrescribe) y la entrada nueva abre un turno nuevo (otro `message_id`) con `new_input` como pregunta. El agente no usa `interrupt()` para esto y no se modificó.

## Guardrails: el trade-off

Los guardrails de salida validan la respuesta **completa** después de generarla; con streaming el usuario ya vio los tokens. Decisión: se muestra el stream, y si el texto final validado difiere del mostrado se emite `message_corrected` (el cliente sustituye el texto) justo antes de `generation_completed`; si no se mostró nada (p. ej. rechazo del guardrail de entrada o de saludo casual) el texto final se emite en `token_chunk`s. **Riesgo asumido y a revisar con el tech lead:** durante unos segundos el usuario puede ver texto que el guardrail luego corrige; si eso no es aceptable, la alternativa es no streamear en rutas con guardrail de salida.

## Cómo probarlo

- Automático: `uv run pytest -q tests/chat` (contrato de eventos, aborto real, parcial `interrupted`, turno nuevo con `new_input`, rehidratación, varios clientes, guardrails) y, desde `services/api`, `DATABASE_URL=sqlite:// uv run --project . pytest tests/test_chat_ws.py` (JWT, rechazo previo, session_id, solo lectura). Front: `npx jest` en `uis/backoffice`.
- Manual sin claves (WebSocket real + proveedor falso lento): `PYTHONPATH=.:services/api uv run --project services/api python -m scripts.chat_ws_demo`. Imprime tiempo al primer token, el aborto (ms desde que se pide), que no llega ningún token viejo tras `generation_interrupted`, y el snapshot al reconectar.
- Manual en el navegador: levantar la API y la UI (`/chat`, «Chat en vivo»), iniciar sesión, preguntar algo largo y, mientras escribe, enviar otro mensaje («Interrumpir y enviar»): el parcial queda con la marca «Interrumpido» y la respuesta nueva es otro mensaje. Para reconexión: DevTools → Network → «Offline» unos segundos y volver a «Online»; o recargar la página (el `session_id` está en `sessionStorage`).

## Límites conocidos

- Broker y generaciones viven en el proceso (un solo worker); con varios haría falta Redis pub/sub detrás de la misma interfaz `subscribe`/`publish`.
- El JWT se valida en el handshake; una conexión larga no se corta cuando el token caduca (el siguiente handshake sí lo exige). `?token=` queda en la URL (así lo prefiere el BRIEFING): conviene que los logs del proxy no registren query strings.
- Cancelar antes de que empiece a generar (p. ej. durante la recuperación RAG) no puede interrumpir esa fase, pero la generación abortada ya no publica nada y su `complete()` se cancela al llamarse.
