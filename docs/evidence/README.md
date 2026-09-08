# Evidencias de entrega

- `seed-output.txt`: salida real de dos ejecuciones de `uv run seed`.
- `swagger-filter-response.txt`: respuesta real de `GET /suppliers?category=Carnes`.

Las capturas visuales de Swagger UI y del backoffice requieren un navegador
con librerías gráficas. El contenedor de desarrollo no pudo iniciar Chromium
por la ausencia de `libatk-1.0.so.0`; las mismas comprobaciones HTTP y de build
sí fueron verificadas localmente.