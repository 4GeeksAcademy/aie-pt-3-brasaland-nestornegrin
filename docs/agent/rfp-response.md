# Generación de respuestas a RFPs (Hito 9 · Parte 2)

Flujo agéntico que toma el `handoff` de la Parte 1 y, **por departamento**, genera la sección de la propuesta, la evalúa en paralelo
(legibilidad, pertinencia, cumplimiento del BRIEFING §5) y la devuelve al generador con feedback hasta que pasa o se agota el límite
de iteraciones. No re-lee el PDF: la única entrada es `ticket_id` + el `handoff` persistido (`schema_version 1`, `ready_for_part_2`).

## Arquitectura

```
analisis_completo ─POST /rfp/tickets/{id}/generate (o encadenado al terminar la Parte 1)─▶ generando_borrador
                                                                                       │ BackgroundTasks
              data/pipelines/rfp_response  (grafo `rfp_response`, separado del de la Parte 1)
 load ─▶ section[marketing]   ─┐         cada `section` = subgrafo por departamento:
         section[operaciones]  ├▶ finish      generate ─▶ ─┬▶ eval_readability ─┐
         section[procurement]  │  (Send API,               ├▶ eval_relevance   ─┼▶ decide ─┬─ pasa ───────────▶ paso
         section[training]    ─┘   en paralelo)            └▶ eval_compliance  ─┘          ├─ falla y quedan iteraciones ─▶ generate (con feedback)
                                                                                           └─ falla y se agotaron ─▶ needs_human_review
```

- Routers (`services/api/app/rfp/routes.py`) solo disparan/consultan. Lógica en `data/pipelines/rfp_response/`; el pipeline recibe un
  `ResponseStore` (SQL en `services/api/app/rfp/repository.py`, en memoria en los tests).
- **PostgreSQL (SQLModel)** es la fuente de verdad: `rfp_department_sections` guarda `draft_content`, `evaluation_results`,
  `iterations`, `evaluation_history`, `needs_human_review`, `pending_items`, `generation_status`; `rfp_tickets` guarda `part3_handoff`
  y `response_completed_at`. `create_all` no añade columnas a tablas existentes → `schema_sync.ensure_columns` hace `ALTER TABLE … ADD COLUMN`
  idempotente al arrancar la API (columnas nuevas nullable).
- **Estados del ticket** (solo los de esta parte; no se reescribe `analisis_completo`, los de la Parte 3, `esperando_aprobación` y `terminado`, los escribe [`rfp-approval.md`](rfp-approval.md)):
  `analisis_completo` → `generando_borrador` → `en_evaluación` (todas pasaron: queda con `response_completed_at`) | `needs_human_review`.
- **Estados de sección**: `pendiente | generando | en_evaluacion | paso | needs_human_review | error`.
- **Endpoint** `POST /rfp/tickets/{id}/generate` (202): arranca desde `analisis_completo`; **reanuda** tras un fallo/parada (solo rehace las
  secciones que fallaron); `?regenerate=true` rehace desde `en_evaluación` terminado o `needs_human_review`. 409 si corre, si está
  `analizando` o `descartado`. Se encadena solo tras la Parte 1 (`RFP_AUTO_GENERATE=0` lo apaga). El reproceso de la Parte 1 queda cerrado
  una vez iniciada la Parte 2.

## Agentes

| Agente | Recibe | Qué verifica el código (no el modelo) |
|---|---|---|
| Generador (×N, uno por departamento) | metadatos compartidos + **su** workstream + `precios_referencia` + feedback previo | Salida validada con pydantic (reintento de reparación); si falla, la sección queda en `error` visible |
| Legibilidad | solo el texto | Fernández-Huerta ≥ 45 (es), ≤ 30 palabras/frase, 60–400 palabras, FK ≤ 14 (en) — `py-readability-metrics` |
| Pertinencia (LLM juez) | texto + `key_aspects` | Cada aspecto «cubierto» exige una **cita literal** del borrador; si no aparece, cuenta como faltante |
| Cumplimiento | texto + departamento + cifras permitidas | **Determinista en código** (`rules.py`), una regla por lineamiento del BRIEFING §5 |

### Reglas de cumplimiento

| `rule_id` | Lineamiento | Cómo se evalúa |
|---|---|---|
| `price-dual-currency` | §5: todo precio en COP **y** USD | Todo importe debe ir con su equivalente en la otra moneda |
| `brand-pillars` | §5: los tres pilares al menos una vez | Exigido en la sección dueña (`marketing`): calidad consistente, experiencia cálida, velocidad de servicio |
| `setup-sla-breach` | §5/§7: montaje/entrega ≥ 10 días hábiles | Parser de plazos (días/semanas/horas/meses, rangos, números en letras) |
| `no-competitors` | §5: sin nombres de competidores | Lista configurable (ver supuestos) |
| `offer-validity-30d` | §5: validez de 30 días | Exigida en `marketing`; las demás secciones solo no pueden contradecirla |
| `no-invented-figures` | §2.3: nunca inventar números | Toda cifra del borrador debe existir en el handoff |

El umbral de 50.000 USD/año (aprobación CEO) **no** se evalúa aquí: es de la Parte 3 (`ceo-threshold`).

## `EvaluationResult` (persistido por sección)

```json
{"section_id": "operaciones", "department_id": "operaciones", "iteration": 1,
 "readability": {"pass": true, "score": 73.4, "details": {"metrics": {"…": "…"}, "problems": []}},
 "relevance":   {"pass": true, "missing_aspects": []},
 "compliance":  {"pass": false, "rule_ids": ["setup-sla-breach"], "violations": [{"rule_id": "setup-sla-breach", "message": "…", "excerpt": "…", "briefing_ref": "§5 / §7"}]},
 "overall_pass": false, "feedback_for_generator": "…"}
```

## Respuestas a las preguntas de diseño

1. **¿Qué estado necesita cada evaluador?** Solo su porción, entregada por el payload de `Send`: legibilidad → el texto; pertinencia →
   texto + `key_aspects` de ese departamento; cumplimiento → texto + `department_id` + cifras permitidas. Ninguno necesita el documento
   completo ni las secciones de otros departamentos: cada regla del §5 se puede decidir dentro de una sola sección (la coherencia
   entre secciones —p. ej. `cost-vs-feasibility`— es de la Parte 3, que sí ve el documento completo).
2. **¿Cómo se evitan conflictos de escritura en paralelo?** Cada evaluador escribe **únicamente** su `{kind, iteration, result}` en una lista
   con reducer (`operator.add`) y nunca toca el borrador ni el estado de otro. El nodo `decide` es un *join* (`add_edge([3 evaluadores], "decide")`):
   solo corre cuando los tres terminaron y fusiona los resultados de la iteración actual. Las secciones son subgrafos independientes; el
   único estado compartido entre departamentos es de solo lectura, y cada sección escribe solo su propia fila en la base de datos.
3. **¿Cómo ve Ventas una sección `needs_human_review`?** Como **borrador provisional**: la UI muestra la insignia «Borrador provisional — requiere
   revisión humana», el último borrador, los chips de legibilidad/pertinencia/cumplimiento y el último feedback abierto. La sección va en el
   `part3_handoff` con `needs_human_review: true`, `provisional: true` y `approval_status: pendiente`; el ticket no se descarta nunca.
4. **¿El feedback es suficientemente específico?** Se construye en código, no lo redacta el modelo: incluye el `rule_id`, la referencia al BRIEFING,
   la **frase exacta** que viola la regla y qué corregir; para pertinencia, el aspecto concreto sin cubrir; para legibilidad, la métrica y las frases
   más largas. Ejemplo real:
   `[CUMPLIMIENTO · setup-sla-breach · BRIEFING §5 / §7] Promete montaje/entrega en ≈5 días hábiles; el mínimo permitido es 10. Frase: «Garantizamos el montaje en 5 días hábiles.».`

## Ejemplos

**Sección que pasa** (`operaciones`, Sunset Bay Resorts): legibilidad 73,4 · pertinencia ✓ · cumplimiento ✓ (sin violaciones)

> Operaciones evaluará la viabilidad de atender a Sunset Bay Resorts, LLC. Revisaremos la capacidad de cocina, el personal y el flujo de servicio en el sitio del cliente. El plazo de montaje está pendiente de confirmar y nunca será menor a 10 días hábiles.
> - Capacidad: la RFP no indica el volumen completo, por eso queda pendiente de confirmar.
> - Costo operativo por evento: pendiente de definir cuando recibamos los datos que faltan.
> - Personal: el plan se ajustará a la temporada y al horario del servicio.

**Sección que falla**: el mismo texto con «Garantizamos el montaje en 5 días hábiles.» → `compliance.pass == False`, `rule_ids == ["setup-sla-breach"]`,
`overall_pass == False` y el feedback citado arriba vuelve al generador. Si tras `RFP_MAX_ITERATIONS` intentos sigue fallando, queda con su último
borrador y su `EvaluationResult`, `needs_human_review` y entra en el handoff a la Parte 3.

## Handoff a la Parte 3 (`rfp_tickets.part3_handoff`)

`ready_for_part_3`, `sections[]` (`draft_content`, `evaluation`, `iterations`, `needs_human_review`, `provisional`, `approval_status: pendiente`),
`needs_human_review[]`, `all_sections_passed`, `approvals.ceo`, `conflicts`, `open_questions`.

## Configuración y probar

| Variable | Por defecto | Efecto |
|---|---|---|
| `RFP_MAX_ITERATIONS` | 3 | Límite de iteraciones por sección |
| `RFP_AUTO_GENERATE` | 1 | Encadena la Parte 2 al terminar la Parte 1 |
| `RFP_USD_COP_RATE` | sin definir | TRM para mostrar precios de referencia en COP y USD |
| `RFP_COMPETITORS` | lista por defecto | Nombres de competidores a vetar (separados por coma) |

```bash
uv run python -m pytest tests/pipelines/test_rfp_response.py -q                              # pipeline
cd services/api && DATABASE_URL=sqlite:///:memory: uv run python -m pytest tests/test_rfp_api.py -q; cd ../..   # API
uv run python -m scripts.rfp_smoke --generate                                                # modelo real (necesita GENERATION_MODEL…)
```

## Límites y supuestos

- El BRIEFING **no** lista competidores: la lista por defecto es un supuesto, sobrescribible con `RFP_COMPETITORS`. Confirmar con Marketing.
- Sin `RFP_USD_COP_RATE` el generador **no escribe importes** («pendiente de definir»): nunca inventa una TRM ni cifras.
- El umbral de legibilidad (Huerta ≥ 45, ≤ 30 palabras/frase, 60–400 palabras) es una elección razonable, no del BRIEFING.
- El acceso a la base de conocimiento por el generador (opcional en el ticket) **no** se implementó.
- El juez de pertinencia es un LLM acotado por verificación en código (cita literal); no sustituye la revisión humana.
