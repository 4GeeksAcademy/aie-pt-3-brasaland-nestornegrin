#!/bin/sh
# Arranca las dos apps Next.js en modo desarrollo (recarga en caliente),
# cada una en su propio puerto, dentro del mismo contenedor.
set -e

(cd /app/website && npm run dev -- -p 3000 -H 0.0.0.0) &
website_pid=$!

(cd /app/backoffice && npm run dev -- -p 3001 -H 0.0.0.0) &
backoffice_pid=$!

# Si cualquiera de las dos muere, el contenedor entero se detiene (para que
# Docker lo reinicie) en vez de quedarse a medias con solo una app viva.
# No se usa "wait -n" (extensión de bash): el /bin/sh de Alpine es BusyBox
# ash, que no lo soporta -- por eso se sondea con un bucle en su lugar.
while kill -0 "$website_pid" 2>/dev/null && kill -0 "$backoffice_pid" 2>/dev/null; do
    sleep 1
done
exit 1
