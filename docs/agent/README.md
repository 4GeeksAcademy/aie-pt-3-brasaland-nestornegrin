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
