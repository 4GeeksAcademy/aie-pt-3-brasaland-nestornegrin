# TESTING.md — AUTH-088: cobertura de pruebas unitarias de la API de autenticación

Batería de pruebas para todos los endpoints de autenticación (`services/api/app/auth/`
más el registro en `app/users/routes.py`, que crea la cuenta) y para las
funciones de utilidad de auth del frontend (`uis/backoffice/lib/api-client.ts`).
Se prueba la lógica de negocio real — no la serialización HTTP ni los
internos del framework.

## Cómo ejecutar

### Backend (pytest)

Funciona igual **desde la raíz del monorepo** o desde dentro de `services/api`
— la cobertura ya viene siempre acotada a `app.auth` vía `addopts` en
`services/api/pyproject.toml`, así que no hace falta recordar ningún flag.

Desde la raíz del repo:

```bash
uv sync --project services/api          # instala pytest, pytest-cov (grupo dev incluido por defecto)
uv run --project services/api pytest services/api/tests -v
```

(Si en cambio corres `uv run --project services/api pytest` sin indicar
`services/api/tests`, pytest intenta descubrir tests desde tu directorio
actual y puede toparse con `scripts/test_analyze.py`, del Hito 5, que no es
parte de esta batería — por eso el path explícito.)

O, de forma equivalente, entrando primero al proyecto:

```bash
cd services/api
uv sync
uv run pytest              # corre toda la batería + cobertura de app.auth
```

Los tests son autocontenidos: `tests/conftest.py` fija las variables de
entorno necesarias (`JWT_SECRET_KEY`, etc.) antes de importar la app, y un
fixture `autouse` vacía las tablas de TinyDB antes de cada test, así que no
hace falta ningún `.env` para correrlos ni se tocan tus datos reales de
`users.json`/`profiles.json`/`password_resets.json`.


### Frontend (Jest)

```bash
cd uis/backoffice
npm install               # instala jest, jest-environment-jsdom, @types/jest
npm test                  # corre la batería
npm run test:coverage     # + reporte de cobertura de lib/api-client.ts
```

## Plan de pruebas — qué se cubre y por qué

Para cada endpoint: **camino feliz** (entrada válida, respuesta esperada),
**caso límite** (un valor en el borde del dominio: mayúsculas/minúsculas,
reintento, mismo estado) y **modo de fallo** (entrada inválida o dependencia
externa caída).

| Endpoint / función | Camino feliz | Caso límite | Modo de fallo |
|---|---|---|---|
| `POST /users` (registro) | Crea la cuenta, `201`, nunca devuelve la contraseña | Email duplicado con distinta capitalización → `409` | Contraseña de menos de 8 caracteres / email con formato inválido → `400` con el campo identificado |
| `POST /auth/login` | Credenciales correctas → `200` + `access_token` | Email en mayúsculas funciona igual (normalización a minúsculas); el campo `username` funciona como alias de `email` | Contraseña incorrecta y usuario inexistente devuelven el **mismo** mensaje de error (anti-enumeración) |
| `GET /auth/me` | Token válido → email, rol y perfil | Perfil creado en el registro aparece correctamente | Sin token, token manipulado, token expirado, y **usuario desactivado con un token todavía válido** → todos `401` |
| `POST /auth/forgot-password` | Email existente → `200`, se genera el token y se llama al envío de email | Email inexistente responde con el **mismo** cuerpo `200` (nunca revela si existe) | Si el proveedor de email (Resend) falla, el endpoint sigue devolviendo `200` — nunca un `500` que delate el fallo |
| `POST /auth/reset-password` | Token válido → cambia la contraseña; la vieja deja de funcionar y la nueva sí | — | Token inexistente, ya usado, o expirado → `400` en los tres casos |
| `POST /auth/change-password` | Contraseña actual correcta → la cambia | — | Contraseña actual incorrecta → `400`; contraseña nueva demasiado corta → `400`; sin token → `401` |
| `security.py` (funciones puras) | Hash/verificación de contraseña; ida y vuelta de un JWT | — | JWT manipulado, expirado, o con `sub` no numérico → error; el token de reseteo nunca se repite y su hash es determinista |
| `email.py` (funciones puras) | `build_reset_link` incluye el token y la URL correcta; el envío llama a Resend con los datos correctos | — | Sin `RESEND_API_KEY` configurada → error explícito (nunca un fallo silencioso) |
| `lib/api-client.ts` (frontend) | Guardar/leer el token; adjuntar `Authorization` cuando hay token | Sin token guardado no se adjunta el header; `readApiErrorDetails` interpreta el formato real de FastAPI (`detail`: lista de `{loc, msg}`) | Una respuesta `401` limpia el token y redirige a `/login`; un cuerpo de error que no es JSON cae al mensaje por defecto |

**Decisiones deliberadas:**
- No se prueba con mocks la llamada real a Resend (`resend.Emails.send`) más
  que a nivel de función (`test_email.py`) — en los tests de endpoint
  (`test_forgot_password.py`) se sustituye directamente
  `app.auth.routes.send_password_reset_email` para no depender de la red ni
  gastar envíos reales, igual que se hace en producción con datos sensibles.
- Los tests de `/users`, `/auth/*` no verifican el *shape* JSON completo de
  cada respuesta (eso ya lo garantiza `response_model` de FastAPI) — verifican
  el código de estado y los datos que importan para la lógica de negocio
  (p. ej. que la contraseña nunca se devuelve).

## Flujo asistido por IA

Antes de escribir cualquier prueba, se revisó el código real de
`auth/routes.py`, `users/routes.py`, `security.py` y `repository.py` (en vez
de asumir el comportamiento) para identificar casos no evidentes a simple
vista:

- `LoginRequest` acepta tanto `email` como `username` como campos alternativos
  para iniciar sesión (`login_email` usa `self.email or self.username`) —
  nadie lo documentó explícitamente en ningún ticket anterior, pero está
  implementado y es un caso de prueba real (`test_login_accepts_username_field_as_an_alias_for_email`).
- El registro normaliza el email a minúsculas antes de guardarlo
  (`users/routes.py`) y el login hace lo mismo antes de buscar
  (`LoginRequest.login_email`) — esto solo se confirmó leyendo ambos
  archivos a la vez; de haber lowercased solo uno de los dos lados, el login
  con distinta capitalización habría fallado silenciosamente. Se añadió
  `test_login_email_is_case_insensitive` para dejarlo verificado, no
  solo asumido.
- El fix del ticket anterior (auditoría de errores) que hace que
  `/auth/forgot-password` siga devolviendo `200` aunque Resend falle se
  "blindó" con una prueba dedicada
  (`test_forgot_password_still_returns_200_when_the_email_provider_fails`),
  para que una futura regresión en ese manejo de errores la detecte esta
  batería antes de llegar a producción — exactamente el escenario que dio
  origen al ticket AUTH-088 (una regresión sin pruebas que nadie detectó).

No se encontró ningún bug nuevo al escribir las pruebas — el código ya se
comportaba como debía en los tres puntos anteriores — pero los tres eran
comportamientos que fácilmente se podrían haber roto sin que ninguna prueba
lo notara.



- **Backend:** 42/42 pruebas pasando. Cobertura de `app/auth`: **93%** (routes.py,
  dependencies.py, email.py y models.py al 100%; security.py 97%;
  repository.py 79% — el resto corresponde a métodos de gestión de usuarios
  como `list`/`update`/`delete` que están fuera del alcance de este ticket,
  pertenecientes al backlog `API-042`).
- **Frontend:** 9/9 pruebas pasando. Cobertura de `lib/api-client.ts`: **88%**
  statements / **91%** líneas.

Ambos superan holgadamente el 70% mínimo pedido.
