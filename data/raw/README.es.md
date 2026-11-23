# Carpeta `data/raw`

Esta carpeta está pensada para almacenar **datos en bruto** (raw) relacionados con la compañía: dumps, exports, archivos de ejemplo, muestras de eventos, o datasets sin transformar.

- **Propósito principal**: servir como zona de aterrizaje o referencia de datos originales antes de ser procesados por pipelines.
- **Recomendación**: documenta el origen de cada dataset, formato, tamaño esperado, consideraciones de privacidad/PII y cómo se versiona (idealmente evitando subir datos sensibles al repositorio).

## `brasaland_sales.csv`

Dataset **provisto por el curso** (no se genera ni se modifica) con las ventas mensuales consolidadas de las 14
ubicaciones: 120 filas, de 2016-01 a 2025-12, fila `market = consolidated`. Columnas: `month` (`YYYY-MM-01`),
`revenue_usd`, `covers_served`, `avg_ticket_usd` y `market`. Lo usa el modelo de predicción de ventas
(`scripts/sales_forecast/`), que valida sus reglas al cargarlo y registra su huella SHA-256 en
`data/eval/sales_forecast/metrics.json`. Sin datos personales.

## `incidents-COMPANY.csv`

Muestra sintética y anonimizada de 100 incidencias postventa para validar el
pipeline de análisis. No contiene datos reales de clientes. Incluye 90 filas
válidas y 10 inválidas, con errores de campos obligatorios, categoría, estado,
fecha y satisfacción. Las expectativas son: 90 válidos, 10 inválidos, 30
incidencias por categoría, 60 `Abierto`, 30 `Cerrado`, 0 `Descartado` y una
satisfacción media cerrada de 3.00.
