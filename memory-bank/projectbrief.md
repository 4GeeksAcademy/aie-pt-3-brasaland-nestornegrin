# Project Brief — Brasaland

**Fuente:** `CONTEXT.es.md` (briefing oficial del hito) y `company-choice.md` (justificación del escenario elegido por el estudiante). Última actualización: milestone 4.

## La empresa

**Brasaland** es una cadena de restaurantes de comida a la brasa fundada en 2008 en Medellín, Colombia. Empezó como un único local familiar y hoy opera **14 restaurantes propios** en dos países:

- **Colombia:** 10 locales en Medellín, Bogotá y Cali.
- **Estados Unidos (Florida):** 4 locales en Miami y Orlando.

Emplea ~115 personas (cocina, sala, operaciones, equipo corporativo en Medellín + oficina comercial en Miami). Facturación anual ~USD 6M. Tres pilares de marca: calidad consistente del producto, experiencia cálida y confiable, rapidez en el servicio.

## Estructura de negocio y stakeholders

- **Mariana Restrepo** — CEO, creó el equipo interno **Brasaland Digital** para liderar la transformación digital.
- **Nicolás Park** — CTO, a quien reporta el equipo técnico (nuestro "tech lead" en este monorepo).
- **Camila Ospina** — Gerente de Marketing, stakeholder directa de la web pública y del programa de fidelización.

## El problema que resuelve este proyecto (hasta ahora)

1. **Hito 1 (web pública):** el sitio corporativo era de 2019, no permitía pedidos en línea, solo mostraba el menú, y no reflejaba la operación en dos países. Se construyó una landing page (`index.html` + `application.html` + `validation.js`) con las secciones de marca, ubicaciones, y el formulario de registro al programa de fidelización **Brasa Points**.
2. **Hito 2 (lógica de negocio):** módulo TypeScript puro (`src/`) con los tipos de dominio (`RestaurantLocation`, `BrasaPointsRegistration`), utilidades de colecciones (filtrar, ordenar, agregar registros), búsqueda (lineal y binaria), y validaciones de negocio (nombre completo, email, teléfono con código de país, mayoría de edad, términos aceptados) — todo sin dependencias de DOM, pensado para reutilizarse en cualquier interfaz.
3. **Hito 3 (componentes generados con IA):** `uis/talent-pipeline-tracker`, una app Next.js ya generada (fuera del alcance de este milestone — no se modifica).

## Programa Brasa Points (el producto central de este hito)

- Programa de fidelización 100% digital, reemplaza tarjetas físicas.
- Acumulación: 1 punto por cada $10.000 COP o $5 USD.
- Registro captura: nombre, email, teléfono, país, ciudad, ubicación favorita, preferencias alimentarias, cómo conoció la marca, fecha de nacimiento (debe ser mayor de 18 años), aceptación de términos.
- **Restricción de negocio explícita:** Brasa Points es un programa de fidelización, **no** un sistema de pedidos en línea. El sitio debe dejarlo claro: "¿Quieres hacer un pedido? Llama a tu ubicación favorita o visítanos directamente."

## Este hito (Milestone 4): infraestructura del monorepo

El repo deja de ser "tres hitos sueltos" y pasa a ser el núcleo técnico de la empresa. Este milestone no agrega producto nuevo — construye el soporte para que cualquier agente de código (y cualquier persona del equipo) pueda seguir construyendo sobre Brasaland sin romper lo ya hecho:

- Banco de memoria (este archivo + `techContext.md` + `progress.md`) con contexto de negocio y técnico real, no genérico.
- `AGENTS.md` con el flujo de trabajo obligatorio para cualquier agente.
- `.agents/rules/` con convenciones específicas del proyecto.
- `.agents/skills/` con al menos una skill reutilizable para una tarea recurrente real.
- La web pública migrada a `uis/website` (Next.js), y `uis/backoffice` como el espacio interno donde vive la lógica de negocio del Hito 2, visible en pantalla.

## Idea de agente de IA para un hito futuro (de `company-choice.md`, para no perderla)

Sistema de pedidos inteligentes de ingredientes por local, apoyado en predicción de demanda e inventario: vigila stock por local vs. reposición necesaria, y propone el pedido ideal por día/semana. Necesitaría histórico de ventas por local/producto, inventario actual, catálogo de ingredientes, relación plato↔ingrediente, tiempo de entrega por proveedor, calendario operativo. Al detectar quiebre de stock: crea borrador de pedido + notifica al encargado + avisa a compras si el impacto es relevante. Al detectar exceso/riesgo de caducidad: sugiere reducir el próximo pedido o lanza alerta de consumo prioritario en cocina. Esto es una idea para un milestone futuro (agentes) — no se implementa en este hito, pero queda documentada aquí para que el agente que trabaje esa fase no empiece desde cero.
