# Evidencia — memoria del agente (Hito 8, Parte 1)

Generado por `tests/pipelines/test_agent_memory_evidence.py` sobre el grafo y el almacén reales; el modelo y el clasificador son los guionizados de `memory_support.py` (flujo, no calidad del modelo).

## Ciclo A — la actualización se APRUEBA y se refleja después

**carlos.jimenez** (`conv-ciclo-a1`): En realidad el proveedor de vegetales de Medellín entrega los miércoles, no los martes como dijiste antes.

**Agente** (estado `answered`):

> Gracias por la corrección, tomo nota de que entregan los miércoles.
>
> ¿Quieres que recuerde esto para la próxima vez?
> • Medellín · proveedores: El proveedor de vegetales de Medellín entrega los miércoles, no los martes.
> Responde «sí», «no» o dime cómo corregirlo.

Tras la propuesta, aún nada guardado (solo hay una propuesta pendiente):

Memoria activa: `(vacía)`

**carlos.jimenez** (`conv-ciclo-a1`): Sí, guárdalo

**Agente** (estado `memory_decision`):

> Listo, lo guardé: El proveedor de vegetales de Medellín entrega los miércoles, no los martes.

Memoria activa:

- El proveedor de vegetales de Medellín entrega los miércoles, no los martes.

Más tarde, en OTRA conversación, el agente ya lo sabe:

**carlos.jimenez** (`conv-ciclo-a2`): ¿Qué día entrega el proveedor de vegetales de Medellín?

**Agente** (estado `answered`):

> Según lo que me corrigieron: El proveedor de vegetales de Medellín entrega los miércoles, no los martes.

## Ciclo B — la actualización se RECHAZA y la memoria no cambia

Memoria antes del ciclo:

Memoria activa:

- El proveedor de vegetales de Medellín entrega los miércoles, no los martes.

**ashley.r** (`conv-ciclo-b1`): La location de Miami Beach ahora cierra a las 11pm los fines de semana, cambió el mes pasado.

**Agente** (estado `answered`):

> Entendido, el cierre de fin de semana es a las 11pm.
>
> ¿Quieres que recuerde esto para la próxima vez?
> • Miami Beach · horarios: Miami Beach ahora cierra a las 11pm los fines de semana.
> Responde «sí», «no» o dime cómo corregirlo.

**ashley.r** (`conv-ciclo-b1`): No, no lo guardes

**Agente** (estado `memory_decision`):

> Entendido, no lo guardo.

Memoria después del rechazo (idéntica):

Memoria activa:

- El proveedor de vegetales de Medellín entrega los miércoles, no los martes.

**ashley.r** (`conv-ciclo-b2`): ¿A qué hora cierra Miami Beach los fines de semana?

**Agente** (estado `no_information`):

> No tengo información suficiente en la base de conocimiento de Brasaland para responder eso.

## Registro de auditoría (solo-añadir)

Cada propuesta y su resultado, aprobada o rechazada, con quién la autorizó y cuándo:

| # | Momento (UTC) | Evento | Actor | Detalle |
|---|---|---|---|---|
| 1 | 2026-11-10T12:02:00+00:00 | `proposal_created` | agent | fact=El proveedor de vegetales de Medellín entrega los miércoles, no los martes. |
| 2 | 2026-11-10T12:04:00+00:00 | `memory_written` | carlos.jimenez | intent=approve; confidence=0.97; decision_message=Sí, guárdalo; reason= |
| 3 | 2026-11-10T12:08:00+00:00 | `proposal_created` | agent | fact=Miami Beach ahora cierra a las 11pm los fines de semana. |
| 4 | 2026-11-10T12:10:00+00:00 | `proposal_rejected` | ashley.r | intent=reject; confidence=0.97; decision_message=No, no lo guardes; reason= |

