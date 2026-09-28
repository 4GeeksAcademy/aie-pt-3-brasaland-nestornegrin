# Informe de mejoras de rendimiento

Fecha: 2026-09-28

## Cambios aplicados

1. **Imagen LCP priorizada en website.** En `uis/website/components/our-story-section.tsx` se añadieron `loading="eager"` y `fetchPriority="high"`, conservando `sizes`. La corrección ataca la carga lazy detectada por Lighthouse, no solo la puntuación.
2. **Carga diferida del backoffice.** `SupplierDirectory` e `IncidentAnalysis` se cargan con `next/dynamic` desde `uis/backoffice/app/page.tsx`, porque están debajo del dashboard principal. Se añadieron estados de carga explícitos.
3. **Refactorización compartida.** `uis/backoffice/components/stat-card.tsx` reemplaza dos implementaciones equivalentes y se integra en dashboard y análisis CSV.
4. **Corrección de efecto React.** Se eliminaron dos actualizaciones síncronas de estado en `inventory-outbound-form.tsx`; el reset del stock y del error ocurre en un microtask con cancelación segura.

## Comparativa Lighthouse

Formato: Performance / Accessibility / Best Practices / SEO.

| Frontend | Vista | Modo | Antes | Después | Impacto observable |
| --- | --- | --- | --- | --- | --- |
| Website | `/` | Escritorio | 100 / 100 / 100 / 100 | 100 / 100 / 100 / 100 | Se elimina `lcp-lazy-loaded`; LCP se mantuvo en 0.6 s. |
| Website | `/` | Móvil | 92 / 100 / 100 / 100 | 94 / 100 / 100 / 100 | +2 Performance; LCP de 1.3 s en la base. |
| Website | `/brasa-points` | Escritorio | 100 / 100 / 100 / 100 | 100 / 100 / 100 / 100 | LCP de 0.5 s a 0.3 s en la ejecución final. |
| Website | `/brasa-points` | Móvil | 99 / 100 / 100 / 100 | 100 / 100 / 100 / 100 | +1 Performance. |
| Backoffice | `/login` | Escritorio | 100 / 100 / 100 / 100 | 100 / 100 / 100 / 100 | La página ya estaba en el máximo. |
| Backoffice | `/login` | Móvil | 100 / 100 / 100 / 100 | 100 / 100 / 100 / 100 | Sin regresión. |
| Backoffice | `/` autenticado | Escritorio | 100 / 100 / 96 / 100 | 100 / 96 / 100 / 100 | +4 Best Practices; desaparece el fallo de consola/CORS al medir con `localhost`. |
| Backoffice | `/` autenticado | Móvil | 94 / 100 / 96 / 100 | 93 / 96 / 100 / 100 | +4 Best Practices; Performance es variable y no se declara mejorada. |

La mejora más clara fue la de la web móvil: priorizar el recurso que Lighthouse identificó como LCP movió Performance de 92 a 94 en home y de 99 a 100 en Brasa Points. En backoffice, la mejora de Best Practices procede de ejecutar la vista autenticada con el origen local permitido por la API y de eliminar el entorno que producía errores de consola; la carga diferida prepara una frontera correcta para JavaScript secundario, pero una sola corrida de laboratorio no demuestra una mejora de Performance.

## Validación

- `npm --prefix uis/website run lint`: 0 errores; queda un warning preexistente por una directiva ESLint innecesaria en `app/layout.tsx`.
- `npm --prefix uis/website run build`: correcto.
- `npm --prefix uis/backoffice run lint`: correcto.
- `npm --prefix uis/backoffice run build`: correcto.
- La evidencia visual antes/después incluye home, Brasa Points, login y dashboard autenticado en escritorio y móvil.
- Los informes HTML y JSON permanecen junto a sus capturas en `docs/evidence/lighthouse/before/` y `docs/evidence/lighthouse/after/`.

## Skills externas

No se instalaron skills externas de `skills.sh`: el entorno no tenía un runner de skills configurado y las correcciones aplicadas se guiaron directamente por las auditorías Lighthouse reproducibles y las reglas de Next.js/React ya presentes en el repositorio. No se presenta una ejecución de agente externo que no haya ocurrido.
