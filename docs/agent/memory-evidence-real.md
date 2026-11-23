# Evidencia con el modelo real — memoria del agente (Hito 8, Parte 1)

Corridas hechas el 2026-11-10 en el Codespace con `python -m services.agent` (RAG en Qdrant Cloud y `GENERATION_MODEL` reales,
almacén `data/memory/agent_memory.sqlite`). La evidencia del flujo con modelo guionizado está en [`memory-evidence.md`](./memory-evidence.md).

## Ciclo A — aprobado y reflejado en una conversación posterior

**carlos.jimenez** (`demo-aprobado-01`): En realidad el proveedor de vegetales de Medellín entrega los miércoles, no los martes como dijiste antes.

> Gracias por la corrección. Lo anoto: el proveedor de vegetales de Medellín entrega los miércoles. Te confirmo que en la información oficial de Brasaland el pedido de vegetales y frutas se hace lunes y jueves, con entrega en 24 horas, pero no se especifica el día de la semana de la entrega, así que tu dato lo tomo como referencia local. Cualquier cosa, conviene validarlo con compras para que quede alineado con el pedido semanal.
>
> ¿Quieres que recuerde esto para la próxima vez?
> • Medellín · proveedores: El proveedor de vegetales de Medellín entrega los miércoles, no los martes.
> Responde «sí», «no» o dime cómo corregirlo.

Ruta: `receive_question → resolve_pending → route_question → recall_memory → retrieve_context → generate_answer → propose_memory`

**carlos.jimenez** (`demo-aprobado-01`): Sí, guárdalo

> Listo, lo guardé: El proveedor de vegetales de Medellín entrega los miércoles, no los martes.

Estado `memory_decision`; ruta `receive_question → resolve_pending → acknowledge_memory` (clasificador: `approve`, confianza 1.0).

**carlos.jimenez** (`demo-aprobado-02`, otra conversación): ¿Qué día entrega el proveedor de vegetales de Medellín?

> Según la memoria aprobada por gerentes, el proveedor de vegetales de Medellín entrega los **miércoles**. Ten en cuenta que es un dato registrado por el equipo, no oficial, así que te recomiendo confirmarlo con el proveedor; de forma oficial sabemos que el pedido de vegetales y frutas se hace lunes y jueves, con entrega en 24 horas.
>
> Fuente: supplier-ordering — Frecuencia de pedido por categoría

El recuerdo se usó (`recall_memory`) y el agente lo presentó como **no oficial** contrastándolo con el RAG, sin sobrescribirlo.

## Ciclo B — rechazado y la memoria permanece sin cambios

**ashley.r** (`demo-rechazado-01`): La location de Miami Beach ahora cierra a las 11pm los fines de semana, cambió el mes pasado.

> (respuesta con la propuesta) ¿Quieres que recuerde esto para la próxima vez? • Miami Beach · horarios: …

**ashley.r** (`demo-rechazado-01`): No, no lo guardes

> Entendido, no lo guardo.

Clasificador: `reject`, confianza 1.0. `python -m services.agent.memory list` después del rechazo muestra **solo** el recuerdo aprobado del ciclo A; no hay nada de Miami Beach.

## Registro de auditoría (`python -m services.agent.memory events`)

| # | Momento (UTC) | Evento | Actor | Detalle |
|---|---|---|---|---|
| 1 | 13:59:00 | `proposal_created` | agent | Medellín · proveedores: «El proveedor de vegetales de Medellín entrega los miércoles, no los martes.» |
| 2 | 13:59:38 | `memory_written` | carlos.jimenez | intent=approve, confianza=1.0, mensaje «Sí, guárdalo» |
| 3 | 14:01:07 | `proposal_created` | agent | Miami Beach · horarios: «La location de Miami Beach ahora cierra a las 11pm los fines de semana, cambió el mes pasado.» |
| 4 | 14:01:34 | `proposal_rejected` | ashley.r | intent=reject, confianza=1.0, mensaje «No, no lo guardes» |

## Lo que mostraron las corridas reales (y se corrigió)
1. **El modelo preguntaba él mismo si anotarlo** («¿te parece bien dejarlo anotado tal cual?») y el sistema volvía a preguntarlo: pregunta duplicada.
   Se añadió una regla al prompt (`STRUCTURED_RULES`): no preguntar en `respuesta`, la pregunta la hace el sistema con el texto exacto.
2. **Guardaba referencias relativas** («cambió el mes pasado»), que dentro de unos meses no significan nada.
   Se añadió la regla «sin referencias relativas al tiempo» al prompt. Cubierto por `test_prompt_keeps_the_proposal_timeless_and_leaves_the_question_to_the_system`.
