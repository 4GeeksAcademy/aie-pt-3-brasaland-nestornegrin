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

## Limitaciones y regresiones observadas

Datos de los mismos JSON de `audit/before/` y `audit/after/` (una sola ejecución por vista y estado, así que son indicativos, no concluyentes). Formato: antes → después.

| Vista | Modo | Performance | LCP | TBT | Accessibility | Best Practices |
| --- | --- | --- | --- | --- | --- | --- |
| Website `/` | Móvil | 92 → 94 | 1.27 s → 2.63 s | 339 → 182 ms | 100 → 100 | 100 → 100 |
| Website `/brasa-points` | Móvil | 99 → 100 | 0.80 s → 1.12 s | 115 → 54 ms | 100 → 100 | 100 → 100 |
| Backoffice `/` autenticado | Escritorio | 100 → 100 | 0.60 s → 0.65 s | 0 → 0 ms | **100 → 96** | 96 → 100 |
| Backoffice `/` autenticado | Móvil | 94 → 93 | 2.85 s → 3.11 s | 133 → 104 ms | **100 → 96** | 96 → 100 |

- **Accessibility baja de 100 a 96 en el dashboard del backoffice.** El informe «después» marca `select-name` (*Select elements do not have associated label elements*) en un `<select>` del formulario de `section#suppliers` (`SupplierDirectory`). Es un fallo real de etiquetado del formulario, no ruido de medición. No se corrigió en esta iteración porque queda fuera de los cambios dirigidos de este informe; está pendiente y debe resolverse con un `aria-label` o `<label>` asociado, y volver a medir.
- **La mejora de Performance en la home móvil viene del TBT, no del LCP.** Performance sube de 92 a 94 porque el TBT baja de 339 a 182 ms. El LCP, en cambio, pasa de 1.27 s a 2.63 s en esta medición, por encima del umbral de 2.5 s, aunque el diagnóstico `lcp-lazy-loaded` desaparece. No se declara la corrección del LCP como una mejora medida.
- **Hay variabilidad entre ejecuciones.** Los HTML originales, procedentes de una segunda ejecución sobre la misma versión, dieron otras cifras: por ejemplo, home móvil antes 100 (frente a 92) y después 98 (frente a 94). Con esa dispersión, diferencias de 1 o 2 puntos de Performance no son una prueba de mejora. Para confirmarlo hay que repetir cada medición varias veces y comparar medianas.
- **Best Practices en el backoffice** sube de 96 a 100 por el cambio de entorno de medición (origen `localhost` permitido por la API), no por un cambio de código, como ya se indica arriba.

## Validación

- `npm --prefix uis/website run lint`: 0 errores; queda un warning preexistente por una directiva ESLint innecesaria en `app/layout.tsx`.
- `npm --prefix uis/website run build`: correcto.
- `npm --prefix uis/backoffice run lint`: correcto.
- `npm --prefix uis/backoffice run build`: correcto.
- La evidencia visual antes/después incluye home, Brasa Points, login y dashboard autenticado en escritorio y móvil.
- Los informes HTML y JSON permanecen junto a sus capturas en `audit/before/` y `audit/after/` (`<vista>-lighthouse.png` es la captura del informe; ver la nota de método de `AUDIT.md`).

## Skills externas

No se instalaron skills externas de `skills.sh`: el entorno no tenía un runner de skills configurado y las correcciones aplicadas se guiaron directamente por las auditorías Lighthouse reproducibles y las reglas de Next.js/React ya presentes en el repositorio. No se presenta una ejecución de agente externo que no haya ocurrido.
