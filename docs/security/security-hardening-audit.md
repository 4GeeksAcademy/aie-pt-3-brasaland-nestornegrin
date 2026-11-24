# Auditoría de seguridad como atacante externo · `security-hardening`

> CTO: «No voy a autorizar que expongamos más superficie pública hasta que sepamos qué vulnerabilidades tiene lo que ya construimos.»

**Alcance:** solo la aplicación propia (API `services/api`, backoffice `uis/backoffice`), en local y sobre `main`. Sin escaneos a terceros.
**Método:** (1) inventario de endpoints y flujos de riesgo, (2) ataque real contra la API arrancada (no revisión de memoria): primero se documenta el estado **antes**, (3) corrección, (4) la misma sonda **después**. Cada hallazgo tiene una prueba automatizada que falla sobre `main` y pasa con la corrección.
**Relación con auditorías previas:** `owasp-top10-audit.md` (H1–H13) y `nist-security-report.md` ya cerraron CORS, roles, límite de login, cabeceras, JWT débil, CSV… Este ticket **no los repite**: parte de que están corregidos y busca lo que sigue roto. Se verificó que siguen funcionando (p. ej. el registro rechaza `role` con 400, un usuario no lee ni edita a otro, nadie sube su rol).

## 1 · Inventario del riesgo

Del `openapi.json` real: 55 rutas. Las que importan para un atacante externo:

| Superficie | Rutas | Por qué es de riesgo |
|---|---|---|
| **Pública (sin sesión)** | `POST /users`, `POST /auth/login`, `/auth/forgot-password`, `/auth/reset-password`, `POST /telemetry/events` | Las alcanza cualquiera en Internet; reciben contraseñas, tokens y cuerpos arbitrarios |
| **Credenciales / sesión** | `/auth/change-password`, `PUT /users/{id}`, JWT | Quien controla esto controla la cuenta |
| **Escrituras críticas** | `/api/suppliers` y `/suppliers` (alta/baja/estado/valoración), `/inventory/products`, `DELETE /users/{id}` | Alteran datos del negocio; protegidas por rol pero sin freno de ritmo |
| **Coste** | `/agent/query`, `/knowledge/query`, chat WS | Cada llamada gasta tokens (ya limitadas en el hito anterior) |
| **Datos sensibles** | `GET /users`, `/telemetry/report`, `/api/incidents/results/export` | PII y datos internos (ya con control de acceso) |

## 2 · Hallazgos (todos reproducidos contra la API en marcha)

Evidencia: `evidence/hardening-antes.txt` (sondas contra `main`), `evidence/hardening-despues.txt` (mismas sondas con la corrección), `evidence/hardening-tests-antes.txt` / `-despues.txt` (pruebas automáticas), script `evidence/security_probe.py` (reproducible: `python docs/security/evidence/security_probe.py http://localhost:8000`).

| # | Hallazgo | OWASP | Severidad |
|---|---|---|---|
| V1 | Los tokens robados siguen válidos tras cambiar o restablecer la contraseña | A07 | Alta |
| V2 | Cambiar el email de la cuenta solo exige el token: toma de cuenta persistente | A07 / A01 | Alta |
| V3 | Contraseña sin longitud máxima: 500 sin autenticar y coste de CPU | A04 | Media |
| V4 | Cualquiera puede bloquear la cuenta de otra persona (DoS dirigido) | A07 / A04 | Media |
| V5 | Sin rate limiting en cambio/restablecimiento de contraseña, telemetría anónima y escrituras críticas | A04 / A07 | Media |
| V6 | Sin tope de tamaño de cuerpo: 20 MB leídos en memoria sin autenticar | A04 | Media |

### V1 · Tokens que sobreviven al cambio de contraseña
- **Por qué es un problema:** el JWT solo llevaba `sub` y `exp`. La reacción habitual ante una sesión robada («cambio la contraseña») no hacía nada: el atacante conservaba acceso hasta 30 minutos, y con V2 podía convertirlo en acceso permanente.
- **Reproducción (antes):**
  1. `POST /users` + `POST /auth/login` → `T`.
  2. `POST /auth/change-password` con `T` (contraseña cambiada).
  3. `GET /auth/me` con `T` → **200**.
- **Impacto:** una fuga de token (XSS, log, `localStorage` —H12—) no se corta ni cambiando la contraseña. Mismo efecto con `/auth/reset-password`.
- **Corrección:** el token incluye `iat` y una huella `pwf` del hash de contraseña vigente; `get_current_user` y el WebSocket del chat la comparan con la actual. Cambiar o restablecer la contraseña (hash nuevo) invalida **todos** los tokens anteriores sin guardar listas de revocación. `/auth/change-password` devuelve un token nuevo para no cerrar la sesión legítima (el backoffice lo guarda).
- **Después:** mismo paso 3 → **401**; el token nuevo → 200. Pruebas: `test_v1_*` (4: cambio, restablecimiento, token sin huella, WebSocket).

### V2 · Cambio de email sin reautenticar
- **Por qué es un problema:** `PUT /users/{id}` aceptaba `{"email": ...}` solo con el token. Cambiar el email redirige `/auth/forgot-password` al atacante: de «sesión prestada 30 min» a «cuenta suya para siempre».
- **Reproducción (antes):** con `T` de una cuenta normal: `PUT /users/4 {"email":"atacante@evil.example"}` → **200**; `POST /auth/login` con ese email y la contraseña original → **200**; el token viejo seguía valiendo.
- **Impacto:** toma de cuenta completa; el dueño legítimo pierde el acceso.
- **Corrección:** cambiar el **propio** email exige `current_password` (403 si falta o es errónea), con límite de 5 fallos / 15 min, y la contraseña de confirmación nunca se persiste. Un admin que corrige el email de otra persona no la necesita.
- **Después:** `PUT` sin contraseña → **403**; con la correcta → 200. Pruebas: `test_v2_*` (4).

### V3 · Contraseña sin tope de longitud
- **Por qué es un problema:** `password` no tenía `max_length`. passlib lanza `PasswordSizeError` ante entradas enormes y la API respondía **500** (y registra un traceback por petición), sin autenticar, en `POST /users` y `POST /auth/login`.
- **Reproducción (antes):** `POST /users` con `"password": "A1" + "a"*5_000_000` → **HTTP 500**; mismo en login.
- **Impacto:** error 500 provocable a voluntad (ruido en monitorización, trazas) y trabajo de hash/serialización de megabytes por petición anónima.
- **Corrección:** `MAX_PASSWORD_LENGTH = 128` en todos los modelos que reciben contraseñas; `verify_password` devuelve `False` (nunca lanza) ante longitudes o hashes absurdos.
- **Después:** contraseña de 100 000 caracteres → **400** (validación); de 5 MB → **413** (V6). Pruebas: `test_v3_*` (2).

### V4 · Bloqueo de la cuenta de otra persona
- **Por qué es un problema:** el límite de login (5 fallos / 15 min) se contaba **solo por cuenta**. Es el control correcto contra la fuerza bruta pero, solo por cuenta, es un arma: quien conozca el email de la víctima (público en una pyme) la deja fuera 15 minutos repitiendo 5 intentos, y vuelve a hacerlo cada 15.
- **Reproducción (antes):** desde `127.0.0.14`, 6 logins con contraseña errónea contra `victima@…`; después el dueño, desde `127.0.0.15` y con su contraseña **correcta** → **429**.
- **Impacto:** denegación de servicio dirigida contra cualquier usuario (incluido el admin).
- **Corrección:** el límite estricto (5) pasa a ser por pareja **cuenta + IP** (el atacante se bloquea a sí mismo); se mantiene el tope por IP (20) y se añade un tope global por cuenta más alto (50 / 15 min) que sigue frenando la fuerza bruta distribuida.
- **Después:** el dueño entra con **200**; el atacante sigue recibiendo 429; 50 fallos desde 50 IPs siguen agotando el tope global. Pruebas: `test_v4_*` (2).

### V5 · Endpoints sensibles sin rate limiting
- **Por qué es un problema:** solo login, forgot, registro y modelo tenían límite. Quedaban sin freno `change-password` (un token robado servía de oráculo de la contraseña actual), `reset-password` (canje de tokens al azar), `telemetry/events` (anónimo, escribe en base de datos) y todas las escrituras críticas.
- **Reproducción (antes):** 30 × `change-password` con contraseña errónea → 0 respuestas 429; 40 × `reset-password` con tokens al azar → 0 × 429; 300 × `telemetry/events` → 0 × 429.
- **Impacto:** adivinación sin límite de la contraseña con un token robado, inundación de la tabla de telemetría, y una sesión comprometida (o un script defectuoso) podía dar de alta/baja proveedores sin freno.
- **Corrección** (todas devuelven **429** con `Retry-After`; ventana deslizante, `app/security.py`):

  | Endpoint | Límite | Clave |
  |---|---|---|
  | `POST /auth/change-password` y cambio de email | 5 fallos / 15 min | usuario |
  | `POST /auth/reset-password` | 10 intentos / 15 min | IP |
  | `POST /telemetry/events` | 120 / min | IP |
  | Altas/bajas/cambios de proveedores, inventario, `PUT`/`DELETE /users/{id}` | 30 / min | usuario |
  | (ya existentes) login, forgot-password, registro, modelo | ver `app/security.py` | — |
- **Después:** 25/30, 30/40 y 180/300 respuestas 429 en las sondas en vivo. Pruebas que **disparan el límite**: `test_v5a/b/c/d` y `test_v5_los_limites_se_liberan_al_pasar_la_ventana`.
- **Limitación conocida:** el limitador es en memoria (un solo proceso). Con varias réplicas hay que moverlo a Redis (ya disponible en el stack); queda anotado como H13.

### V6 · Sin tope de tamaño de cuerpo
- **Por qué es un problema:** FastAPI/uvicorn no limitan el cuerpo. `telemetry/events` hacía `await request.body()` completo antes de validar.
- **Reproducción (antes):** `POST /telemetry/events` con 20 MB → la API lo lee entero y responde **400** («el cuerpo debe ser JSON»); no hay 413.
- **Impacto:** agotamiento de memoria con unas pocas peticiones anónimas concurrentes.
- **Corrección:** `BodySizeLimitMiddleware` (ASGI): 1 MiB por defecto (`MAX_BODY_BYTES`), 6 MiB para el CSV de análisis; se mira `Content-Length` y también se cuentan los bytes recibidos (cuerpos *chunked*), y se responde **413** sin leer el resto.
- **Después:** 20 MB → **413** en milisegundos. Pruebas: `test_v6_*` (3, incluida la de cuerpo troceado sin `Content-Length`).

## 3 · Rate limiting: verificación

Todos los límites anteriores están cubiertos por pruebas que **provocan el 429** (no solo comprueban que el código existe) y por la sonda en vivo (`hardening-despues.txt`). Además se comprueba que la ventana se libera y que un límite por IP no afecta a otra IP.

## 4 · Secretos

- **Árbol actual y historial completo** (221 commits, todas las ramas, sin clon superficial): patrones de claves (`sk-…`, `re_…`, `AKIA…`, `AIza…`, `ghp_…`, JWT, `postgres://usuario:clave@…`, claves privadas PEM) y ficheros (`.env`, `.pem`, `.key`, bases de datos). **Resultado: 0 credenciales reales**; solo el marcador de ejemplo `usuario:contraseña@host` de `.env.example`. Salida: `evidence/hardening-secretos.txt`.
- **Hallazgo honesto:** ningún secreto está en el repositorio, pero el informe NIST (B5) indica que el secreto Auth0 `brasaland-playground` y la contraseña de Supabase *se expusieron durante el desarrollo* (fuera de git). Un escaneo del repo no puede demostrar que ya no sirvan: **siguen pendientes de rotar a mano** (procedimiento en `secret-rotation.md` §3).
- **Mecanismo de rotación implementado:** `JWT_SECRET_KEY_PREVIOUS` (lista separada por comas). Se firma siempre con la vigente y se verifica con la vigente y, si falla, con las anteriores. Pruebas `test_rotacion_*` (3): un token de la clave anterior es rechazado sin configuración, aceptado durante la transición, y rechazado de nuevo al retirar la clave; un token **caducado** firmado con la clave anterior no se acepta.
- **Procedimiento sin cortes:** `docs/security/secret-rotation.md` (inventario de secretos, rotación del JWT en dos fases, rotación de emergencia, patrón «dos credenciales activas» para Resend/Supabase/IdP/LLM y comprobación posterior).

## 5 · OWASP Top 10 (2021) aplicado a esta aplicación

| Categoría | ¿Aplica? | Estado tras este ticket |
|---|---|---|
| **A01 Control de acceso roto** | Sí | Roles en proveedores/inventario, propiedad en `/users/{id}` y el agente exigen sesión (auditoría previa). **V2**: cambio de email sin reautenticar → corregido. |
| **A02 Fallas criptográficas** | Sí | bcrypt, JWT HS256 con secreto fuerte validado. **V1**: tokens no revocables → corregido (huella `pwf`); **rotación** de secretos → implementada y documentada. |
| **A03 Inyección** | Sí | TinyDB/SQLModel parametrizados, sin SQL en crudo; CSV con fórmulas neutralizado (previo). Sin hallazgos nuevos. |
| **A04 Diseño inseguro** | Sí | **V3, V5, V6** (sin tope de longitud, ritmo ni tamaño) → corregidos. |
| **A05 Configuración incorrecta** | Sí | CORS exacto, cabeceras, `/docs` apagado con `APP_ENV=production` (previos). `/docs` está abierto en desarrollo: esperado. |
| **A06 Componentes vulnerables** | Sí | `pip-audit`/`npm audit` del informe NIST sin críticos; sin cambios de dependencias en este ticket. |
| **A07 Fallos de identificación y autenticación** | Sí | **V1, V2, V4, V5** → corregidos. |
| **A08 Fallos de integridad de software y datos** | Parcial | Sin deserialización de datos no confiables ni auto-update; la integridad de la cola/auditoría se trata en sus tickets. |
| **A09 Fallos de registro y monitorización** | Sí | Los 429 y los fallos de login quedan en el log (huella de la clave, nunca el dato). |
| **A10 SSRF** | No | La API no hace peticiones a URLs que aporte el usuario (solo a proveedores con URL fija desde el entorno). |

## 6 · Riesgo residual (honesto)

- **H12**: el JWT vive en `localStorage` (si hubiera XSS se podría robar); mitigado con CSP, sin `dangerouslySetInnerHTML` y ahora con revocación (V1) y vida de 30 min.
- **H13 / V5**: limitadores en memoria → moverlos a Redis al escalar a varias réplicas.
- Rotar a mano Auth0 `brasaland-playground` y la contraseña de Supabase (§4).
- Los tokens emitidos **antes** de desplegar este cambio dejan de valer (no llevan `pwf`): los usuarios deberán iniciar sesión una vez.
