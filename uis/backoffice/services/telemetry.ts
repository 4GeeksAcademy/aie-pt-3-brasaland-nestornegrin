/**
 * TelemetryService — único punto del frontend que habla con el endpoint de
 * telemetría. Diseño: docs/telemetry/telemetry-plan.md.
 *
 * - API pública: `track(eventType, properties)` (+ `startTelemetrySession`).
 * - Los llamadores NUNCA pasan campos estándar (eventId, timestamp, sessionId,
 *   userId, schemaVersion, requestId, source): los añade el servicio.
 * - Cola en memoria; se envía por lotes cada 10 s o al llegar a 20 eventos.
 * - `navigator.sendBeacon` al ocultarse la pestaña para no perder la cola.
 * - Hasta 3 reintentos con backoff exponencial (1 s, 2 s, 4 s); luego se descarta.
 * - Telemetría nunca debe romper la app: todo el servicio es a prueba de fallos.
 */
import { getAccessToken } from "@/lib/api-client";
import { EVENT_ALLOWLISTS, SCHEMA_VERSION } from "@/services/telemetry-schema";

export const FLUSH_INTERVAL_MS = 10_000;
export const MAX_BATCH_SIZE = 20;
export const MAX_RETRIES = 3;
export const BASE_BACKOFF_MS = 1_000;
/** Tope de la cola en memoria si el endpoint está caído (evita fugas). */
const MAX_QUEUE_SIZE = 500;

export type TelemetryProperties = Record<string, unknown>;

interface QueuedEvent {
  eventId: string;
  timestamp: string;
  sessionId: string;
  userId: string;
  event_type: string;
  schemaVersion: string;
  requestId: string;
  source: "frontend";
  properties: TelemetryProperties;
}

const SESSION_KEY = "brasaland_telemetry_session";

let queue: QueuedEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let sessionId: string | null = null;
let listenersInstalled = false;

function endpoint(): string | undefined {
  // Acceso literal: Next.js sustituye NEXT_PUBLIC_* en tiempo de build.
  return process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT || undefined;
}

function uuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback para contextos no seguros (http no-localhost).
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** Genera un sessionId nuevo. Llamar al iniciar sesión (login correcto). */
export function startTelemetrySession(): string {
  sessionId = uuid();
  try {
    window.sessionStorage.setItem(SESSION_KEY, sessionId);
  } catch {
    // sessionStorage no disponible: el id vive solo en memoria.
  }
  return sessionId;
}

/** Cierra la sesión de telemetría (logout / sesión expirada). */
export function endTelemetrySession(): void {
  sessionId = null;
  try {
    window.sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // ignorar
  }
}

function currentSessionId(): string {
  if (sessionId) return sessionId;
  try {
    const stored = window.sessionStorage.getItem(SESSION_KEY);
    if (stored) {
      sessionId = stored;
      return stored;
    }
  } catch {
    // ignorar
  }
  // Evento previo al login (p. ej. login_failed): sesión anónima efímera.
  return startTelemetrySession();
}

/** userId = `sub` del JWT de la sesión autenticada; `anonymous` si no hay sesión. */
function currentUserId(): string {
  const token = getAccessToken();
  if (!token) return "anonymous";
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const sub = (JSON.parse(json) as { sub?: unknown }).sub;
    return sub === undefined || sub === null ? "anonymous" : String(sub);
  } catch {
    return "anonymous";
  }
}

/** Valida contra la allowlist del plan. Devuelve el motivo del rechazo o null. */
export function validateEvent(eventType: string, properties: TelemetryProperties): string | null {
  const rule = EVENT_ALLOWLISTS[eventType];
  if (!rule) return `event_type desconocido: ${eventType}`;
  const extra = Object.keys(properties).filter((key) => !rule.allowed.includes(key));
  if (extra.length > 0) return `propiedades no permitidas en ${eventType}: ${extra.join(", ")}`;
  const missing = rule.required.filter((key) => properties[key] === undefined);
  if (missing.length > 0) return `faltan propiedades obligatorias en ${eventType}: ${missing.join(", ")}`;
  return null;
}

/** Registra un evento. Nunca lanza ni bloquea: es "fire and forget". */
export function track(eventType: string, properties: TelemetryProperties = {}): void {
  try {
    if (typeof window === "undefined" || !endpoint()) return;
    const problem = validateEvent(eventType, properties);
    if (problem) {
      // En desarrollo se avisa; en producción el evento se descarta en silencio.
      if (process.env.NODE_ENV !== "production") console.warn(`[telemetry] descartado: ${problem}`);
      return;
    }
    installListeners();
    queue.push({
      eventId: uuid(),
      timestamp: new Date().toISOString(),
      sessionId: currentSessionId(),
      userId: currentUserId(),
      event_type: eventType,
      schemaVersion: SCHEMA_VERSION,
      requestId: uuid(),
      source: "frontend",
      properties,
    });
    if (queue.length > MAX_QUEUE_SIZE) queue = queue.slice(-MAX_QUEUE_SIZE);
    if (queue.length >= MAX_BATCH_SIZE) {
      void flush();
    } else {
      scheduleFlush();
    }
  } catch {
    // La telemetría jamás debe romper la app.
  }
}

function scheduleFlush(): void {
  if (flushTimer !== null) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    void flush();
  }, FLUSH_INTERVAL_MS);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function sendWithRetry(url: string, events: QueuedEvent[]): Promise<boolean> {
  const body = JSON.stringify({ events });
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      });
      if (response.ok) return true;
      // 4xx (salvo 408/429) no mejora reintentando: se descarta el lote.
      if (response.status >= 400 && response.status < 500 && response.status !== 408 && response.status !== 429) {
        return false;
      }
    } catch {
      // error de red: se reintenta
    }
    if (attempt < MAX_RETRIES) await sleep(BASE_BACKOFF_MS * 2 ** attempt);
  }
  return false;
}

/** Envía lo que haya en la cola (lotes de hasta 20). */
export async function flush(): Promise<void> {
  const url = endpoint();
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (!url || queue.length === 0) return;
  const batch = queue.splice(0, MAX_BATCH_SIZE);
  await sendWithRetry(url, batch); // si falla tras los reintentos, el lote se descarta
  if (queue.length > 0) {
    if (queue.length >= MAX_BATCH_SIZE) void flush();
    else scheduleFlush();
  }
}

/** Vuelca la cola con sendBeacon (síncrono, sobrevive al cierre de la pestaña). */
export function flushWithBeacon(): void {
  const url = endpoint();
  if (!url || queue.length === 0) return;
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  try {
    while (queue.length > 0) {
      const batch = queue.splice(0, MAX_BATCH_SIZE);
      const blob = new Blob([JSON.stringify({ events: batch })], { type: "application/json" });
      if (typeof navigator.sendBeacon !== "function" || !navigator.sendBeacon(url, blob)) break;
    }
  } catch {
    // ignorar
  }
}

function installListeners(): void {
  if (listenersInstalled || typeof document === "undefined") return;
  listenersInstalled = true;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushWithBeacon();
  });
}

/** Solo para tests: reinicia el estado interno del módulo. */
export function __resetTelemetryForTests(): void {
  queue = [];
  if (flushTimer !== null) clearTimeout(flushTimer);
  flushTimer = null;
  sessionId = null;
  listenersInstalled = false;
}

export function __queueSizeForTests(): number {
  return queue.length;
}
