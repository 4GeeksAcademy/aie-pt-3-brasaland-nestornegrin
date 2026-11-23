import { apiFetch } from "./api-client";

// Cliente SSE sobre `fetch` + `ReadableStream`. No usa `EventSource`: no permite cabeceras propias, y el endpoint exige el JWT
// en `Authorization: Bearer …` (el mismo que el resto de la API del backoffice).

export interface SseMessage { event: string; data: string; id?: string }
export type SseStatus = "connecting" | "live" | "reconnecting" | "closed";

/** Analiza el flujo `text/event-stream` por trozos: soporta líneas partidas entre trozos, CRLF, comentarios (`: keep-alive`) y `data:` multilínea. */
export class SseParser {
  /** Espera de reconexión que sugiere el servidor con `retry:` (ms), si la ha enviado. */
  retry: number | undefined;
  private buffer = "";
  private event = "";
  private data: string[] = [];
  private id: string | undefined;

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    const out: SseMessage[] = [];
    for (;;) {
      const match = /\r\n|\n|\r/.exec(this.buffer);
      if (!match) break;
      if (match[0] === "\r" && match.index === this.buffer.length - 1) break; // un «\r» al final puede ser la mitad de un «\r\n»
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      this.line(line, out);
    }
    return out;
  }

  private line(line: string, out: SseMessage[]): void {
    if (line === "") { // línea en blanco: el evento está completo
      if (this.data.length > 0) out.push({ event: this.event || "message", data: this.data.join("\n"), ...(this.id !== undefined ? { id: this.id } : {}) });
      this.event = ""; this.data = []; this.id = undefined;
      return;
    }
    if (line.startsWith(":")) return; // comentario / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    else if (field === "id" && !value.includes("\0")) this.id = value;
    else if (field === "retry" && /^\d+$/.test(value)) this.retry = Number(value);
  }
}

/** Espera antes de reintentar: exponencial con tope y «jitter» parcial para que varios clientes no reconecten a la vez. */
export function backoffDelay(attempt: number, options: { baseMs?: number; maxMs?: number; random?: () => number } = {}): number {
  const base = options.baseMs ?? 1000;
  const max = options.maxMs ?? 30000;
  const random = options.random ?? Math.random;
  const ceiling = Math.min(max, base * 2 ** attempt);
  return Math.round(ceiling / 2 + random() * (ceiling / 2));
}

export interface SseOptions {
  path: string;
  onMessage: (message: SseMessage) => void;
  onStatus?: (status: SseStatus, info?: { attempt: number; delayMs?: number }) => void;
  /** Último id que la aplicación ya tiene (p. ej. el mayor `ticket_id` de la lista). Se envía como `Last-Event-ID` al (re)conectar. */
  getLastEventId?: () => string | null;
  /** Sin ningún byte (ni siquiera un keep-alive) durante este tiempo se da la conexión por muerta y se reconecta. */
  idleTimeoutMs?: number;
  baseMs?: number;
  maxMs?: number;
  // Inyectables para las pruebas:
  request?: (path: string, init: RequestInit) => Promise<Response>;
  random?: () => number;
  sleep?: (ms: number) => Promise<void>;
}

export interface SseConnection {
  close: () => void;
  /** Reconecta ya, saltándose la espera del backoff (p. ej. cuando el navegador vuelve a estar online). */
  reconnectNow: () => void;
}

export function connectSse(options: SseOptions): SseConnection {
  const request = options.request ?? ((path, init) => apiFetch(path, init));
  let closed = false;
  let controller: AbortController | null = null;
  let wake: (() => void) | null = null;
  let lastSeen: string | null = null;

  const wait = (ms: number): Promise<void> => {
    if (options.sleep) return options.sleep(ms);
    return new Promise((resolve) => {
      const timer = setTimeout(() => { wake = null; resolve(); }, ms);
      wake = () => { clearTimeout(timer); wake = null; resolve(); };
    });
  };

  async function run(): Promise<void> {
    let attempt = 0;
    let baseMs = options.baseMs;
    while (!closed) {
      options.onStatus?.(attempt === 0 ? "connecting" : "reconnecting", { attempt });
      const current = new AbortController();
      controller = current;
      let idleTimer: ReturnType<typeof setTimeout> | undefined;
      const arm = () => {
        clearTimeout(idleTimer);
        if (options.idleTimeoutMs) idleTimer = setTimeout(() => current.abort(), options.idleTimeoutMs);
      };
      try {
        const headers: Record<string, string> = { Accept: "text/event-stream" };
        const lastId = options.getLastEventId?.() ?? lastSeen;
        if (lastId) headers["Last-Event-ID"] = lastId;
        arm();
        const response = await request(options.path, { headers, signal: current.signal, cache: "no-store" });
        if ([401, 403, 404].includes(response.status)) { // reintentar no arregla un permiso o una ruta; apiFetch ya llevó al login en 401
          options.onStatus?.("closed", { attempt });
          return;
        }
        if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const parser = new SseParser();
        let first = true;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          arm();
          if (first) { first = false; attempt = 0; options.onStatus?.("live", { attempt }); }
          for (const message of parser.feed(decoder.decode(value, { stream: true }))) {
            if (message.id) lastSeen = message.id;
            options.onMessage(message);
          }
          if (parser.retry !== undefined) baseMs = parser.retry;
        }
      } catch {
        // Red caída, abortada por inactividad o error del servidor: se reintenta abajo.
      } finally {
        clearTimeout(idleTimer);
      }
      if (closed) return;
      const delayMs = backoffDelay(attempt, { baseMs, maxMs: options.maxMs, random: options.random });
      attempt += 1;
      options.onStatus?.("reconnecting", { attempt, delayMs });
      await wait(delayMs);
    }
  }

  const onOnline = () => wake?.();
  if (typeof window !== "undefined") window.addEventListener("online", onOnline);
  void run().finally(() => { if (typeof window !== "undefined") window.removeEventListener("online", onOnline); });

  return {
    close() {
      closed = true;
      controller?.abort();
      wake?.();
      options.onStatus?.("closed", { attempt: 0 });
    },
    reconnectNow() {
      controller?.abort(); // corta una conexión «colgada»; si ya estaba esperando, `wake` salta el backoff
      wake?.();
    },
  };
}
