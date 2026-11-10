# Memoria y auto-mejora del agente (Hito 8 · Parte 1)

El **Manager support agent** de Brasaland aprende de la conversación **sin inventar ni acumular basura**: cuando un gerente
corrige o afirma un dato operativo repetible («el proveedor de carne de Medellín entrega los martes, no los lunes»), el
agente **se lo propone al usuario en la misma respuesta**, la decisión del usuario se **clasifica de forma explícita**, y solo
lo aprobado se guarda. Es el mismo agente LangGraph de siempre (RAG + MCP) con tres piezas más: un almacén, una política y un
paso de auto-evaluación en su salida. No hay agente auxiliar ni segunda llamada al modelo.

```
mensaje -> receive_question -> resolve_pending ──(solo contestaba la propuesta)──> acknowledge_memory -> END
                                      │
                                      └─> route_question -> recall_memory -> [tickets | inventario | RAG]
                                              -> generate_answer (UNA llamada: respuesta + propuesta_memoria)
                                              -> propose_memory -> END   (valida con la política y deja la propuesta PENDIENTE)
```

| Nodo nuevo | Qué hace |
|---|---|
| `resolve_pending` | Si la conversación tiene una propuesta pendiente, clasifica este mensaje contra ella (aprobar / rechazar / editar / ambigua), la resuelve, y devuelve el resto del mensaje como una pregunta normal |
| `acknowledge_memory` | El mensaje solo respondía a la propuesta: confirma qué pasó («Listo, lo guardé: …») sin consultar nada |
| `recall_memory` | Trae como máximo 5 recuerdos relevantes (≤ 1 200 caracteres), no todo el almacén |
| `generate_answer` | Una llamada con salida estructurada: la respuesta y el campo `propuesta_memoria` |
| `propose_memory` | Antepone lo que pasó con la propuesta anterior y, si el modelo propuso algo y la política lo acepta, lo deja pendiente y lo pregunta al final de la misma respuesta |

Sin `AgentDependencies.memory` (o con `AGENT_MEMORY_ENABLED=0`) el grafo es exactamente el anterior.

## 1. Arquitectura de memoria elegida (y por qué)

**Elegida: memoria episódica estructurada en SQLite**, con clave `location + categoría + tema`, aparte de Qdrant.

| Opción | Decisión | Por qué |
|---|---|---|
| Ventana de contexto / system prompt | Se mantiene solo para la conversación en curso | El BRIEFING pide que *lo aprendido* sobreviva entre conversaciones, y meter todo en el prompt crece sin límite y no se puede auditar ni olvidar |
| **Clave-valor / tabla (SQLite)** | **Elegida** | Los hechos son exactos (un día, una hora, una excepción) y se indexan por location + categoría. Da transacciones, un índice único que garantiza «una propuesta pendiente a la vez», triggers que hacen el registro de auditoría solo-añadir y consultas para auditar. Sin servicio nuevo que operar en el monorepo |
| Redis | Descartada por ahora | Aportaría TTL nativo y caché, pero añade un servicio y no da auditoría relacional. La interfaz (`AgentMemory` + `SqliteMemoryStore`) está aislada: cambiar de backend es sustituir una clase |
| VectorDB (Qdrant) | Descartada | La similitud semántica difumina justo lo que importa: «martes» y «miércoles» están casi a la misma distancia. Además el ticket prohíbe mezclar memoria con las colecciones `*_knowledge`. Con ≤ ~700 recuerdos activos (14 locations × 5 categorías × ≤ 10), escanear con puntuación léxica es más simple y predecible |
| Knowledge graph | Descartada | No hay relaciones explícitas que recorrer (solo location → categoría, que ya es la clave) |
| Fine-tuning | Descartada | Es la memoria «paramétrica»: cara, lenta de actualizar y **no permite olvidar** un dato falso |

El **RAG sigue siendo solo lectura**: el paquete `services/agent/memory/` no importa Qdrant (lo comprueba una prueba) y su
archivo (`AGENT_MEMORY_DB`, por defecto `data/memory/agent_memory.sqlite`, en `.gitignore`) no es ninguna colección `*_knowledge`.

**Interfaz explícita de lectura/escritura** (no hay estado acumulado en el prompt):
`AgentMemory.recall()` (lectura), `AgentMemory.propose()` (abre una propuesta PENDIENTE; no escribe) y
`AgentMemory.resolve_pending()` (único camino que llama a `activate_memory()`, tras un aprobar/editar clasificado).

## 2. Qué se recuerda y qué NUNCA entra (BRIEFING)

Se recuerda solo: **horarios**, **proveedores** (días de entrega), **incidentes conocidos** (una escalación resuelta que se repite,
p. ej. un apagón), **preferencias de comunicación** de un gerente y **excepciones a un procedimiento** (`CATEGORIES` en `models.py`).

Nunca entra (BRIEFING): datos personales de clientes de Brasa Points, cifras de nómina o compensación individual, y cualquier
cosa de una conversación puntual sin patrón repetible. Se hace cumplir en **dos capas**:

1. **El prompt** (`STRUCTURED_RULES` en `llm.py`) le dice al modelo qué proponer y qué no.
2. **La política determinista** (`policy.py`) revisa lo que el modelo propone **y la edición que escribe el usuario** antes de
   guardar nada: categoría permitida, marcado «repetible», nómina/compensación, correos, teléfonos, documentos, datos de
   clientes de Brasa Points. Un prompt no es una barrera; esta capa sí. Si algo no pasa, la propuesta **ni se muestra** y queda
   registrada (`proposal_rejected_by_policy`).

## 3. Auto-evaluación en una sola llamada

El modelo devuelve un JSON `{"respuesta": ..., "propuesta_memoria": null | {...}}` con un criterio explícito (ver `STRUCTURED_RULES`):
solo propone cuando la persona **afirma o corrige** un dato operativo **repetible** de una location en una categoría permitida.
Si la salida no es JSON válido, el fallo es **seguro**: se entrega el texto sin propuesta.

### Ejemplos que NO generan una propuesta (los tres del BRIEFING, con las pruebas)
| Mensaje | Por qué no |
|---|---|
| «¿Cuál fue el ticket promedio de ayer en Bogotá?» | Consulta puntual; el dato vive en telemetría, no en memoria |
| «Gracias, eso resuelve mi duda.» | Cierre de conversación, nada nuevo |
| «¿Puedes traducir esto al inglés para el reporte de Ashley?» | Tarea de un solo uso |

Además, aunque el modelo se equivoque y proponga (una queja de un cliente de un solo día, o la nómina de una jefa de cocina),
la política lo frena (`test_even_if_the_model_proposes_by_mistake_...`).

## 4. Confirmación del usuario y registro auditable

* **Una propuesta pendiente a la vez**, por conversación: un índice único parcial en SQLite lo garantiza y `propose()` lo
  comprueba antes de abrir otra.
* **El siguiente mensaje se evalúa primero contra la propuesta** con un clasificador (`classify_intent`, una llamada con etiqueta
  estructurada: `aprobar | rechazar | editar | ambigua` + confianza). Nunca se busca «sí» dentro del texto.
* **Silencio o ambigüedad = descarte**, nunca aprobación: confianza < 0,8, cambio de tema sin responder, clasificador caído o JSON
  inválido, edición rechazada por la política, límite de ritmo, o 24 h sin respuesta → la propuesta se descarta y se avisa al usuario.
* Si el usuario contesta **y** sigue con otra pregunta, se resuelve la propuesta y se atiende el resto del mensaje.
* **Edición**: el texto del usuario pasa por la misma política antes de guardarse.
* **Auditoría** (`memory_events`, solo-añadir con triggers que abortan UPDATE/DELETE): `proposal_created` (qué se propuso, mensaje
  que lo originó), `memory_written` / `proposal_rejected` / `proposal_discarded` (qué decidió el usuario, su mensaje, intención, confianza,
  **quién** y **cuándo**), `memory_superseded`, `memory_expired`, etc. Los mensajes se guardan sin correos ni teléfonos y acotados.
  La tabla `proposals` conserva el hecho propuesto y la decisión, aprobada o rechazada.

Evidencia: [`memory-evidence.md`](./memory-evidence.md) (dos ciclos, flujo con modelo guionizado) y
[`memory-evidence-real.md`](./memory-evidence-real.md) (los dos ciclos con el modelo real, el registro de auditoría y lo que se corrigió a partir de ellos).

## 5. Consolidación y limpieza

Se ejecuta tras cada escritura y a demanda (`python -m services.agent.memory consolidate`). Reglas, todas auditadas:

| Regla | Valor | Por qué |
|---|---|---|
| Sustitución por clave | misma location + categoría + tema → la versión nueva reemplaza (y el historial queda `superseded`) | Una corrección debe cambiar el dato, no sumarse a él. La propuesta avisa: «Reemplazaría lo guardado: …» |
| Deduplicación | hechos idénticos en el mismo grupo → se queda el más reciente | Evita repetidos |
| Tope por grupo | 10 por location + categoría (se descarta lo más antiguo sin uso reciente) | El BRIEFING sugiere agrupar por location + categoría; con 14 locations la memoria crecería rápido |
| Tope total | 500 activos | Cota dura |
| Caducidad por categoría | incidentes conocidos 60 días; horarios, proveedores y excepciones 180; preferencias 365 | Un apagón conocido envejece rápido; un horario cambia unas pocas veces al año. Se cuenta desde la **aprobación**, no desde el último uso: un dato falso que se consulta mucho no debe volverse inmortal. Un recuerdo se renueva aprobando de nuevo |
| Propuesta sin respuesta | 24 h → se descarta | No queda abierta para siempre |

La consolidación es **determinista** (sin resumir con un LLM): un resumen generado podría alterar «martes» por «miércoles» y no
se puede auditar. El agrupamiento por location + categoría se aplica al **leer** (`format_memories` agrupa lo que recibe el modelo).

## 6. Decisiones de diseño (respuestas del ticket)

1. **¿Qué tipo de memoria necesita Brasaland y por qué se descartaron las otras?** Episódica estructurada por clave, para
   correcciones exactas y por location. Semántica/vectorial no (confunde «martes» y «miércoles» y el ticket prohíbe mezclarla con
   `*_knowledge`), grafo no (no hay relaciones que recorrer), fine-tuning no (no permite olvidar). Ver la tabla del apartado 1.
2. **¿Qué nunca debe entrar?** Lo del BRIEFING: datos personales de clientes de Brasa Points, nómina/compensación individual y
   lo puntual sin patrón. Se aplica con la política determinista, no solo con el prompt (apartado 2).
3. **¿Cómo decide qué olvidar y qué pasa con una propuesta que nadie responde?** Se olvida por caducidad por categoría, por sustitución
   cuando llega una versión nueva y por topes por grupo. La propuesta sin respuesta se descarta: en el siguiente mensaje (si
   cambia de tema, es ambiguo o el clasificador falla) o a las 24 h (apartado 4 y 5).
4. **¿Cómo evita el «envenenamiento» con información falsa presentada como corrección?** Defensas en capas: (a) **el usuario siempre
   decide** y ve exactamente lo que se guardaría; (b) el hecho debe **salir del mensaje del usuario** (todas las cifras y la mayoría de
   las palabras deben aparecer en él), así el modelo no puede «mejorar» una hora; (c) la política rechaza instrucciones dirigidas al
   agente («ignora…», «a partir de ahora…»), enlaces y marcado, también en las ediciones; (d) límites de ritmo (5 aprobaciones/hora por
   conversación, 20/día por actor); (e) lo recordado se le da al modelo como **datos no oficiales** y, si contradice el contexto
   oficial (RAG/tools), debe decir ambas cosas; la memoria nunca sobrescribe el RAG; (f) cada escritura queda atribuida y fechada, y
   caduca. **Límite honesto:** si un gerente afirma algo falso a propósito y lo aprueba, se guarda hasta que caduque o lo corrijan;
   el control es la atribución y la caducidad, no adivinar la verdad.
5. **¿Por qué no hace falta multi-agente?** Porque la auto-evaluación es **un campo más en la salida** del mismo modelo que ya
   responde (una sola llamada, comprobado en `test_structured_generation_parses_answer_and_proposal_from_one_call` y
   `test_the_proposal_goes_in_the_same_answer...`). Un agente aparte duplicaría contexto y latencia y añadiría un punto de desacuerdo
   sin aportar control: el control real está en el **código** (política, una pendiente, clasificador, auditoría), que es determinista.
   La única segunda llamada es el clasificador de la respuesta del usuario, y ocurre en un turno distinto.

> **Gobernanza de la memoria core (omitida a propósito).** En una empresa real, los cambios a la memoria core pasan por tickets de
> solicitud y los aplica un equipo con esa cadena de control. Para este hito se omite: el flujo es propuesta → confirmación del
> usuario → escritura directa, tal como pide el ticket.

## 7. Idioma
La propuesta y la confirmación usan el idioma de la persona (español o inglés): el modelo devuelve `idioma` y los textos fijos
(pregunta, avisos) salen en ese idioma. El clasificador entiende ambos. Probado en `test_proposal_and_confirmation_work_in_english_too`.

## 8. Límites conocidos
* El endpoint `POST /agent/query` sigue siendo público (como en los hitos anteriores): `user` lo declara el cliente, así que
  el actor del registro es **declarado, no autenticado**. Protegerlo con `get_current_user` lo convertiría en identidad verificada.
* Cada pregunta sin evidencia cuesta ahora una llamada al modelo (antes se respondía sin modelo): es el precio de poder detectar una
  corrección que el agente aún no conoce. `AGENT_MEMORY_ENABLED=0` vuelve al comportamiento anterior.
* El archivo SQLite vive en el disco del servicio; en un despliegue con varias réplicas habría que moverlo a Postgres/Redis (la interfaz está aislada).
* La calidad del modelo real (qué propone y cómo clasifica) depende de `GENERATION_MODEL`; las pruebas automáticas usan un modelo guionizado
  para verificar todo lo que lo rodea, y los dos ciclos reales están en `memory-evidence-real.md`.

## Variables y comandos
| Variable | Por defecto | Qué hace |
|---|---|---|
| `AGENT_MEMORY_ENABLED` | `1` | `0` desactiva la memoria |
| `AGENT_MEMORY_DB` | `data/memory/agent_memory.sqlite` | Archivo del almacén |

```bash
# Dos ciclos con el modelo real (con el .env cargado; no hace falta la API ni el MCP). Cambia el id de conversación para cada ciclo.
uv run --env-file .env python -m services.agent --conversation demo-aprobado-01 --user carlos.jimenez "En realidad el proveedor de vegetales de Medellín entrega los miércoles, no los martes."
uv run --env-file .env python -m services.agent --conversation demo-aprobado-01 --user carlos.jimenez "Sí, guárdalo"
uv run --env-file .env python -m services.agent --conversation demo-aprobado-02 --user carlos.jimenez "¿Qué día entrega el proveedor de vegetales de Medellín?"
uv run --env-file .env python -m services.agent --conversation demo-rechazado-01 --user ashley.r "La location de Miami Beach ahora cierra a las 11pm los fines de semana."
uv run --env-file .env python -m services.agent --conversation demo-rechazado-01 --user ashley.r "No, no lo guardes"
python -m services.agent.memory events      # registro de auditoría
python -m services.agent.memory list        # memoria activa
python -m services.agent.memory consolidate # limpieza a demanda
# Pruebas (sin red) y regenerar la evidencia offline
python -m pytest tests/pipelines/test_agent_memory.py tests/pipelines/test_agent_memory_evidence.py
AGENT_MEMORY_EVIDENCE=docs/agent/memory-evidence.md python -m pytest tests/pipelines/test_agent_memory_evidence.py
```
