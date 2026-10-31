# Diseño del RAG de Brasaland (Hito 7)

Este documento explica cómo funciona el asistente de conocimiento de Brasaland para que otro desarrollador pueda
entender el stack **sin leer el código**: el flujo de extremo a extremo, cómo se dividen los documentos (chunking) y
cómo se usan los embeddings.

**Qué resuelve.** Operaciones y Marketing reciben siempre las mismas preguntas (puntos, desperdicio, alérgenos,
pedidos a proveedores) y hoy cada gerente responde "a su manera". El asistente responde **como lo haría un vendedor
entrenado** — seguro, cercano, con datos correctos — usando solo los manuales oficiales, y admite cuando no sabe.

**Restricciones del hito.** Qdrant + SDKs directos + FastAPI (sin LangChain ni LlamaIndex); modelo de embeddings
distinto del de generación; la respuesta final siempre la redacta un modelo; nada de datos inventados.

---

## 1. Proceso RAG de extremo a extremo

```
 docs/company-knowledge-base/*.md                        (4 documentos fuente de Brasaland)
            │
            ▼  setup()  ── data/process/rag.py
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 1. load_documents()   lee los .md                                      │
   │ 2. chunk_document()   17 chunks semánticos con su sección              │
   │ 3. embed(chunk)       un vector por chunk (modelo de EMBEDDINGS)       │
   │ 4. Qdrant upsert      colección `brasaland_knowledge` (IDs uuid5)      │
   └────────────────────────────────────────────────────────────────────────┘
            │                                  (se ejecuta una vez / al cambiar los documentos)
   ─ ─ ─ ─ ─│─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
            │                                  (en cada pregunta)
 UI (uis/backoffice /knowledge) ──POST /knowledge/query {"question"}──▶ services/api/app/routes/knowledge.py
                                                                                   │ llama a query()
                                                                                   ▼
   query(question)  ── data/pipelines/rag.py  ──  es literalmente retrieve() + generate_answer()
   ┌────────────────────────────────────────────────────────────────────────┐
   │ retrieve(question, k=5, min_score)                                     │
   │   5. embed(question)         la MISMA embed() de la indexación         │
   │   6. Qdrant query_points     los k vecinos más cercanos (coseno)       │
   │   7. filtro min_score        descarta lo que no llega al umbral        │
   │   → devuelve los payloads supervivientes (0 a k)                       │
   │                                                                        │
   │ generate_answer(question, context)                                     │
   │   8. arma el prompt          voz y audiencia del BRIEFING + CONTEXTO   │
   │   9. LLM de GENERACIÓN       modelo de chat (distinto al de embeddings)│
   │   → devuelve el texto redactado por el modelo                          │
   └────────────────────────────────────────────────────────────────────────┘
                                                                                   │
 UI ◀──────────────── {"answer": "..."} ───────────────────────────────────────────┘
        (solo el texto: nunca chunks, listas ni puntuaciones; estas quedan en el log del servidor)
```

| Pieza | Responsabilidad única | Dónde |
|---|---|---|
| `setup()` | Preparar los datos e indexarlos en Qdrant | `data/process/rag.py` |
| `embed(text)` | Convertir texto en un vector | `data/process/rag.py` |
| `retrieve(query, *, k, min_score)` | Buscar y filtrar por umbral | `data/pipelines/rag.py` |
| `generate_answer(question, context)` | Armar el prompt y llamar al LLM | `data/pipelines/rag.py` |
| `query(question)` | `retrieve()` + `generate_answer()`; único punto de entrada para consumidores externos | `data/pipelines/rag.py` |
| `POST /knowledge/query` | Validar la petición y llamar a `query()` (cero lógica RAG) | `services/api/app/routes/knowledge.py` |
| Página `/knowledge` | Escribir la pregunta y mostrar la respuesta (con estados de carga y error) | `uis/backoffice` |

`generate_answer()` está separada de `retrieve()` a propósito: el futuro agente LangGraph podrá llamar a las dos
piezas como pasos distintos, sin recuperar dos veces ni envolver el monolito de `query()`. Cualquier pieza se puede
reemplazar (otro almacén vectorial, otro LLM) sin tocar las demás: los clientes de Qdrant y de modelos se pueden
inyectar por parámetro y se crean de forma perezosa.

---

## 2. Estrategia de chunking

**Estrategia: por bloques semánticos del Markdown, con unión de bloques de la misma sección y división solo si un
bloque es demasiado largo.** No es tamaño fijo.

**Por qué encaja con este corpus.** Los cuatro documentos son cortos (≈25 líneas, 1.000–1.500 caracteres) y **no
tienen encabezados `##`**: solo un título y bloques separados por una línea en blanco. Cada bloque es una idea completa:
una política, una lista de niveles, un grupo de pasos, una regla con su excepción. Esa es la unidad que preservamos:

- **Una lista siempre va con su frase de introducción** ("Niveles del programa:" + sus tres niveles; "Procedimiento
  diario:" + sus tres pasos). Un nivel suelto ("Oro: 15 %") sin saber de qué programa habla no se entiende.
- **Una regla siempre viaja con su condición.** Por ejemplo, el recargo del 8 % de un pedido de emergencia queda en el
  mismo chunk que la regla de stock mínimo que lo dispara y que la aprobación de Lucía Fernández por encima de 500 USD
  (dos bloques que hablan de lo mismo se unen). Si se cortara, el modelo vería "recargo del 8 %" sin saber cuándo
  aplica y acabaría inventando o negándose a responder.
- **Las advertencias de seguridad no se parten.** El protocolo de alergias (incluida la frase "nunca se garantiza cero
  riesgo de contaminación cruzada") es un solo chunk, y que la Costilla BBQ no tenga versión sin gluten certificada
  es un chunk propio, corto y fácil de encontrar.
- **Nunca se corta una frase ni un ítem.** Si en el futuro un bloque supera `MAX_CHARS` (800), se divide solo en el
  límite de un ítem de lista (repitiendo la frase de introducción en cada trozo) o de una frase.
- **Sin solapamiento (overlap).** El solapamiento sirve cuando se corta por tamaño; aquí los cortes ya caen en
  fronteras de significado y repetir texto solo duplicaría resultados.

**Nombre de la sección.** Como los documentos no tienen encabezados, cada sección se nombra por las primeras
palabras del bloque (tabla `SECTION_LABELS` en `data/process/rag.py`); si un bloque no coincide con ninguna regla se
usa su primera frase. Si un documento futuro trae encabezados `##`, esos nombres tienen prioridad.

**Tamaño y conteo por documento** (comprobado con `build_chunks()` sobre los documentos del repo):

| Documento (`source_document`) | Chunks | Tamaño (caracteres) |
|---|---|---|
| `loyalty-program` | 5 | 221 – 437 |
| `waste-protocol` | 5 | 167 – 399 |
| `menu-allergens` | 4 | 135 – 503 |
| `supplier-ordering` | 3 | 132 – 442 |
| **Total** | **17** | 132 – 503 |

Cumple lo pedido por el BRIEFING: al menos 3 chunks por documento, ni uno solo por documento ni uno por línea.

**Payload de cada punto** (campos del BRIEFING): `company="brasaland"`, `source_document`, `section`,
`language="es"`, `chunk_index` y `text` (el cuerpo del chunk, que es lo que se inserta en el prompt). Esos metadatos
son los que permiten citar la fuente ("Fuente: loyalty-program — Niveles del programa").

---

## 3. Prácticas de embeddings

| Aspecto | Decisión |
|---|---|
| **Modelo de embeddings** | `madrid-spain/openrouter/perplexity/pplx-embed-v1-0.6b`, modelo dedicado de embeddings proporcionado por 4Geeks (uno de los modelos permitidos a este equipo). Se lee de `EMBEDDING_MODEL`; no hay valor por defecto. Se piden vectores en formato `float`. |
| **Modelo de generación** | `madrid-spain/openrouter/xiaomi/mimo-v2.5` (modelo de chat de la lista permitida del equipo). Se lee de `GENERATION_MODEL` o `LLM_MODEL`; no hay valor por defecto. Temperatura 0 para ceñirse al contexto. Se probaron los modelos de chat de la lista: `deepseek-v4-flash` devolvía `content` vacío de forma intermitente (modelo de razonamiento), `glm-5.3-flash` no estaba disponible en el gateway y `gpt-6-luna` respondía bien pero más lento (7 s frente a 3,7 s). Además, `complete()` reintenta una vez y lanza `EmptyCompletionError` si la respuesta sigue vacía, para no devolver nunca un texto en blanco. |
| **Endpoint** | Gateway de 4Geeks compatible con OpenAI: clave en `LLM_API_KEY` y URL en `LLM_API_URL` (o `LLM_BASE_URL`). Cada equipo tiene una lista de modelos permitidos; pedir otro devuelve 403. |
| **Separación** | Los dos IDs deben ser distintos: `load_settings()` lanza `RagConfigError` si coinciden (hay un test). El modelo de generación nunca calcula embeddings. |
| **Una sola `embed()`** | La misma función embebe los chunks al indexar y la pregunta al consultar, así ambos viven en el mismo espacio vectorial. |
| **Dimensión del vector** | No se escribe a mano: `setup()` la mide con el primer embedding y crea la colección con ese tamaño (si cambia el modelo y cambia la dimensión, recrea la colección). **Valor medido: 1024.** El modelo devuelve vectores con aspecto cuantizado (valores múltiplos de 1/256); con coseno funcionan bien, como muestra el Recall@3 de la sección 5. |
| **Métrica de distancia** | Coseno (`Distance.COSINE`). Qdrant normaliza los vectores al insertarlos, así que la puntuación está en [−1, 1] y mide el ángulo, no la longitud del texto. |
| **Preprocesado antes de embeber** | Solo se recortan y colapsan espacios y saltos de línea (`normalize_text`). No se pasa a minúsculas ni se quitan tildes: el modelo las entiende y quitarlas puede confundir palabras. |
| **Contexto en el texto embebido** | Al indexar, cada chunk se embebe como `"<título del documento>. <sección>.\n<cuerpo>"`. El título y la sección aportan contexto (p. ej. "Protocolo de Control de Desperdicio") sin cambiar el `text` que se guarda y se inserta en el prompt. La pregunta del usuario se embebe tal cual. |
| **Idempotencia de `setup()`** | IDs deterministas (`uuid5` de documento + índice de chunk) con `upsert`, más borrado de los puntos huérfanos. Ejecutarlo de nuevo no duplica nada (hay tests con Qdrant en memoria). |

### Umbral mínimo de similitud (`min_score`)

`retrieve()` aplica un umbral y **no fuerza k resultados**: un top-k a secas siempre devuelve k chunks aunque ninguno
encaje, y meter contexto malo en el prompt es peor que admitir que no se encontró nada. Cuando nada lo supera,
`generate_answer()` recibe un contexto vacío y el prompt ordena decir que no hay información suficiente.

**Cómo se elige.** Con las preguntas de `data/eval/test-queries.json` el script `scripts/evaluate_rag.py` mide:

- la puntuación del chunk correcto en cada pregunta respondible (la más baja marca hasta dónde hay que bajar el umbral
  para no perder respuestas buenas); y
- la puntuación más alta que obtienen las preguntas totalmente fuera de tema (hasta dónde hay que subirlo para
  filtrar ruido).

El umbral recomendado es el **punto medio** entre ambas cifras; si las distribuciones se solaparan, el script avisa en
vez de inventar un número. Las preguntas que sí están en el dominio pero sin respuesta en los documentos (p. ej. el
precio de la Ensalada Tropical) no se pueden separar por similitud, y por eso la segunda defensa es el prompt: el modelo
solo puede usar el contexto y debe admitir cuando no contiene la respuesta.

El valor por defecto está en `data/process/rag_config.py` (`DEFAULT_MIN_SCORE`) y se puede sobrescribir con la
variable `RAG_MIN_SCORE` sin tocar el código. **Umbral elegido: 0,45.**

Con las 16 preguntas de evaluación: los aciertos puntúan entre **0,5285 y 0,846**, las preguntas fuera de tema entre
**0,07 y 0,28**, y las del dominio sin respuesta en los documentos entre 0,36 y 0,47. El script recomienda el punto
medio de 0,406 (entre 0,284 y 0,5285). Se elige **0,45** porque deja el mismo resultado sobre el conjunto de prueba,
filtra mejor lo ajeno al negocio y mantiene un margen de ~0,08 sobre el acierto más bajo: preguntas reales
formuladas con menos precisión puntuarán algo menos que las de prueba, y rechazar una pregunta válida es peor error
que dejar pasar una dudosa (que el prompt manda contestar como "sin información"). Subir el umbral hasta ~0,50 para
cortar también la pregunta de vacaciones (0,47) dejaría solo ~0,03 de margen, así que no se hace.

---

## 4. Prompt de generación: voz y audiencia

Definidas en el BRIEFING: responde **como un vendedor entrenado** (seguro, cercano, directo) a **gerentes de local,
clientes y personal nuevo** de Brasaland en Colombia y Florida. Reglas del prompt de sistema:

1. Usar **únicamente** el CONTEXTO recuperado.
2. Todo número, porcentaje, monto o plazo debe aparecer tal cual en el contexto; los montos en USD y COP se dejan como
   están (sin conversión de moneda).
3. Si el contexto está vacío o no contiene la respuesta, decir que no hay información suficiente en una o dos frases, sin mencionar el "contexto" interno ni citar fuente; nunca inventar.
4. Alérgenos: nunca decir "sin riesgo" ni garantizar cero riesgo de contaminación cruzada; seguir literalmente el texto.
5. Responder en español, breve, y cerrar con "Fuente: <documento> — <sección>" (la respuesta es trazable a la fuente
   aunque el endpoint solo devuelva el campo `answer`).

---

## 5. Evaluación

`data/eval/test-queries.json` tiene 16 preguntas: 12 respondibles (3 por documento, cada una con su chunk esperado y
la respuesta esperada), 2 fuera de tema y 2 dentro del dominio pero sin respuesta en los documentos.

```bash
uv run python -m scripts.evaluate_rag            # Recall@3 + umbral recomendado
uv run python -m scripts.evaluate_rag --answers  # además genera las respuestas y revisa su fidelidad
```

- **Recall@3** (objetivo ≥ 80 %): fracción de preguntas respondibles con el chunk correcto entre los 3 primeros
  resultados (se mide sin umbral, porque evalúa la calidad de la búsqueda). **Resultado: 100 % (12 de 12 preguntas con el chunk correcto en el top 3; 11 en el primer puesto y 1 en el segundo).**
- **Fidelidad:** ningún número en la respuesta que no aparezca en los chunks recuperados (comprobación automática).
- **Honestidad:** las preguntas sin respuesta deben contestarse admitiendo que no hay información.
- **Seguridad en alérgenos:** ninguna respuesta contiene "sin riesgo".

Los resultados se guardan en `data/eval/rag_eval_results.json`.

---

## 6. Decisiones y límites

- **Qdrant Cloud** (plan gratuito) en lugar de un contenedor propio: el ticket permite cualquiera de los dos y así no
  se depende del `docker-compose.yml` principal. La URL y la clave van en `.env` (`QDRANT_URL`, `QDRANT_API_KEY`).
- **El endpoint no exige sesión**, porque el ticket solo define el cuerpo de petición y de respuesta. La página del
  backoffice sí está tras el `AuthGuard`. Si el endpoint se expusiera fuera de la red interna, convendría añadir
  `get_current_user` y un límite de peticiones (cada consulta cuesta una llamada al LLM).
- **Con contexto vacío igualmente se llama al modelo**, con la instrucción de admitir que no hay información: así la
  respuesta final siempre pasa por el modelo, como exige el criterio de aceptación.
- **Corpus pequeño (17 chunks):** el Recall@3 con 5 resultados posibles es optimista; con una base mucho mayor
  habría que reevaluar el umbral y considerar reranking.
- **Solo español.** El BRIEFING permite mantener el idioma base; el payload lleva `language="es"` para poder añadir
  inglés más adelante.
- **Sin memoria conversacional:** cada pregunta es independiente (un RAG no es memoria).

## 7. Cómo ejecutarlo

```bash
# 1. Variables en .env (ver services/api/.env.example): QDRANT_URL, QDRANT_API_KEY, LLM_API_KEY, LLM_API_URL,
#    EMBEDDING_MODEL y GENERATION_MODEL
uv run python -m data.process.rag                # setup(): indexa y muestra el nº de chunks (idempotente)
uv run python -m scripts.evaluate_rag --answers  # Recall@3, umbral y fidelidad
uv run pytest tests/pipelines/test_rag.py -v     # pruebas unitarias (sin Qdrant ni LLM reales)

# API (desde la raíz del repo) y UI
PYTHONPATH=services/api uv run --project services/api uvicorn app.main:app --app-dir services/api --reload
cd uis/backoffice && npm run dev                 # página /knowledge
curl -X POST localhost:8000/knowledge/query -H 'Content-Type: application/json' \
     -d '{"question": "¿Cuántos puntos necesito para el nivel Oro?"}'
```

**Resultado con `mimo-v2.5` y umbral 0,45** (`uv run python -m scripts.evaluate_rag --answers --min-score 0.45`):
Recall@3 = 100 %, fidelidad = correcta (ningún número fuera de los chunks recuperados), honestidad = correcta
(las 4 preguntas sin respuesta admiten que no hay información) y ninguna respuesta contiene frases prohibidas.
