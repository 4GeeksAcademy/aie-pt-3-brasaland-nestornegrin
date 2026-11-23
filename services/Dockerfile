# Imagen oficial de Python para el backend de FastAPI (services/api).
FROM python:3.12-slim

# uv se copia directamente desde su propia imagen oficial -- es un binario
# estático, no hace falta compilar ni instalar Rust.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/services/api

COPY api/requirements.txt requirements.txt
RUN uv pip install --system -r requirements.txt

# Copia el código como línea base -- en desarrollo, docker-compose.yml
# superpone esto con bind mounts (services/api/, y también scripts/ y
# packages/ del monorepo) para recarga en caliente. app/main.py importa
# scripts.analyze y packages.shared.* como paquetes de nivel superior
# (no viven dentro de services/api/), por eso PYTHONPATH incluye /app
# además de /app/services/api -- ver docker-compose.yml para los montajes
# que colocan esos dos paquetes en /app/scripts y /app/packages.
COPY api api

ENV PYTHONPATH=/app:/app/services/api
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", \
     "--reload-dir", "/app/services/api", "--reload-dir", "/app/scripts", "--reload-dir", "/app/packages"]
