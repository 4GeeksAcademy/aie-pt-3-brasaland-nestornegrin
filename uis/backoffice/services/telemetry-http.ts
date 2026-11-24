/**
 * Observación de peticiones HTTP para telemetría (api_latency_recorded,
 * network_request_failed). No hace ninguna petición: solo mide y llama a `track`.
 * Lo usan `apiFetch` (lib/api-client.ts) e `inventoryFetch` (lib/inventory.ts).
 */
import { track } from "@/services/telemetry";

const METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;
type Method = (typeof METHODS)[number];

const SLOW_MS = 500;
const SAMPLE_RATE = 0.05;

/** `/api/incidents/12/status?x=1` → `/api/incidents/{id}/status` (nunca la ruta real ni la query). */
export function routeTemplate(path: string): string {
  const clean = path.split(/[?#]/)[0];
  const template = clean
    .split("/")
    .map((segment) => (/^\d+$/.test(segment) ? "{id}" : segment))
    .join("/");
  return /^\/[A-Za-z0-9_/{}.-]*$/.test(template) && template.length <= 96 ? template : "/unknown";
}

function normalizeMethod(method?: string): Method {
  const upper = (method ?? "GET").toUpperCase();
  return (METHODS as readonly string[]).includes(upper) ? (upper as Method) : "GET";
}

function statusClass(status: number): "2xx" | "3xx" | "4xx" | "5xx" {
  if (status >= 500) return "5xx";
  if (status >= 400) return "4xx";
  if (status >= 300) return "3xx";
  return "2xx";
}

/** Tiempo de pared medido en el cliente (incluye red). Muestreo: 100 % lentas o 5xx, 5 % el resto. */
export function observeResponse(init: RequestInit | undefined, path: string, startedAt: number, response: Response): void {
  // No medir el propio endpoint de telemetría ni rutas desconocidas.
  const durationMs = Math.max(0, Math.round(performance.now() - startedAt));
  const cls = statusClass(response.status);
  const always = durationMs > SLOW_MS || cls === "5xx";
  if (!always && Math.random() >= SAMPLE_RATE) return;
  const cacheHeader = response.headers?.get?.("X-Cache")?.toLowerCase();
  const bytes = Number(response.headers?.get?.("Content-Length"));
  track("api_latency_recorded", {
    method: normalizeMethod(init?.method),
    routeTemplate: routeTemplate(path),
    statusClass: cls,
    durationMs,
    sampleRate: always ? 1 : SAMPLE_RATE,
    ...(cacheHeader === "hit" || cacheHeader === "miss" ? { cache: cacheHeader } : {}),
    ...(Number.isFinite(bytes) && bytes > 0 ? { responseBytes: Math.round(bytes) } : {}),
  });
}

/** fetch rechazó la promesa: sin respuesta (red caída, CORS, API apagada). */
export function observeNetworkFailure(init: RequestInit | undefined, path: string, startedAt: number, error: unknown): void {
  const timeout = error instanceof DOMException && error.name === "TimeoutError";
  track("network_request_failed", {
    method: normalizeMethod(init?.method),
    routeTemplate: routeTemplate(path),
    errorKind: timeout ? "timeout" : "network",
    online: typeof navigator === "undefined" ? true : navigator.onLine,
    elapsedMs: Math.max(0, Math.round(performance.now() - startedAt)),
  });
}
