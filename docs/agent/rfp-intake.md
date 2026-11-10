# Recepción y enrutamiento de RFPs (Hito 9 · Parte 1)

Flujo agéntico que recibe un PDF de RFP en el backoffice, decide si es una RFP de Brasaland, extrae sus metadatos y reparte el
análisis entre los departamentos que apliquen. Termina con un contrato de entrega (`handoff`) para la Parte 2.

## Arquitectura

```
uis/backoffice  /rfp ──POST PDF──▶ services/api  /rfp/tickets ──202 + ticket_id──▶ (UI hace polling a GET /rfp/tickets/{id})
                                        │ guarda el PDF en data/raw/rfp/ y crea el ticket «analizando» en PostgreSQL
                                        ▼ BackgroundTasks
              data/pipelines/rfp_intake  (grafo LangGraph propio, `rfp_intake`)

 convert ─▶ classify ─┬─▶ measure ─▶ extract_metadata ─▶ orchestrate ─┬─▶ worker[marketing]   ─┐
 (MarkItDown)         │  (legibilidad)                   (plan)        ├─▶ worker[operaciones]  ├▶ synthesize ─▶ analisis_completo
                      │                                               ├─▶ worker[procurement]  │  (handoff + resumen para Ventas)
                      └─▶ discard ─▶ descartado                       └─▶ worker[training]    ─┘  (solo los que aplican; Send API)
```

- **Routers** (`services/api/app/rfp/routes.py`) solo disparan y consultan. **Lógica de agentes**: `data/pipelines/rfp_intake/`.
  El pipeline no conoce SQL: recibe un `RfpStore`; la implementación PostgreSQL es `services/api/app/rfp/repository.py`.
- **Tablas** (SQLModel, Supabase): `rfp_tickets`, `rfp_metadata` (con legibilidad), `rfp_department_sections` (`key_aspects`, y ya
  existen, vacías, las columnas de las Partes 2–3: `draft_content`, `evaluation_results`, `approval_status`, `approver`, `approved_at`).
  `create_all` no migra tablas ya creadas: por eso se crean completas ahora.
- **Estados (Parte 1)**: `analizando` → `analisis_completo` | `descartado`. Nunca `esperando_aprobación`.
- **Departamentos** (BRIEFING §2.1): `marketing` (Camila Ospina, dueña del ticket, siempre activo), `operaciones` (Felipe Guerrero),
  `procurement` (Lucía Fernández), `training` (Jake Morrison). El orquestador decide cuáles aplican; `training` no aplica con menú estándar.

## Agentes

| Agente | Qué hace | Qué verifica el código (no el modelo) |
|---|---|---|
| Clasificador | Propone `is_rfp` y 4 señales | `decide_rfp`: RFP = `is_rfp` **y** servicio **y** alcance/volumen **y** (fecha **o** presupuesto) |
| Extractor | Cliente, ubicación, servicio, alcance, fecha, presupuesto | Cada dato debe aparecer en el documento; si no, se descarta y pasa a `open_questions` |
| Orquestador | Qué departamentos aplican y con qué extractos | Extractos textuales; departamentos inexistentes se descartan; `marketing` forzado |
| Worker (×N) | `key_aspects`, qué pedir, cifras, preguntas abiertas | Toda cifra se busca en el documento (la no verificable se marca y se elimina del estado compartido); la cita de cada aspecto debe figurar textual en el PDF, si no el aspecto queda `inferred: true` y sin cita |
| Synthesizer | Resumen para Ventas (qué pedir y a quién) | Si el modelo falla, texto determinista; el handoff se construye en código |

El texto del PDF es un dato no confiable: va dentro de `<documento>…</documento>` con la regla de no obedecer instrucciones del documento.
Las salidas se validan con pydantic con un reintento de reparación; si falla otra vez, el ticket falla de forma explícita.

## Preguntas de diseño

1. **Departamento desconocido en la RFP** (p. ej. «Legal»). No se crea un worker: se descarta del plan y queda en
   `unknown_departments` dentro del handoff. La información no se pierde: queda como pregunta abierta para Marketing.
2. **Qué necesita cada worker y qué pasa si falta una cifra.** Recibe solo metadatos compartidos + los extractos de su departamento
   (no el estado completo ni el PDF entero). Si falta una cifra, el worker la declara en `open_questions`; si inventa una, el código
   la detecta (`unverified_numbers`), la saca de `figures` y añade una pregunta abierta. Nunca se inventan números.
3. **Cómo se decide «no es una RFP» y qué hace un falso negativo.** El modelo propone, las reglas de arriba deciden y el motivo
   queda en el ticket (`discard_reason` y `classification`). Se prefiere descartar con motivo visible a procesar basura. Un falso
   negativo se corrige desde la UI («Forzar análisis», `POST /rfp/tickets/{id}/reprocess?force=true`): salta la decisión, deja
   `forced_by_user` en la clasificación y sigue el flujo normal. Un descarte nunca detiene a otros tickets.
4. **Dos workers que se contradicen.** Las cifras se guardan estructuradas por departamento; `detect_conflicts` compara la misma
   cifra con valores distintos y la deja en `handoff.conflicts`. El pipeline **señala**, no resuelve: el arbitraje es de la Parte 3.
5. **Dónde corre lo asíncrono y cómo el ticket sigue siendo verdad si el job muere.** En `BackgroundTasks` del mismo API (sin
   infraestructura nueva). La verdad está en PostgreSQL: cada nodo escribe `current_node` y `heartbeat_at`; una excepción se guarda
   con `fail()` (el ticket sigue `analizando` pero se muestra «falló»); si el proceso muere sin avisar, un latido de más de 15 min se
   muestra «detenido». Ambos se reintentan con `POST …/reprocess` (o `scripts/rfp_reprocess.py`). Un estado final solo lo escribe el
   pipeline al terminar, y `complete` es una única transacción.

## Handoff hacia la Parte 2 (`schema_version: 1`, guardado en `rfp_tickets.handoff`)

`ticket_id`, `rfp_id`, `ready_for_part_2`, `metadata`, `departments_needed`, `unknown_departments`, `workstreams[]` (departamento,
responsable, motivo, `key_aspects`, `asks`, `figures`, `open_questions`, `excerpts`, `request_summary`), `open_questions`,
`conflicts`, `approvals.ceo` (`required` true/false/null, umbral 50.000 USD, Mariana Restrepo) y `summary_for_sales`.
`required: null` significa «sin monto en USD en la RFP»: no se afirma nada que el documento no diga.

## Legibilidad y costo

`py-readability-metrics` (Flesch-Kincaid, Gunning Fog, Flesch) + métricas propias siempre presentes: palabras, oraciones, tokens
estimados (caracteres/4), y Fernández-Huerta para español. Se guardan con el ticket. Límites conocidos: la librería exige ≥100
palabras y datos `punkt_tab` de NLTK, y sus fórmulas son para inglés; cuando no puede calcular, el campo queda `null` con
`library_error`, y la complejidad (baja/media/alta) usa Huerta en español. MarkItDown aplana las tablas de los PDF.

## Cómo probarlo

- Tests offline (modelo simulado, sin red): `python -m pytest tests/pipelines/test_rfp_intake.py` y, en `services/api`,
  `DATABASE_URL=sqlite:///:memory: python -m pytest tests/test_rfp_api.py`.
- Con el modelo real: `uv run python -m scripts.rfp_smoke` (los 3 PDF) y, de punta a punta, subiendo
  `tests/fixtures/rfp/brasaland-request-{1,2,3}.pdf` desde `http://localhost:3000/rfp`.
- Esperado: 1 → `analisis_completo` con los 4 departamentos y CEO requerida; 2 → `analisis_completo` con marketing, operaciones y
  procurement (sin presupuesto ni año en la fecha, anotado como pregunta abierta); 3 → `descartado`.
