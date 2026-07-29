# Tech Context — Brasaland monorepo

**Última actualización:** milestone 4 — infraestructura de agentes, `uis/website` y `uis/backoffice` completados y verificados (`npm run build` y `npm run dev` sin errores en ambas apps).

## Layout del monorepo (decidido, no negociable sin discutirlo)

Este es un **monorepo por dominio de negocio**, no un monorepo de librerías genéricas. Cada carpeta raíz tiene una única responsabilidad (ver `README.md` de cada una antes de añadir algo nuevo):

| Carpeta | Contiene | Estado en este hito |
|---|---|---|
| `uis/website` | Web pública Next.js (Hito 1 migrado, ruta `/` + `/brasa-points`) | **Nuevo en este hito — build y dev verificados** |
| `uis/backoffice` | App interna Next.js, integra y muestra en pantalla la lógica del Hito 2 | **Nuevo en este hito — build y dev verificados** |
| `uis/talent-pipeline-tracker` | App generada con IA (Hito 3) | Existente, **no se toca** en este hito |
| `src/` (raíz) | Módulo de lógica de negocio TypeScript puro (Hito 2) | Existente — `uis/backoffice` lo **importa**, nunca lo copia |
| `index.html`, `application.html`, `validation.js` | Web pública Hito 1 en HTML/JS plano | Existente — es la fuente de contenido para `uis/website`, se conserva en su lugar como histórico del hito |
| `agents/`, `skills/` (sin punto) | Agentes y skills que la empresa construye como **producto** (ej. futuro agente de pedidos de ingredientes) | Vacíos/plantilla, no relacionados con este hito |
| `.agents/` | Configuración del agente de código (reglas + skills para Cursor/Claude/etc.) | **Nuevo en este hito** |
| `memory-bank/` | Este banco de memoria | **Nuevo en este hito** |
| `packages/shared` | Tipos TypeScript compartidos entre apps (`@repo/shared-types`) | Existente, placeholder — candidato futuro para mover ahí los tipos de `src/types/models.ts` si más de una app los necesita |
| `services/` | Backend centralizado (FastAPI) | Vacío — este hito no requiere API |

**Distinción importante (viene del enunciado, se repite aquí a propósito):** `.agents/` configura la *herramienta* de desarrollo (qué reglas sigue el agente de código en este repo). `agents/` y `skills/` sin punto son *código de producto* de la empresa. No se mezclan.

## Stack técnico

- **`uis/website`**: Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS v4 (`@tailwindcss/postcss`), mismas versiones que `uis/talent-pipeline-tracker` para mantener consistencia dentro de `uis/`.
- **`uis/backoffice`**: mismo stack (Next.js 16 + React 19 + TS + Tailwind v4), layout completamente separado del de `website` (son dos experiencias distintas: pública vs. interna).
- **Módulo de lógica de negocio (Hito 2)**: TypeScript puro en `src/` (raíz del monorepo), sin dependencias de framework ni de DOM — por diseño, para poder importarse desde cualquier UI futura. Se valida con `npm run typecheck` (`tsc --noEmit`) desde la raíz.
- **Gestión de dependencias**: cada app en `uis/` mantiene su propio `package.json` (no hay workspace runner configurado a nivel raíz todavía — así lo documenta el `README.md` raíz). `uis/backoffice` importa `src/` vía ruta relativa de TypeScript (`../../../src`), no vía un paquete publicado.

## Decisiones de arquitectura tomadas en este hito

1. **No se reescribe el Hito 1 desde cero visualmente.** El contenido, copy, y estructura de secciones de `index.html`/`application.html` (definidos en `CONTEXT.es.md`) se migran tal cual a componentes React tipados; lo que cambia es la implementación (HTML+Tailwind CDN → Next.js + Tailwind compilado + componentes reutilizables), no el contenido de negocio.
2. **La lógica de negocio del Hito 2 se importa, no se copia**, en `uis/backoffice`. Si en el futuro más de una app necesita esos tipos, se promueven a `packages/shared` — pero eso no ha pasado todavía, así que no se hace preventivamente.
3. **`uis/backoffice` no incluye autenticación ni backend real en este hito.** Es la vista de entrada + la demo visible de la lógica de negocio. Un futuro hito conectará `services/` cuando haya un caso de uso que lo requiera.
4. **Restricción de negocio que el agente debe respetar siempre:** Brasa Points es un programa de fidelización, no un sistema de pedidos. Ninguna feature de `uis/website` debe implicar checkout, carrito, o pedidos en línea.

## Restricciones técnicas

- Idioma base del sitio público: **español** (heredado del Hito 1 — no se agregó un segundo idioma, era opcional).
- Los campos "Ciudad" y "Ubicación favorita" del formulario Brasa Points son **dependientes en cascada** de País → Ciudad → Ubicación — esta relación está codificada como datos en `validation.js` (Hito 1) y debe preservarse exactamente igual al migrar a React (mismo mapa país→ciudad→ubicaciones, ver `.agents/rules/`).
- Validación de teléfono exige prefijo de país exacto (+57 Colombia, +1 EE.UU.) — regla de negocio, no solo de formato.
- Node.js 22.x / npm 10.x (versión usada para verificar el build en esta sesión).
