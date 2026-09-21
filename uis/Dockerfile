# Imagen oficial de Node (Alpine) para las dos interfaces de /uis:
# el sitio público (website) y el panel interno (backoffice).
# El backend de FastAPI vive en un contenedor aparte (ver /services/Dockerfile).
FROM node:22-alpine

WORKDIR /app

# Se instalan las dependencias de cada app POR SEPARADO (cada una tiene su
# propio package.json/package-lock.json e histórico independiente — no es
# un monorepo con npm workspaces). Copiar solo los manifiestos primero
# aprovecha la caché de capas de Docker: si el código cambia pero no las
# dependencias, este paso no se repite.
COPY website/package.json website/package-lock.json ./website/
RUN cd website && npm ci

COPY backoffice/package.json backoffice/package-lock.json ./backoffice/
RUN cd backoffice && npm ci

# Copia el código como línea base -- en desarrollo, docker-compose.yml
# superpone esto con un bind mount para recarga en caliente; esta copia
# solo garantiza que la imagen funcione igual si se construye sin montajes.
COPY website ./website
COPY backoffice ./backoffice

COPY start.sh /start.sh
RUN chmod +x /start.sh

# website en 3000, backoffice en 3001 (ver start.sh)
EXPOSE 3000 3001

CMD ["/start.sh"]
