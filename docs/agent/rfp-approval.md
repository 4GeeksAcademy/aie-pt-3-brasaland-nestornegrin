# Aprobación humana y cierre del documento (Hito 9 · Parte 3)

Última pieza del flujo: antes de dar por buena la sección de un departamento hay un **punto de aprobación humana real** (`interrupt` de
LangGraph con checkpointer). Cuando todos los responsables dan su visto bueno (y la CEO, si el contrato supera 50.000 USD/año), el
documento final se genera solo. Es el mismo ticket de la Parte 1: sin saltos de estado y con la traza de cada paso.

## Arquitectura

```
Parte 2 termina (en_evaluación | needs_human_review) ─auto─▶ ApprovalEngine.start ──▶ esperando_aprobación

 TICKET  thread `rfp-{ticket}`:   open ─▶ converge ─┬─ ramas por abrir ─Send×N─▶ branch[dept]  (en paralelo; cada una corre hasta SU interrupt)
                                  (arbitraje §7)    ├─ todo aprobado + CEO ok + sin conflicto ─▶ synthesize ─▶ close ─▶ terminado
                                                    └─ si no: el ticket sigue en esperando_aprobación

 RAMA    thread `rfp-{ticket}:{dept}`  (también `…:ceo`):
         prepare ─▶ await_approval ⏸ interrupt(ficha de decisión) ─▶ record ─┬─ approve ─────────────▶ FIN (aprobado)
            ▲                                                                ├─ reject / request_changes, quedan rondas ─▶ regenerate ─┐
            └────────────────────────────────────────────────────────────────┘   (generador de la Parte 2, SOLO ese depto)            │
                                                                                └─ rondas agotadas ─▶ escalate ─▶ última pausa: decide Camila (árbitro) ─▶ FIN
 resume:  ApprovalEngine.resume(ticket, decisión) ─ valida ─▶ Command(resume=…) sobre el checkpoint de ESA rama ─▶ converge
```

- **Pausa solo de la rama afectada.** Cada departamento tiene su propio hilo de checkpoint: no comparten *superstep*, así que aprobar a B mientras A
  sigue interrumpido no toca el checkpoint de A (probado: `test_approving_department_b_while_department_a_stays_interrupted`, y las ramas se abren
  en paralelo real con una barrera de 4 hilos).
- **`resume` es un punto de entrada explícito**: reanuda únicamente el checkpoint de la rama que decidió; no reinicia el flujo ni regenera nada
  (se prueba que `prepare` no vuelve a ejecutarse y que el checkpoint sobrevive a un «reinicio» del proceso con una conexión nueva al archivo).
- **Identidad del checkpoint**: `thread_id = rfp-{ticket_id}` (coordinador) y `rfp-{ticket_id}:{departamento}` (ramas; la CEO es `…:ceo`).
  Dos tickets concurrentes nunca comparten checkpoint (se verifica leyendo los `thread_id` reales de la tabla `checkpoints`).
- **Checkpointer** (`checkpoint.py`): SQLite en archivo por defecto (`RFP_CHECKPOINT_DB`, `data/runtime/rfp_checkpoints.sqlite`); PostgreSQL con
  `RFP_CHECKPOINT_BACKEND=postgres` (`RFP_CHECKPOINT_DB_URL` o `DATABASE_URL`); en memoria solo si se pide `RFP_CHECKPOINT_DB=:memory:` (desarrollo).
- **Dónde está la verdad**: PostgreSQL (SQLModel) guarda decisiones, rondas, historial, conflictos, documento final y traza; el checkpoint solo
  recuerda *dónde quedó cada rama*. Un error se registra en `processing_error` y se reintenta (`/approval/retry`) sin volver a pedir aprobaciones.

## Estados del ticket (BRIEFING §2.3; no se inventan otros)

`analisis_completo → generando_borrador → en_evaluación | needs_human_review` (Partes 1–2, sin cambios) `→ esperando_aprobación → terminado`.
Mientras alguna aprobación está pendiente el ticket está en `esperando_aprobación`; `terminado` solo cuando el documento final está guardado y accesible
(`GET /rfp/tickets/{id}/document`). Los valores de las Partes 1–2 se conservan en la misma fila.

## Arbitraje (nodo determinista, sin LLM) — BRIEFING §7

Se ejecuta en `converge`: al abrir y después de cada decisión. Detecta los triggers sobre **estado estructurado**, no sobre conversación:

| Trigger | Se detecta en… | Árbitro fijo | Resolución |
|---|---|---|---|
| `setup-sla-breach` | texto de **cada** sección (parser de plazos de la Parte 2: días/semanas/horas/meses, rangos, números en letras) | Felipe Guerrero rechaza (`operaciones`); Camila Ospina escala si otro depto lo embebe | `request_changes` forzado hasta ≥ 10 días hábiles en todas partes; además un borrador así **no puede aprobarse** (guardrail) |
| `cost-vs-feasibility` | cifras estructuradas: `costo_*_por_{cubierto,evento}_usd` (procurement) > `precio_*_por_{cubierto,evento}_usd` (operaciones) | Camila Ospina | «subir precio o reducir alcance»: `request_changes` forzado en las dos secciones desalineadas |
| `ceo-threshold` | valor anual estimado > 50.000 USD y la aprobación de la CEO pendiente | Mariana Restrepo | bloquea la síntesis; si rechaza, **marketing** vuelve a cambios con su comentario y la CEO se reabre al re-aprobarse |

Cada conflicto queda en `rfp_tickets.conflicts_log` (`abierto`/`resuelto`, árbitro, evidencia, referencia al BRIEFING) y en la traza como
`arbiter:<nombre>`. Las cifras estructuradas las aporta cada responsable al decidir (`figures`), p. ej. `{"costo_insumos_por_cubierto_usd": "11.20"}`.

**Límite de iteraciones**: `RFP_MAX_APPROVAL_ROUNDS` (3 por defecto) rondas de aprobación por sección; al alcanzarlo la sección se **escala** a Camila
Ospina (árbitro fijo): la rama se pausa **una última vez**, ahora también ella puede decidir, y no hay otra vuelta al generador. Si aprueba, la sección queda aprobada
(`escalated_decision`); si rechaza, el rechazo es definitivo y el ticket **no se cierra** solo. Se aplica en código (`graph.py`) y se prueba (`test_iteration_limit_…`).
Si un conflicto de costo sigue abierto, el árbitro lo resuelve aprobando la sección escalada; `setup-sla-breach` y `ceo-threshold` no se pueden anular.

## Documento final

`document.py` (*ultimate document synthesizer*) es determinista a propósito: un documento que va al cliente no debe contener texto que nadie aprobó. Ensambla
las secciones aprobadas, añade la validez de la oferta (30 días desde la emisión, §5) y un cuadro de aprobaciones, y verifica con el evaluador de cumplimiento de la
Parte 2 que el documento consolidado respete el §5 (si no, falla visible y reintentable). Se guarda en `rfp_final_documents` (`FinalDocument`: `ticket_id`, `sections`,
`total_estimated_value`, `generated_at`). La síntesis corre una sola vez aunque las dos últimas aprobaciones lleguen a la vez (`claim_close`, atómico en la base de datos).

## Trazabilidad

Cada ejecución de nodo de las **tres partes** deja un evento (`rfp_trace.emit`): agente, nodo, entrada y salida resumidas, `thread_id` y marca de tiempo, en orden
(`rfp_trace_events`, `GET /rfp/tickets/{id}/trace`, y también en el estado de los grafos de la Parte 3). Agentes: `converter`, `classifier`, `worker:<dept>`, `generator:<dept>`,
`evaluator-*:<dept>`, `arbiter:<nombre>`, `human:<nombre>`, `ultimate-synthesizer`… Los textos largos se recortan y el PDF/handoff completo nunca se vuelca.

## Preguntas de diseño

1. **¿Qué pasa si un departamento rechaza tras la interrupción?** Vuelve al **generador de la Parte 2 de ese departamento** (no hay una nueva ejecución completa ni se toca a los
   demás) con el comentario humano como feedback; los tres evaluadores la revisan otra vez y se abre una nueva interrupción (ronda + 1). `reject` queda registrado como
   `rechazado`, `request_changes` como `pendiente`; ambos exigen explicar qué corregir. Tras `RFP_MAX_APPROVAL_ROUNDS` se escala a Camila.
2. **¿Qué necesita ver un humano para decidir?** Una **ficha** (`review_packet`) con lo mínimo: contexto del trato (cliente, servicio, alcance, fecha límite, valor), su borrador, si es
   *provisional* y por qué, el veredicto de los 3 evaluadores (reglas incumplidas, aspectos sin cubrir, feedback), lo pendiente/abierto, los conflictos que le afectan, qué se
   pidió en la ronda anterior y quién puede decidir. La CEO ve valor, umbral y el estado de cada sección. No hace falta releer el documento.
3. **¿Cómo se detectan los triggers en estado estructurado?** `arbiter.detect` es una función pura sobre `sections` (texto, cifras `figures`, estados) y `ceo_approval`: mismo
   estado → mismos conflictos. SLA: parser de plazos sobre cada borrador; costo-vs-factibilidad: comparación numérica de cifras con unidad; CEO: valor estimado vs 50.000 con
   estado de aprobación. El resultado es un registro (`conflicts_log`) que fuerza cambios reales: no es un nodo decorativo (hay pruebas que verifican la regeneración, el árbitro y el cierre).

## Cómo probarlo

```bash
uv run python -m pytest tests/pipelines/test_rfp_approval.py -q                                   # unitarias + paralelismo + E2E con resumes simulados
cd services/api && DATABASE_URL=sqlite:///:memory: uv run python -m pytest tests/test_rfp_api.py -q; cd ../..
uv run python -m scripts.rfp_e2e            # E2E reproducible offline (modelo simulado); --real usa el modelo real
```

API: `POST /rfp/tickets/{id}/approvals/{departamento|ceo}` `{action, approver, comment, figures}` (422 si la respuesta no es válida, 409 si no hay interrupción
pendiente), `POST …/approval/start`, `POST …/approval/retry`, `GET …/trace`, `GET …/document`. Se encadena sola tras la Parte 2 (`RFP_AUTO_REVIEW=0` lo apaga).

## Límites y supuestos

- **Identidad del aprobador**: el BRIEFING nombra al responsable por departamento, pero el modelo de usuarios no lo enlaza con un departamento. Se valida el nombre declarado
  (`approver`) contra el responsable (§2.1) y se audita el usuario autenticado (`submitted_by`). No es autorización fuerte.
- El checkpointer de **PostgreSQL** está implementado (`langgraph-checkpoint-postgres`) pero no se ha verificado contra una base real en CI; SQLite es la ruta probada.
- Un `converge` a la vez por ticket mediante un candado **del proceso**; con varios procesos de API el cierre sigue protegido por `claim_close` (base de datos), pero el arbitraje
  podría ejecutarse dos veces.
- La CEO decide **después** de que todos los departamentos aprobaron (aprueba la propuesta consolidada, antes de la síntesis).
- Un borrador que viola `setup-sla-breach` no se puede aprobar; si el generador no lo corrige dentro del límite de rondas, el ticket queda en `esperando_aprobación` y hace falta intervención
  (no hay edición manual del texto: solo `request_changes`).
- `cost-vs-feasibility` necesita cifras estructuradas aportadas por los responsables al decidir; los *workers* de la Parte 1 solo extraen cifras literales de la RFP.
