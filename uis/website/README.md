# uis/website

App pública (audiencia: clientes/visitantes) que migra y mejora la web
corporativa del Hito 1 (`index.html`, `application.html`, `validation.js`)
a Next.js + TypeScript, con componentes reutilizables en vez de HTML plano.

## Cómo correrla en local

```bash
cd uis/website
npm install
npm run dev
```

Abre `http://localhost:3000`.

## Rutas

- `/` — home con todas las secciones del Hito 1 (historia, valores, ubicaciones,
  teaser de Brasa Points, contacto), migradas a componentes React (`components/*`).
- `/brasa-points` — formulario de registro a Brasa Points (reemplaza
  `application.html`), con validación en tiempo real por campo.

## Qué importa de fuera de esta carpeta

- Tipos y funciones de validación del Hito 2 (`../../../src/types/models`,
  `../../../src/validations`) — usados en `components/brasa-points-form.tsx`.
  No se copia ningún archivo de `src/`, solo se importa.
- Los datos de ciudades/ubicaciones en cascada (`lib/locations-data.ts`) están
  documentados en `.agents/rules/brasa-points-cascading-fields.md` — cualquier
  cambio a las 14 ubicaciones debe hacerse ahí y no duplicarse en otro archivo.

## Notas

- `next.config.ts` permite imágenes remotas de `images.unsplash.com` (usadas
  en la sección "Nuestra Historia" vía `next/image`).
- Este proyecto no comparte layout con `uis/backoffice` ni con
  `uis/talent-pipeline-tracker` (ver `.agents/rules/nextjs-app-boundaries.md`).
