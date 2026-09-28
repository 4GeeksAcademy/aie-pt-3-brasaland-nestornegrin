# Auditoría de rendimiento

Fecha: 2026-09-28

## Método

Se ejecutó Lighthouse 13.5.0 sobre builds de producción de Next.js 16.2.12, con Chromium 1161 dentro de un contenedor reproducible. Se usaron los mismos URLs, viewport y flags antes y después. La web se auditó en `/` y `/brasa-points`, en escritorio y móvil. El backoffice se auditó en `/login` y, con una cuenta temporal de desarrollo, en el dashboard `/` en escritorio y móvil.

Los informes HTML/JSON y las capturas están en `docs/evidence/lighthouse/before/` y `docs/evidence/lighthouse/after/`.

## Línea base

Formato de puntuaciones: Performance / Accessibility / Best Practices / SEO.

| Frontend | Vista | Modo | Antes | LCP | TTFB |
| --- | --- | --- | --- | --- | --- |
| Website | `/` | Escritorio | 100 / 100 / 100 / 100 | 0.6 s | 10 ms |
| Website | `/` | Móvil | 92 / 100 / 100 / 100 | 1.3 s | 0 ms |
| Website | `/brasa-points` | Escritorio | 100 / 100 / 100 / 100 | 0.5 s | 0 ms |
| Website | `/brasa-points` | Móvil | 99 / 100 / 100 / 100 | 0.8 s | 0 ms |
| Backoffice | `/login` | Escritorio | 100 / 100 / 100 / 100 | 0.5 s | 20 ms |
| Backoffice | `/login` | Móvil | 100 / 100 / 100 / 100 | 1.0 s | 0 ms |
| Backoffice | `/` autenticado | Escritorio | 100 / 100 / 96 / 100 | 0.6 s | 10 ms |
| Backoffice | `/` autenticado | Móvil | 94 / 100 / 96 / 100 | 2.9 s | 10 ms |

La medición autenticada usa `localhost`, que es un origen permitido por la API. La cuenta temporal no se guarda en el repositorio.

## Problemas y causa raíz

### 1. Imagen LCP cargada como lazy en la web

- **Dónde:** `uis/website/components/our-story-section.tsx`, imagen remota de la sección Nuestra Historia.
- **Evidencia:** Lighthouse marcó `lcp-lazy-loaded` y `largest-contentful-paint-element` en la home. Next.js también avisó durante el arranque que esa imagen era el LCP y debía cargarse eager.
- **Causa raíz:** `next/image` no tenía una prioridad explícita. El navegador podía esperar a la intersección lazy aunque la imagen acabara siendo el elemento de mayor contenido de la ejecución.
- **Corrección:** se añadió `loading="eager"` y `fetchPriority="high"`, manteniendo `sizes` para no descargar una imagen mayor que el viewport.

### 2. JavaScript de módulos secundarios en el primer paquete del backoffice

- **Dónde:** `uis/backoffice/app/page.tsx` cargaba de forma inmediata `SupplierDirectory` e `IncidentAnalysis`, aunque aparecen después del dashboard principal.
- **Evidencia:** el dashboard móvil mostró TBT/TTI más sensibles que `/login`, además de diagnósticos de JavaScript no usado. El dashboard renderiza tabla, análisis CSV, proveedores y llamadas a API en una sola entrada.
- **Causa raíz:** las dos secciones inferiores formaban parte del grafo inicial de la ruta protegida; no había una frontera de carga entre el contenido prioritario y los paneles secundarios.
- **Corrección:** se usa `next/dynamic` para diferir esos dos módulos, con estados de carga visibles. `BackofficeDashboard` y el flujo de autenticación permanecen en la carga inicial.

### 3. Error de estado síncrono durante el efecto de inventario

- **Dónde:** `uis/backoffice/components/inventory-outbound-form.tsx`.
- **Evidencia:** ESLint `react-hooks/set-state-in-effect` detectó resets síncronos de `currentStock` y `stockError`.
- **Causa raíz:** el efecto que sincroniza el stock remoto también mutaba estado inmediatamente al cambiar el ingrediente, provocando renders en cascada y mezclando el ciclo de limpieza con la petición.
- **Corrección:** ambos resets se difieren a un microtask y se conservó la bandera de cancelación. Esto reduce trabajo redundante sin cambiar la lógica de negocio.

## Análisis de refactorización

### Caso A: tarjeta estadística duplicada

`BackofficeDashboard` tenía `StatCard` y `IncidentAnalysis` tenía `Stat`, con el mismo patrón visual: contenedor, valor destacado y etiqueta. Se extrajo `uis/backoffice/components/stat-card.tsx`, que ahora se usa en ambas vistas. La prop `compact` conserva el tamaño visual específico del análisis CSV sin duplicar markup.

### Caso B: estados de error de formularios repetidos

`login-form.tsx`, `register-form.tsx`, `forgot-password-form.tsx`, `reset-password-form.tsx`, `profile-form.tsx`, `incident-form.tsx` e `inventory-inbound-form.tsx` repiten el bloque visual `role="alert"` con fondo rojo, padding y tipografía en negrita. Es un candidato claro para un `FormAlert` compartido, pero no se extrajo en esta iteración porque no era necesario para los KPI y habría ampliado el alcance de la auditoría. El patrón queda documentado para el siguiente cambio aislado.

## Limitaciones

Lighthouse es una medición de laboratorio. LCP, TBT y Performance pueden variar entre ejecuciones. No se interpretó una subida o bajada de pocos puntos como causal sin una auditoría concreta. No se modificó la arquitectura ni se tocó `src/`.
