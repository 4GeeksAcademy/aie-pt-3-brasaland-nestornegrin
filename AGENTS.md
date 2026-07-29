# AGENTS.md — Brasaland monorepo

Este archivo define cómo debe operar cualquier agente de código (Cursor, Windsurf, Claude Code, Copilot, etc.) en este repositorio. Es el acuerdo de equipo: el agente no toma decisiones por su cuenta donde este documento dice que no debe.

## 1. Qué leer al inicio de cada sesión, en este orden

1. `memory-bank/projectbrief.md` — quién es Brasaland, qué problema resuelve este proyecto, qué es Brasa Points.
2. `memory-bank/techContext.md` — stack, layout del monorepo, decisiones de arquitectura ya tomadas, restricciones técnicas.
3. `memory-bank/progress.md` — qué existe ya, qué está en curso, qué falta.
4. `.agents/rules/` (todas las reglas) — convenciones específicas que no están en el banco de memoria.
5. El `README.md` de la carpeta específica donde vayas a trabajar (`uis/README.md`, `services/README.md`, etc.) — cada carpeta documenta qué va ahí.

No escribas código de aplicación sin haber leído los tres archivos del banco de memoria. Si alguno no existe o está desactualizado, decilo antes de continuar en vez de asumir contexto genérico.

## 2. Flujo obligatorio antes de cada commit

1. **Releer** `memory-bank/progress.md` para confirmar que el cambio que vas a hacer no duplica algo ya hecho ni contradice una decisión registrada en `techContext.md`.
2. **Verificar en local** antes de commitear: `npm run typecheck` (raíz, para `src/`), y `npm run build` (o al menos `npm run dev` y comprobar que carga sin errores) en cualquier app de `uis/` que hayas tocado.
3. **Actualizar `memory-bank/progress.md`** con lo que cambió, en la misma sesión — no lo dejes para después. Un banco de memoria desactualizado deja de ser útil en días.
4. **Commit atómico y descriptivo**: un commit por unidad de trabajo lógica (una skill, una regla, una feature), mensaje que explique el qué y el porqué, no solo "update files".
5. Si el cambio toca algo de la sección 3 (carpetas protegidas), **detente y pide confirmación explícita** antes de commitear.

## 3. Carpetas y archivos que el agente NO debe modificar sin confirmación explícita del desarrollador

- `uis/talent-pipeline-tracker/` — es el entregable del Hito 3, ya evaluado. No se toca en este hito ni en los siguientes salvo instrucción explícita.
- `src/` (raíz, módulo de lógica de negocio del Hito 2) — se **importa** desde otras apps, nunca se copia ni se reescribe. Si una app necesita una función distinta, se propone como función nueva, no se edita el comportamiento validado del Hito 2.
- `index.html`, `application.html`, `validation.js` (raíz) — es el entregable del Hito 1. Se usa como referencia de contenido para `uis/website`, no se borra ni se reescribe.
- `CONTEXT.es.md` — es la fuente de verdad del negocio para este escenario (Brasaland). Solo el desarrollador la reemplaza si cambia de empresa asignada.
- `agents/` y `skills/` (sin punto, en la raíz) — son código de **producto** de la empresa (agentes/skills que Brasaland construye para sí misma en hitos futuros), no configuración del agente de código. No confundir con `.agents/`.
- `packages/shared/` — cualquier cambio a tipos compartidos afecta potencialmente a más de una app; proponer el cambio y confirmar antes de tocarlo.

## 4. Convenciones generales

- Ver `.agents/rules/` para reglas específicas por patrón de archivo o siempre-activas.
- Ver `.agents/skills/` para tareas recurrentes ya formalizadas — úsalas en vez de reinventar el procedimiento cada vez.
- Toda decisión de negocio (nombres de campos, validaciones, textos de la marca) debe coincidir exactamente con `CONTEXT.es.md`. Si no coincide, es un bug, no una libertad creativa.
