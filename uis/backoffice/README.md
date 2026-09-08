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

## Autenticación

- `/login` inicia sesión contra `POST /auth/login` y guarda el JWT en `localStorage`.
- `/register` crea el usuario en `POST /users`, inicia sesión automáticamente y muestra errores de validación por campo.
- `/account/profile` consulta `GET /auth/me` y actualiza el perfil con `PUT /profiles/me`.
- El dashboard y el perfil tienen un guard cliente; las llamadas protegidas adjuntan `Authorization: Bearer` y un `401` limpia la sesión y redirige a `/login`.
- La aplicación pública `uis/website` permanece sin guard ni autenticación.

## Notas

- Layout propio (`app/layout.tsx`), independiente del de `uis/website` y de
  `uis/talent-pipeline-tracker` (ver `.agents/rules/nextjs-app-boundaries.md`).
- La API debe estar disponible en `http://localhost:8000` o configurarse mediante `NEXT_PUBLIC_API_URL`.
