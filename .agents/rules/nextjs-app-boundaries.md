# Regla: límites entre las apps de `uis/`

**Alcance:** siempre activa — aplica a cualquier trabajo dentro de `uis/website`, `uis/backoffice`, o `uis/talent-pipeline-tracker`.

## Por qué existe

`uis/` va a seguir creciendo (más apps en hitos futuros). Sin una regla explícita, es fácil que un agente comparta un layout "para no repetir código" entre la web pública y el backoffice, o que copie lógica de negocio de `src/` en vez de importarla, y esas dos cosas generan deuda técnica difícil de deshacer.

## Qué debe cumplirse

1. **Cada app en `uis/` es un proyecto Next.js independiente** con su propio `package.json`, su propio layout raíz (`app/layout.tsx`), y su propio `README.md`. No hay un layout compartido entre `website` y `backoffice` — son audiencias distintas (pública vs. interna) y deben poder evolucionar sin coordinarse.
2. **La lógica de negocio de `src/` (raíz) se importa, nunca se copia.** Si `uis/backoffice` necesita `validateRegistration`, `filterRegistrationsByCriteria`, etc., el import apunta a la ruta relativa real de `src/` en el monorepo. Si TypeScript se queja de la resolución de módulos fuera del `rootDir` de la app, se ajusta `tsconfig.json`/`next.config.ts` de esa app — no se copia el archivo.
3. **`uis/talent-pipeline-tracker` no se modifica** desde este hito en adelante salvo instrucción explícita — es el entregable de un hito ya evaluado.
4. Si dos apps de `uis/` terminan necesitando el mismo tipo TypeScript de dominio (por ejemplo `BrasaPointsRegistration`), la señal es moverlo a `packages/shared` — pero solo cuando una segunda app lo necesite de verdad, no antes (ver `techContext.md`).

## Cómo verificar

- `uis/website` y `uis/backoffice` corren cada uno con su propio `npm run dev` desde su propia carpeta, en puertos distintos, sin depender de que el otro esté corriendo.
- Buscar (`grep`) que no exista ningún archivo en `uis/backoffice` que duplique una función ya definida en `src/utils/` o `src/validations.ts`.
