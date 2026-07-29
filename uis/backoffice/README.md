# uis/backoffice

App interna (audiencia: equipo Brasaland) para revisar los registros del
programa Brasa Points. Es el lugar donde el módulo TypeScript del Hito 2
(`src/` en la raíz del monorepo) se integra y se muestra en pantalla, en vez
de solo ejecutarse por consola como en el Hito 2 original (`src/demo.ts`).

## Cómo correrla en local

```bash
cd uis/backoffice
npm install
npm run dev
```

Abre `http://localhost:3000` (usa otro puerto si `uis/website` ya está
corriendo, Next.js lo asigna automáticamente).

## Qué muestra

- Estadísticas agregadas de edad de los registros (`aggregateNumbers`).
- Conteo de registros por país y por canal de origen
  (`countRegistrationsByCountry`, `countRegistrationsBySource`).
- Tabla filtrable por país y ordenable por nombre/país/ciudad/fecha
  (`filterRegistrationsByCriteria`, `sortBy`).
- Búsqueda de un registro por email (`linearSearch`) y búsqueda de una edad
  exacta sobre el arreglo de edades ordenado (`binarySearch`).
- Validación de un registro de ejemplo con errores (`validateRegistration`),
  mostrando la lista de errores en pantalla.

## Qué importa de fuera de esta carpeta

- Todas las funciones de negocio anteriores se importan desde
  `../../../src/index` (barrel de `src/`), **no se reimplementan**.
- `data/sample-registrations.ts` contiene únicamente datos de muestra para
  poblar la vista — no es lógica de negocio, por eso vive dentro de esta app.

## Notas

- Layout propio (`app/layout.tsx`), independiente del de `uis/website` y de
  `uis/talent-pipeline-tracker` (ver `.agents/rules/nextjs-app-boundaries.md`).
- No hay autenticación en este hito (ver `memory-bank/techContext.md`).
