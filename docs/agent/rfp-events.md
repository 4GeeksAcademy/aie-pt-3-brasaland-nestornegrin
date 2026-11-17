# Notificaciones en tiempo real de RFPs (SSE) — Hito 10 · Parte 1

Canal **Server-Sent Events** `GET /rfp/events` que avisa al dashboard (`/rfp`) cuando se registra un ticket nuevo. Es una capa de
comunicación: **no llama a ningún modelo ni agente**.

## Contrato

Requiere el mismo JWT que el resto de la API del backoffice (`Authorization: Bearer <token>`).

```
retry: 3000
id: 17
event: rfp_ticket_created
data: {"ticket_id":17,"rfp_id":"RFP-00017","status":"analizando","requires_processing":true,"original_filename":"rfp.pdf","created_at":"2026-11-17T10:00:00+00:00"}

: keep-alive
```

- Cabeceras: `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, `Connection: keep-alive`, `X-Accel-Buffering: no`.
- Campos del ticket según BRIEFING §2.3 (`ticket_id`, `rfp_id`, `status`, `created_at`); estado inicial `analizando`. El BRIEFING no define
  nombres de evento SSE: `rfp_ticket_created` es decisión de esta parte. Si `rfp_id` aún no existe se usa `RFP-{ticket_id:05d}`.
- `id` = `ticket_id` (monótono, ya persistido): sirve de `Last-Event-ID`.
- Un frame de comentario `: keep-alive` cada 15 s (`RFP_SSE_KEEPALIVE_SECONDS`).

## Recuperación tras un corte

Al reconectar con `Last-Event-ID: N` el servidor reenvía los tickets con `ticket_id > N` (máx. `RFP_SSE_REPLAY_LIMIT`, 500) leyendo la base
de datos y sigue en vivo. Se suscribe **antes** de leer la base para no perder un ticket creado en medio; el duplicado posible se descarta
por `id`. El cliente deduplica además por `ticket_id` (`mergeCreatedTicket`).

## Cliente (`uis/backoffice/lib/sse.ts`)

`fetch` + `ReadableStream` (no `EventSource`, que no permite la cabecera `Authorization`). Backoff exponencial 1 s → 30 s con jitter,
se reinicia tras una conexión que entrega datos; respeta `retry:`; sin bytes en 45 s se da por muerta; 401/403/404 no se reintentan;
vuelve a conectar al instante con el evento `online` del navegador. Al montar `/rfp` primero se carga la lista y luego se abre el stream
con `Last-Event-ID` = mayor `ticket_id` conocido.

## Cómo probarlo

```bash
# 1) Terminal A: escuchar el canal (usa un JWT válido del backoffice)
curl -N -H "Authorization: Bearer $TOKEN" http://localhost:8000/rfp/events
# 2) Terminal B (o la UI): subir un PDF -> aparece `event: rfp_ticket_created` en A
# 3) Recuperación: curl -N -H "Authorization: Bearer $TOKEN" -H "Last-Event-ID: 3" http://localhost:8000/rfp/events
# 4) Sin JWT -> 401
```

Verificación manual en la UI: abrir `/rfp`, DevTools → Network → «Offline» unos segundos (el indicador pasa a «Reconectando…» y los
intentos se espacian), subir un PDF desde otra pestaña/sesión durante el corte, volver a «Online»: el ticket aparece una sola vez.

Tests: `services/api/tests/test_rfp_events.py` (backend), `uis/backoffice/__tests__/sse.test.ts` (parser, backoff, reconexión + recuperación + dedupe).

## Límites conocidos

El broker vive en el proceso: con varios workers de uvicorn hace falta un bus compartido (Redis pub/sub o `LISTEN/NOTIFY` de PostgreSQL);
la recuperación por `Last-Event-ID` cubre mientras tanto lo publicado por otro worker.
