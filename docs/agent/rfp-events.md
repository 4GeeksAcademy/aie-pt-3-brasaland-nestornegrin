# Notificaciones en tiempo real de RFPs (SSE) — Hito 10 · Parte 1

Canal **Server-Sent Events** `GET /rfp/events` que avisa al dashboard (`/rfp`) cuando se registra un ticket nuevo. Es una capa de
comunicación: **no llama a ningún modelo ni agente**.

## Cuándo se dispara
Según el BRIEFING, cuando el documento **ya fue clasificado como RFP válida** y el flujo lo está procesando (`status = analizando`). En el
pipeline eso es justo después de guardar los metadatos (`extract_metadata`): un documento descartado **nunca** genera aviso, y cada ticket
se anuncia una sola vez (`announced_at`, UPDATE condicional atómico), aunque se reprocese.

## Contrato

Requiere el mismo JWT que el resto de la API del backoffice (`Authorization: Bearer <token>`).

```
retry: 3000
id: 1795012345678901
event: rfp_ticket_created
data: {"ticket_id":17,"rfp_id":"RFP-2026-017","client_name":"Andes Tech Solutions","location":"Medellín","service_type":"recurring_catering","status":"analizando","created_at":"2026-11-17T10:00:00+00:00"}

: keep-alive
```

- Cabeceras: `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`, `Connection: keep-alive`, `X-Accel-Buffering: no`.
- Payload plano con los campos del BRIEFING §3 y los mismos nombres que usa el sistema. El BRIEFING sugiere `status: "analyzing"`, pero el sistema
  de RFPs ya usa `analizando` y el BRIEFING §5 exige no inventar nombres nuevos para las mismas entidades; `ticket_id` sigue siendo entero.
- `id` = instante del aviso (`announced_at`, µs desde 1970): monótono y persistido. **No** es el `ticket_id`: los tickets se clasifican en
  distinto orden al de subida y un ticket antiguo puede anunciarse después de uno más nuevo.
- Un frame de comentario `: keep-alive` cada 15 s (`RFP_SSE_KEEPALIVE_SECONDS`).

## Recuperación tras un corte

1. **Servidor:** al reconectar con `Last-Event-ID: N` reenvía los tickets anunciados después de N (máx. `RFP_SSE_REPLAY_LIMIT`, 500)
   leyendo la base de datos y sigue en vivo. Se suscribe **antes** de leer la base para no perder un aviso en medio; el posible duplicado se
   descarta por `id`.
2. **Cliente:** cada vez que el stream pasa a «live» (primera conexión y cada reconexión) recarga la lista una vez, lo que cierra el hueco
   entre «lista cargada» y «stream abierto». Nunca se recarga por evento.
3. **Duplicados:** `mergeCreatedTicket` deduplica por `ticket_id`; si ya existe devuelve la misma lista y no pisa la fila real.

## Cliente (`uis/backoffice/lib/sse.ts`)

`fetch` + `ReadableStream` (no `EventSource`, que no permite la cabecera `Authorization`). Backoff exponencial 1 s → 30 s con jitter,
se reinicia tras una conexión que entrega datos; respeta `retry:`; sin bytes en 45 s se da por muerta; 401/403/404 no se reintentan;
vuelve a conectar al instante con el evento `online` del navegador. Reenvía como `Last-Event-ID` el `id` del último aviso recibido.

## Cómo probarlo

```bash
# 1) Terminal A: escuchar el canal (usa un JWT válido del backoffice)
curl -N -H "Authorization: Bearer $TOKEN" http://localhost:8000/rfp/events
# 2) Terminal B (o la UI): subir un PDF -> aparece `event: rfp_ticket_created` en A
# 3) Recuperación: usa el `id:` de un aviso anterior como Last-Event-ID y recibirás los posteriores
curl -N -H "Authorization: Bearer $TOKEN" -H "Last-Event-ID: <id anterior>" http://localhost:8000/rfp/events
# 4) Un PDF que NO es RFP (se descarta) no emite nada
# 5) Sin JWT -> 401
```

Verificación manual en la UI: abrir `/rfp`, DevTools → Network → «Offline» unos segundos (el indicador pasa a «Reconectando…» y los
intentos se espacian), subir un PDF desde otra pestaña/sesión durante el corte, volver a «Online»: el ticket aparece una sola vez.

Tests: `services/api/tests/test_rfp_events.py` (backend), `uis/backoffice/__tests__/sse.test.ts` (parser, backoff, reconexión + recuperación + dedupe).

## Límites conocidos

El broker vive en el proceso: con varios workers de uvicorn hace falta un bus compartido (Redis pub/sub o `LISTEN/NOTIFY` de PostgreSQL);
la recuperación por `Last-Event-ID` cubre mientras tanto lo publicado por otro worker.
