#!/usr/bin/env bash
# Demuestra el endurecimiento APLICADO en un Ubuntu real (contenedor): antes -> aplicar harden-server.sh -> después,
# con pruebas reales por SSH y de firewall. Requiere docker y el cliente ssh (ya están en el Codespace).
#   bash infra/hardening/lab/run-lab.sh
# Genera docs/security/evidence/servidor-antes.txt y servidor-despues.txt (también se muestran por pantalla).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../../.." && pwd)"
OUT="$REPO/docs/security/evidence"; NAME=brasaland-lab; PORT=2200
KEYDIR="$(mktemp -d)"; trap 'docker rm -f $NAME >/dev/null 2>&1; rm -rf "$KEYDIR"' EXIT
SSH="ssh -i $KEYDIR/id -p $PORT -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o LogLevel=ERROR"
dx() { docker exec "$NAME" bash -c "$1"; }
reach() { timeout 3 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null && echo "ABIERTO" || echo "BLOQUEADO (sin respuesta)"; }

ssh-keygen -t ed25519 -N "" -f "$KEYDIR/id" -q && chmod 600 "$KEYDIR/id"
docker build -q -t brasaland-hardening-lab "$HERE" >/dev/null || { echo "ERROR: docker build falló"; exit 1; }
docker rm -f $NAME >/dev/null 2>&1
docker run -d --name $NAME --cap-add NET_ADMIN -p 127.0.0.1:$PORT:22 brasaland-hardening-lab >/dev/null || { echo "ERROR: docker run falló"; exit 1; }
sleep 2
IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $NAME)"
# Servicios de prueba que NUNCA deberían ser públicos (BD 5432, Redis 6379, MCP admin 8001) y uno legítimo (HTTPS 443)
dx 'for p in 5432 6379 8001 443; do setsid nc -lk $p >/dev/null 2>&1 & done; sleep 1'
# La clave del operador también se instala en root: así, si root no entra, es por PermitRootLogin y no por falta de clave
docker cp "$KEYDIR/id.pub" $NAME:/tmp/id.pub; dx 'cp /tmp/id.pub /root/.ssh/authorized_keys'
docker cp "$REPO/infra/hardening/harden-server.sh" $NAME:/tmp/; docker cp "$REPO/infra/hardening/verify-hardening.sh" $NAME:/tmp/
sleep 1

{
echo "=== ANTES (Ubuntu real sin endurecer) — $(date -u +%FT%TZ) ==="
dx 'grep PRETTY_NAME /etc/os-release; uname -sr'
echo "--- SSH efectivo ---"; dx "sshd -T | grep -Ei '^(permitrootlogin|passwordauthentication|allowusers)'"
echo "--- Login por SSH como root con clave ---"; $SSH root@127.0.0.1 'echo ENTRA: $(whoami)' 2>&1
echo "--- Alcanzabilidad desde fuera del servidor ($IP) ---"
for p in 22 443 5432 6379 8001; do echo "puerto $p: $(reach $IP $p)"; done
echo "--- verify-hardening.sh ---"; dx 'bash /tmp/verify-hardening.sh'; echo "exit=$?"
} 2>&1 | tee "$OUT/servidor-antes.txt"

echo; echo ">>> Aplicando harden-server.sh ..."
dx 'bash /tmp/harden-server.sh --pubkey-file /tmp/id.pub' 2>&1 | tee "$OUT/servidor-aplicar.txt"
sleep 2

{
echo "=== DESPUÉS (harden-server.sh aplicado) — $(date -u +%FT%TZ) ==="
echo "--- SSH efectivo ---"; dx "sshd -T | grep -Ei '^(permitrootlogin|passwordauthentication|allowusers)'"
echo "--- Login como root con clave (debe fallar) ---"; $SSH root@127.0.0.1 'echo ENTRA' 2>&1 || echo "-> denegado (exit=$?)"
echo "--- Login por contraseña como brasaland (debe fallar) ---"
ssh -p $PORT -o PreferredAuthentications=password -o PubkeyAuthentication=no -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 brasaland@127.0.0.1 true 2>&1 || echo "-> denegado (exit=$?)"
echo "--- Login con clave como brasaland (debe entrar) ---"
$SSH brasaland@127.0.0.1 'whoami; id; echo "sudo sin contraseña: $(sudo -n true 2>&1 | head -1)"; ls -ld /opt/brasaland/*; touch /opt/brasaland/app/x 2>&1 | head -1; touch /opt/brasaland/data/x && echo "data: escritura OK"; cat /opt/brasaland/config/.env 2>&1 | head -1' 2>&1
echo "--- ufw ---"; dx 'ufw status verbose'
echo "--- Alcanzabilidad desde fuera del servidor ($IP) ---"
for p in 22 443 5432 6379 8001; do echo "puerto $p: $(reach $IP $p)"; done
echo "--- Puertos en escucha dentro del servidor ---"; dx 'ss -tlnp'
echo "--- verify-hardening.sh ---"; dx 'bash /tmp/verify-hardening.sh'; echo "exit=$?"
} 2>&1 | tee "$OUT/servidor-despues.txt"
