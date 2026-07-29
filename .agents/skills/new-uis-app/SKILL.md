---
name: new-uis-app
description: Scaffold a new frontend application inside uis/ following this monorepo's conventions (own Next.js project, own layout, README, correct imports from root src/ or packages/shared instead of copies). Use when adding a new app under uis/ — a new customer portal, internal tool, dashboard, etc.
---

# Skill: crear una nueva app en `uis/`

## Objetivo

Este monorepo va a acumular varias apps bajo `uis/` a lo largo de los hitos (ya tiene `website`, `backoffice`, `talent-pipeline-tracker`, y habrá más). Cada vez que se agrega una, hay una lista fija de cosas que deben quedar bien desde el primer commit para que el agente (y el resto del equipo) puedan navegar el repo sin ambigüedad. Esta skill formaliza esa tarea recurrente en un procedimiento verificable, en vez de reconstruirlo de memoria cada vez.

**Objetivo único:** dejar una nueva app de `uis/` corriendo localmente, con la estructura y documentación que el resto del monorepo espera, sin duplicar código que ya existe en otro lugar del repo.

## Inputs

- `appName`: nombre de la carpeta bajo `uis/` (kebab-case, ej. `backoffice`, `website`, `loyalty-portal`).
- `audience`: quién la usa — `"pública"` (clientes/visitantes) o `"interna"` (equipo Brasaland).
- `needsBusinessLogic`: si la app necesita importar algo de `src/` (Hito 2) o de `packages/shared` — sí/no, y qué símbolos exactos si aplica.
- `contextSource`: qué parte de `CONTEXT.es.md` describe el contenido/reglas de negocio de esta app (para no inventar copy ni validaciones).

## Procedimiento

1. Revisar `uis/README.md` y confirmar que la app corresponde ahí (tiene interfaz de usuario) y no a `services/`.
2. Crear `uis/<appName>/` con `npx create-next-app@latest` (TypeScript + Tailwind, App Router), usando las mismas versiones de Next.js/React/Tailwind que las otras apps de `uis/` (ver `memory-bank/techContext.md`) salvo que haya una razón documentada para divergir.
3. Si `needsBusinessLogic` es sí: importar los símbolos necesarios desde su ruta original (`../../../src/...` desde la raíz del monorepo, o desde `packages/shared` si ya están promovidos ahí) — nunca copiar el archivo. Ajustar `tsconfig.json` de la app si hace falta para que la resolución de módulos fuera de su propio `rootDir` funcione.
4. Escribir `uis/<appName>/README.md` con: objetivo de la app, audiencia, cómo correrla en local (`npm install && npm run dev`), y qué importa de fuera de su propia carpeta (si algo).
5. Confirmar que el layout de la nueva app es independiente — no reutiliza el `app/layout.tsx` de otra app de `uis/` (ver `.agents/rules/nextjs-app-boundaries.md`).
6. Añadir la app a la tabla de `memory-bank/techContext.md` (qué contiene, estado).

## Output esperado

- Carpeta `uis/<appName>/` con un proyecto Next.js completo, corriendo con `npm run dev` sin errores.
- `uis/<appName>/README.md` documentando la app.
- Si aplica, imports funcionando hacia `src/` o `packages/shared` (no copias).
- `memory-bank/techContext.md` actualizado con la nueva app.

## Criterios de aceptación (verificables)

- [ ] `cd uis/<appName> && npm install && npm run dev` levanta la app sin errores en consola.
- [ ] `npm run build` (o `next build`) pasa sin errores de TypeScript.
- [ ] `uis/<appName>/README.md` existe y no está vacío.
- [ ] Si `needsBusinessLogic` era sí: `grep -r "from '.*src/" uis/<appName>/` (o el import correspondiente) encuentra al menos un import real hacia el módulo original — y `grep` NO encuentra una copia del archivo fuente dentro de `uis/<appName>/`.
- [ ] El `app/layout.tsx` de la nueva app es un archivo propio, distinto al de cualquier otra app de `uis/` (no hay un import cruzado de layout entre apps).
- [ ] `memory-bank/techContext.md` menciona la nueva app en la tabla de layout del monorepo.
