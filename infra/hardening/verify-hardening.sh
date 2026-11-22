#!/usr/bin/env bash
# Comprueba el endurecimiento (criterios de aceptación del ticket OWASP). Sale con código 1 si algo falla.
#   sudo ./verify-hardening.sh [--user brasaland] [--ssh-port 22]
set -uo pipefail
APP_USER="brasaland"; SSH_PORT="22"; APP_DIR="/opt/brasaland"
while [ $# -gt 0 ]; do case "$1" in --user) APP_USER="$2"; shift 2 ;; --ssh-port) SSH_PORT="$2"; shift 2 ;; *) echo "Uso: $0 [--user u] [--ssh-port p]"; exit 2 ;; esac; done
FAIL=0
SSHD_T="$(sshd -T 2>/dev/null)"   # se captura una vez: con `pipefail`, `sshd -T | grep -q` falla por SIGPIPE cuando grep sale antes de que sshd termine
check() { if eval "$2"; then echo "PASS  $1"; else echo "FAIL  $1"; FAIL=1; fi; }

check "SSH no permite login como root"            "grep -qi '^permitrootlogin no' <<<\"\$SSHD_T\""
check "SSH no admite contraseñas (solo clave)"      "grep -qi '^passwordauthentication no' <<<\"\$SSHD_T\""
check "Existe el usuario no-root $APP_USER"         "id -u $APP_USER >/dev/null 2>&1 && [ \"\$(id -u $APP_USER)\" -ne 0 ]"
check "$APP_DIR/config no es legible por 'otros'"   "[ \"\$(stat -c %a $APP_DIR/config)\" = 750 ]"
check "$APP_DIR/data solo accesible por la app"     "[ \"\$(stat -c %a $APP_DIR/data)\" = 700 ]"
check "$APP_DIR/app no es escribible por la app"    "id -u $APP_USER >/dev/null 2>&1 && [ -d $APP_DIR/app ] && ! sudo -u $APP_USER test -w $APP_DIR/app"
check "ufw activo con entrada denegada por defecto" "ufw status verbose 2>/dev/null | grep -q 'Status: active' && ufw status verbose | grep -qi 'Default: deny (incoming)'"
check "ufw solo abre SSH, 80 y 443"                 "[ \"\$(ufw status | grep -E '^[0-9]+' | grep -v '(v6)' | awk '{print \$1}' | sed 's#/tcp##' | sort -n | tr '\n' ' ')\" = \"$(printf '%s\n' 80 443 "$SSH_PORT" | sort -n | tr '\n' ' ')\" ]"
echo "--- Puertos en escucha (nada de BD/Redis/MCP en 0.0.0.0) ---"
ss -tlnH 2>/dev/null | awk '{print $4}'
exit $FAIL
