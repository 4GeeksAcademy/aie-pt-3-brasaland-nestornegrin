# Rotación de secretos sin interrumpir el servicio

Ticket `security-hardening`. Aquí queda **qué secretos existen, quién los usa y cómo cambiarlos sin cortar sesiones ni peticiones**.

## 1 · Inventario

| Secreto | Dónde se usa | Soporta doble clave | Cómo se rota |
|---|---|---|---|
| `JWT_SECRET_KEY` | firma de los tokens de sesión (`app/auth/security.py`) | **Sí**: `JWT_SECRET_KEY_PREVIOUS` | §2 (ventana de transición, 0 cortes) |
| `RESEND_API_KEY` | envío del email de recuperación | Sí (en el proveedor: dos claves activas a la vez) | §3 |
| `DATABASE_URL` (contraseña de Supabase) | inventario / RFP / telemetría | Sí (rol nuevo o contraseña nueva + reinicio) | §3 |
| `AGENT_MCP_CLIENT_SECRET`, `MCP_BACKEND_PASSWORD` | agente ↔ servidor MCP | Sí (credencial nueva en el IdP y luego retirar la vieja) | §3 |
| Claves LLM / Qdrant | agente y RAG | Sí (dos claves activas en el proveedor) | §3 |

Todos se leen **solo del entorno**; no hay ninguno en el código ni en el historial (ver el informe, apartado "Secretos").

## 2 · Rotar `JWT_SECRET_KEY` sin cortes

La API **firma siempre con `JWT_SECRET_KEY`** y **verifica con `JWT_SECRET_KEY` y, si falla, con cada clave de `JWT_SECRET_KEY_PREVIOUS`** (lista separada por comas). Mientras las dos claves conviven, los tokens ya emitidos siguen valiendo y los nuevos salen con la clave nueva. Los tokens duran `ACCESS_TOKEN_EXPIRE_MINUTES` (30 por defecto), así que la transición termina sola.

1. **Generar** la clave nueva (≥ 32 caracteres aleatorios; la API se niega a arrancar en producción con una débil):
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
2. **Desplegar** con las dos claves (la vieja pasa a *previous*):
   ```
   JWT_SECRET_KEY=<clave nueva>
   JWT_SECRET_KEY_PREVIOUS=<clave vieja>
   ```
   Reinicio progresivo (rolling): durante el despliegue conviven réplicas con la config vieja y con la nueva. Las nuevas aceptan los tokens de las viejas (vía `PREVIOUS`); las viejas rechazarían por unos segundos los tokens firmados por las nuevas. Si la API corre en varias réplicas, hacer el paso 2 en **dos fases**: primero poner la clave nueva solo en `JWT_SECRET_KEY_PREVIOUS` de todas (aceptan ambas, siguen firmando con la vieja) y después intercambiar (nueva = vigente, vieja = previous). Con una sola réplica basta un único reinicio.
3. **Esperar** `ACCESS_TOKEN_EXPIRE_MINUTES` (30 min por defecto) más un margen: ya no queda ningún token firmado con la clave vieja.
4. **Retirar** `JWT_SECRET_KEY_PREVIOUS` y redesplegar. La clave vieja deja de valer (prueba `test_rotacion_los_tokens_de_la_clave_anterior_siguen_valiendo_durante_la_transicion`).

**Rotación de emergencia** (clave filtrada): saltarse la espera. Cambiar `JWT_SECRET_KEY`, **no** poner la comprometida en `PREVIOUS` y redesplegar: todas las sesiones se cierran (los usuarios vuelven a iniciar sesión) y un atacante con la clave vieja ya no puede forjar tokens.

> Además, desde este ticket cada token lleva una huella de la contraseña del usuario (`pwf`): cambiar o restablecer la contraseña **revoca** sus tokens sin tocar ningún secreto del servidor.

## 3 · Rotar credenciales de terceros (patrón "dos activas")

Aplica a Resend, Supabase, Auth0/IdP del MCP y claves LLM. Orden que evita cortes:

1. Crear la credencial **nueva** en el panel del proveedor **sin borrar la vieja**.
2. Actualizar la variable de entorno del despliegue y reiniciar (rolling).
3. Comprobar con una petición real (`/auth/forgot-password`, una consulta de inventario, `/agent/query`…) y revisar el log: sin `401/403` del proveedor.
4. **Revocar la credencial vieja** en el panel del proveedor.
5. Anotar la fecha de rotación y programar la siguiente (recomendado: 90 días, o de inmediato ante cualquier sospecha de fuga).

Pendiente manual (la API no puede hacerlo por ti): el secreto Auth0 `brasaland-playground` y la contraseña de Supabase que el informe NIST (B5) marcó como expuestos durante el desarrollo. El escaneo de este ticket **no encontró copias en el árbol ni en los 221 commits**, pero la rotación sigue siendo la única garantía de que el valor ya no sirve.

## 4 · Cómo comprobar que un secreto no se ha colado

```bash
# historial completo (todas las ramas) y árbol actual; el repo debe estar sin `--depth` (git fetch --unshallow)
git log --all -p -- . ':!*.lock' ':!*package-lock.json' \
  | grep -E '^\+.*(sk_live|sk-[A-Za-z0-9_-]{20,}|re_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|BEGIN [A-Z ]*PRIVATE KEY|postgres(ql)?://[^:/ ]+:[^@ ]{6,}@)'
git ls-files | grep -iE '(^|/)\.env($|\.local|\.prod)|\.pem$|\.key$'   # no debe imprimir nada
```
Salida real de la ejecución de este ticket: `docs/security/evidence/hardening-secretos.txt`.
