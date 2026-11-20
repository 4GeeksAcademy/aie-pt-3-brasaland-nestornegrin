#!/usr/bin/env bash
# Endurecimiento básico de un servidor Ubuntu/Debian para Brasaland (auditoría OWASP A05).
#
#   sudo ./harden-server.sh --pubkey-file ~/.ssh/id_ed25519.pub            # aplica
#   DRY_RUN=1 ROOT=/tmp/x ./harden-server.sh --pubkey-file k.pub          # solo escribe la configuración bajo $ROOT e imprime los comandos
#
# Qué hace (idempotente):
#   1. Crea un usuario de operación SIN root (`brasaland` por defecto) y le instala tu clave pública.
#   2. SSH: sin login directo como root, sin contraseñas (solo clave), sin reenvío X11, pocos intentos. Valida con `sshd -t` antes de recargar.
#   3. Carpetas con permisos explícitos: código / configuración sensible / logs / datos separados.
#   4. Firewall (ufw): todo el tráfico entrante denegado salvo SSH, HTTP (redirige) y HTTPS. Base de datos, Redis y el puerto del
#      servidor MCP/API NO se abren: los procesos escuchan en 127.0.0.1 y se publican solo a través del proxy HTTPS.
# NO bloquea tu acceso: exige la clave pública ANTES de desactivar contraseñas y abre SSH en ufw ANTES de activarlo.
set -euo pipefail

APP_USER="brasaland"
SSH_PORT="22"
PUBKEY_FILE=""
ROOT="${ROOT:-}"            # prefijo del sistema de ficheros (vacío en un servidor real; un directorio temporal en las pruebas)
DRY_RUN="${DRY_RUN:-0}"
APP_DIR="/opt/brasaland"

usage() { echo "Uso: $0 --pubkey-file <ruta.pub> [--user brasaland] [--ssh-port 22]"; exit 2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --pubkey-file) PUBKEY_FILE="${2:-}"; shift 2 ;;
    --user) APP_USER="${2:-}"; shift 2 ;;
    --ssh-port) SSH_PORT="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$PUBKEY_FILE" ] && [ -f "$PUBKEY_FILE" ] || { echo "ERROR: hace falta --pubkey-file con tu clave pública (si no, te quedarías sin acceso)." >&2; exit 1; }
grep -Eq '^(ssh-(ed25519|rsa)|ecdsa-sha2-[a-z0-9]+) ' "$PUBKEY_FILE" || { echo "ERROR: $PUBKEY_FILE no parece una clave pública SSH." >&2; exit 1; }
[[ "$APP_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || { echo "ERROR: nombre de usuario no válido." >&2; exit 1; }
[[ "$SSH_PORT" =~ ^[0-9]{1,5}$ ]] || { echo "ERROR: puerto SSH no válido." >&2; exit 1; }
if [ "$DRY_RUN" != "1" ] && [ "$(id -u)" -ne 0 ]; then echo "ERROR: ejecútalo con sudo/root (o usa DRY_RUN=1)." >&2; exit 1; fi

run() { if [ "$DRY_RUN" = "1" ]; then echo "[dry-run] $*"; else "$@"; fi; }

# --- 1. Usuario no-root --------------------------------------------------------------------------------------------------
if ! id "$APP_USER" >/dev/null 2>&1; then run adduser --disabled-password --gecos "" "$APP_USER"; fi
run install -d -m 700 -o "$APP_USER" -g "$APP_USER" "$ROOT/home/$APP_USER/.ssh"
run install -m 600 -o "$APP_USER" -g "$APP_USER" "$PUBKEY_FILE" "$ROOT/home/$APP_USER/.ssh/authorized_keys"

# --- 2. SSH --------------------------------------------------------------------------------------------------------------
SSHD_DROPIN="$ROOT/etc/ssh/sshd_config.d/99-brasaland-hardening.conf"
mkdir -p "$(dirname "$SSHD_DROPIN")"
cat > "$SSHD_DROPIN" <<CONF
# Gestionado por infra/hardening/harden-server.sh
Port $SSH_PORT
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
X11Forwarding no
MaxAuthTries 3
LoginGraceTime 30
AllowUsers $APP_USER
CONF
chmod 644 "$SSHD_DROPIN"
if [ "$DRY_RUN" != "1" ]; then
  sshd -t                       # si la configuración no es válida, el script se detiene antes de recargar nada
  systemctl reload ssh || systemctl reload sshd
else
  echo "[dry-run] sshd -t && systemctl reload ssh"
fi

# --- 3. Carpetas y permisos ----------------------------------------------------------------------------------------------
#   app/     código: lo escribe root (despliegue), el usuario de la app solo lo lee/ejecuta
#   config/  .env y secretos: root escribe, el grupo de la app lee; nadie más
#   logs/    la app escribe; el resto no lee
#   data/    datos de runtime de la app (bases locales, checkpoints); solo la app
run install -d -m 755 -o root -g "$APP_USER" "$ROOT$APP_DIR/app"
run install -d -m 750 -o root -g "$APP_USER" "$ROOT$APP_DIR/config"
run install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$ROOT$APP_DIR/logs"
run install -d -m 700 -o "$APP_USER" -g "$APP_USER" "$ROOT$APP_DIR/data"
if [ -f "$ROOT$APP_DIR/config/.env" ]; then run chmod 640 "$ROOT$APP_DIR/config/.env"; fi

# --- 4. Firewall ---------------------------------------------------------------------------------------------------------
run ufw --force reset
run ufw default deny incoming
run ufw default allow outgoing
run ufw allow "$SSH_PORT"/tcp comment 'SSH (operaciones)'      # ANTES de activar el firewall: evita quedarte fuera
run ufw allow 80/tcp comment 'HTTP (redirige a HTTPS)'
run ufw allow 443/tcp comment 'HTTPS (API + dashboard + SSE/WebSocket)'
run ufw --force enable

echo "Hecho. Comprueba con: sudo ./verify-hardening.sh --user $APP_USER --ssh-port $SSH_PORT"
echo "Abre una SEGUNDA sesión SSH como $APP_USER ANTES de cerrar la actual para confirmar que entras."
