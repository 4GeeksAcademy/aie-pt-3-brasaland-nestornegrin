# Informe de mejoras de rendimiento

Fecha: 2026-09-28

## Cambios aplicados

1. **Imagen LCP priorizada en website.** En `uis/website/components/our-story-section.tsx` se añadieron `loading="eager"` y `fetchPriority="high"`, conservando `sizes`. La corrección ataca la carga lazy detectada por Lighthouse, no solo la puntuación.
2. **Carga diferida del backoffice.** `SupplierDirectory` e `IncidentAnalysis` se cargan con `next/dynamic` desde `uis/backoffice/app/page.tsx`, porque están debajo del dashboard principal. Se añadieron estados de carga explícitos.
3. **Refactorización compartida.** `uis/backoffice/components/stat-card.tsx` reemplaza dos implementaciones equivalentes y se integra en dashboard y análisis CSV.
4. **Corrección de efecto React.** Se eliminaron dos actualizaciones síncronas de estado en `inventory-outbound-form.tsx`; el reset del stock y del error ocurre en un microtask con cancelación segura.
5. **Accesibilidad del formulario de proveedores (seguimiento, 2026-10-21).** Los dos `<select>` de «Añadir proveedor» (categoría y país) en `uis/backoffice/components/supplier-directory.tsx` no tenían nombre accesible y hacían fallar `select-name`. Se añadió un `aria-label` a cada uno (`Categoría del nuevo proveedor` y `País del nuevo proveedor`), sin cambiar la estructura ni el aspecto.

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
| Backoffice | `/` autenticado | Escritorio | 100 / 100 / 96 / 100 | 100 / 100 / 100 / 100 | +4 Best Practices (desaparece el fallo de consola/CORS al medir con `localhost`); Accessibility se mantiene en 100 una vez etiquetados los dos `<select>` del formulario de proveedores. |
| Backoffice | `/` autenticado | Móvil | 94 / 100 / 96 / 100 | 95 / 100 / 100 / 100 | +4 Best Practices; Accessibility en 100 tras etiquetar los `<select>`. Performance 94 → 95 está dentro de la variabilidad entre ejecuciones y no se declara mejorada. |

La mejora más clara fue la de la web móvil: priorizar el recurso que Lighthouse identificó como LCP movió Performance de 92 a 94 en home y de 99 a 100 en Brasa Points. En backoffice, la mejora de Best Practices procede de ejecutar la vista autenticada con el origen local permitido por la API y de eliminar el entorno que producía errores de consola; la carga diferida prepara una frontera correcta para JavaScript secundario, pero una sola corrida de laboratorio no demuestra una mejora de Performance.

## Limitaciones y regresiones observadas

Datos de los mismos JSON de `audit/before/` y `audit/after/` (una sola ejecución por vista y estado, así que son indicativos, no concluyentes). Formato: antes → después.

| Vista | Modo | Performance | LCP | TBT | Accessibility | Best Practices |
| --- | --- | --- | --- | --- | --- | --- |
| Website `/` | Móvil | 92 → 94 | 1.27 s → 2.63 s | 339 → 182 ms | 100 → 100 | 100 → 100 |
| Website `/brasa-points` | Móvil | 99 → 100 | 0.80 s → 1.12 s | 115 → 54 ms | 100 → 100 | 100 → 100 |
| Backoffice `/` autenticado | Escritorio | 100 → 100 | 0.60 s → 0.42 s | 0 → 0 ms | 100 → 100 | 96 → 100 |
| Backoffice `/` autenticado | Móvil | 94 → 95 | 2.85 s → 1.42 s | 133 → 259 ms | 100 → 100 | 96 → 100 |

- **Accessibility del dashboard del backoffice: fallo `select-name` detectado y corregido (2026-10-21).** La primera medición «después» dio 96 en escritorio y móvil porque Lighthouse marcó `select-name` (*Select elements do not have associated label elements*) en los **dos** `<select>` del formulario de `section#suppliers` (`SupplierDirectory`, líneas 131 y 132; una versión anterior de este informe hablaba de uno solo). Era un fallo real de etiquetado, no ruido de medición. Se corrigió con un `aria-label` en cada `<select>` y se volvió a medir con build + start de producción y la misma configuración (Lighthouse 12.8.2, mismos emuladores): Accessibility 100 en ambos modos y `select-name` pasa. Como control, se repitió la medición con la versión anterior del componente en el mismo montaje y se reprodujo el fallo (Accessibility 96, `select-name` en los dos selects en escritorio y móvil), de modo que la mejora se debe al cambio y no a la variación entre ejecuciones.
- **La línea base no podía detectar este fallo.** En la medición «antes» del dashboard `select-name` figura como *no aplicable* y el DOM tenía 29 nodos (frente a 326 en la medición actual): el directorio de proveedores no llegó a renderizarse en aquella ejecución (la misma que registraba el error de consola/CORS). El 100 de Accessibility de la línea base no comprobaba ese formulario; el defecto ya existía antes de los cambios de rendimiento y no es una regresión causada por ellos.
- **TBT móvil del dashboard: 133 → 259 ms.** En esta medición el TBT móvil del dashboard es mayor que en la línea base, aunque Performance sube de 94 a 95 y el LCP baja de 2.85 s a 1.42 s. Con una sola ejecución por vista no se atribuye ni a los cambios ni al ruido; para concluir hay que repetir y comparar medianas.
- **La mejora de Performance en la home móvil viene del TBT, no del LCP.** Performance sube de 92 a 94 porque el TBT baja de 339 a 182 ms. El LCP, en cambio, pasa de 1.27 s a 2.63 s en esta medición, por encima del umbral de 2.5 s, aunque el diagnóstico `lcp-lazy-loaded` desaparece. No se declara la corrección del LCP como una mejora medida.
- **Hay variabilidad entre ejecuciones.** Los HTML originales, procedentes de una segunda ejecución sobre la misma versión, dieron otras cifras: por ejemplo, home móvil antes 100 (frente a 92) y después 98 (frente a 94). Con esa dispersión, diferencias de 1 o 2 puntos de Performance no son una prueba de mejora. Para confirmarlo hay que repetir cada medición varias veces y comparar medianas.
- **Best Practices en el backoffice** sube de 96 a 100 por el cambio de entorno de medición (origen `localhost` permitido por la API), no por un cambio de código, como ya se indica arriba.

## Validación

- `npm --prefix uis/website run lint`: 0 errores; queda un warning preexistente por una directiva ESLint innecesaria en `app/layout.tsx`.
- `npm --prefix uis/website run build`: correcto.
- `npm --prefix uis/backoffice run lint`: correcto.
- `npm --prefix uis/backoffice run build`: correcto.
- Tras el cambio de los `<select>`: `jest` del backoffice (9 tests) en verde, `tsc --noEmit` sin errores y `npm --prefix uis/backoffice run lint` sin avisos; `npm --prefix uis/backoffice run build` correcto (es el build usado en la nueva medición).
- La evidencia visual antes/después incluye home, Brasa Points, login y dashboard autenticado en escritorio y móvil.
- Los informes HTML y JSON permanecen junto a sus capturas en `audit/before/` y `audit/after/` (`<vista>-lighthouse.png` es la captura del informe; ver la nota de método de `AUDIT.md`).

## Skills externas

No se instalaron skills externas de `skills.sh`: el entorno no tenía un runner de skills configurado y las correcciones aplicadas se guiaron directamente por las auditorías Lighthouse reproducibles y las reglas de Next.js/React ya presentes en el repositorio. No se presenta una ejecución de agente externo que no haya ocurrido.
