# Carpeta `data/raw`

Esta carpeta está pensada para almacenar **datos en bruto** (raw) relacionados con la compañía: dumps, exports, archivos de ejemplo, muestras de eventos, o datasets sin transformar.

- **Propósito principal**: servir como zona de aterrizaje o referencia de datos originales antes de ser procesados por pipelines.
- **Recomendación**: documenta el origen de cada dataset, formato, tamaño esperado, consideraciones de privacidad/PII y cómo se versiona (idealmente evitando subir datos sensibles al repositorio).

## `incidents-COMPANY.csv`

Muestra sintética y anonimizada de 100 incidencias postventa para validar el
pipeline de análisis. No contiene datos reales de clientes. Incluye 90 filas
válidas y 10 inválidas, con errores de campos obligatorios, categoría, estado,
fecha y satisfacción. Las expectativas son: 90 válidos, 10 inválidos, 30
incidencias por categoría, 60 `Abierto`, 30 `Cerrado`, 0 `Descartado` y una
satisfacción media cerrada de 3.00.
