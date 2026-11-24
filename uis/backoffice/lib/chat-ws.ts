import { API_URL, getAccessToken } from "./api-client";
import { backoffDelay } from "./sse";

// Cliente WebSocket del chat del Manager support agent (`/agent/chat/ws`). Contrato de eventos del BRIEFING (Parte 2); NO comparte
// esquemas con el SSE de las RFPs. Dos piezas: `chatReducer` (estado puro, fácil de probar) y `ChatSocket` (conexión con reconexión).

export type MessageStatus = "streaming" | "completed" | "interrupted" | "failed";
export interface ChatMessage { id: string; role: "user" | "assistant"; text: string; status: MessageStatus; sequence: number }
export interface ChatState {
  sessionId: string;
  messages: ChatMessage[];
  /** Mensaje del asistente que se está escribiendo ahora (su `id` puede ser provisional hasta `generation_completed`/`generation_interrupted`). */
  generatingId: string | null;
  /** Texto con el que el usuario interrumpió; se muestra hasta que el servidor confirma `generation_interrupted`. */
  interruptingWith: string | null;
  hydrated: boolean;
  error: string | null;
}
export interface ServerEvent { event: string; data: Record<string, unknown> }
export type ChatStatus = "connecting" | "live" | "reconnecting" | "closed";

export function initialChatState(sessionId: string): ChatState {
  return { sessionId, messages: [], generatingId: null, interruptingWith: null, hydrated: false, error: null };
}

const str = (value: unknown): string => (typeof value === "string" ? value : "");

function patch(state: ChatState, id: string, change: Partial<ChatMessage>): ChatState {
  return { ...state, messages: state.messages.map((m) => (m.id === id ? { ...m, ...change } : m)) };
}

/** Cierra el mensaje en curso con el id definitivo del servidor. Si aún no se había mostrado ningún token, el mensaje se crea vacío. */
function finishGenerating(state: ChatState, messageId: string, status: MessageStatus): ChatState {
  const current = state.generatingId;
  if (current === null) {
    const known = state.messages.some((m) => m.id === messageId);
    const messages = known ? state.messages.map((m) => (m.id === messageId ? { ...m, status } : m))
      : [...state.messages, { id: messageId, role: "assistant" as const, text: "", status, sequence: 0 }];
    return { ...state, messages, interruptingWith: null };
  }
  return { ...patch(state, current, { id: messageId, status }), generatingId: null, interruptingWith: null };
}

export function chatReducer(state: ChatState, message: ServerEvent): ChatState {
  const data = message.data ?? {};
  switch (message.event) {
    case "session_snapshot": { // al (re)conectar: el servidor manda el historial ANTES de cualquier token nuevo
      const raw = Array.isArray(data.messages) ? (data.messages as Array<Record<string, unknown>>) : [];
      const messages: ChatMessage[] = raw.map((m) => ({
        id: str(m.message_id), role: m.role === "user" ? "user" : "assistant", text: str(m.text),
        status: (str(m.status) || "completed") as MessageStatus, sequence: typeof m.sequence === "number" ? m.sequence : 0,
      }));
      const live = [...messages].reverse().find((m) => m.role === "assistant" && m.status === "streaming");
      return { ...state, messages, generatingId: live?.id ?? null, interruptingWith: null, hydrated: true, error: null };
    }
    case "user_message":
      return { ...state, messages: [...state.messages, { id: `user-${state.messages.length}`, role: "user", text: str(data.text), status: "completed", sequence: 0 }] };
    case "token_chunk": {
      const sequence = typeof data.sequence === "number" ? data.sequence : 0;
      const token = str(data.token);
      if (state.generatingId === null) {
        const id = `pending-${state.messages.length}`;
        return { ...state, generatingId: id, messages: [...state.messages, { id, role: "assistant", text: token, status: "streaming", sequence }] };
      }
      const current = state.messages.find((m) => m.id === state.generatingId);
      if (current && sequence <= current.sequence) return state; // ya aplicado (p. ej. cubierto por el snapshot)
      return patch(state, state.generatingId, { text: (current?.text ?? "") + token, sequence });
    }
    case "interrupt_requested":
      return { ...state, interruptingWith: str(data.new_input) };
    case "generation_interrupted":
      return finishGenerating(state, str(data.message_id), "interrupted"); // el parcial se queda a la vista; la respuesta nueva es OTRO mensaje
    case "generation_completed":
      return finishGenerating(state, str(data.message_id), "completed");
    case "generation_failed":
      return finishGenerating(state, str(data.message_id), "failed");
    case "message_corrected": { // los guardrails validan el texto completo al final: sustituye lo mostrado por el texto validado
      const id = state.generatingId ?? str(data.message_id);
      return patch(state, id, { text: str(data.text) });
    }
    case "error":
      return { ...state, error: str(data.message) || "Error del chat." };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------------------------------------------- conexión
export function chatUrl(sessionId: string, options: { token: string | null; locationId?: string | null; apiUrl?: string }): string {
  const base = (options.apiUrl ?? API_URL).replace(/^http/, "ws");
  const query = new URLSearchParams({ session_id: sessionId });
  if (options.token) query.set("token", options.token);
  if (options.locationId) query.set("location_id", options.locationId);
  return `${base}/agent/chat/ws?${query.toString()}`;
}

/** Cierres que reintentar no arregla: petición mal formada, no autenticado, sesión de otro usuario. */
export const FATAL_CLOSE_CODES = [4400, 4401, 4403];

export interface ChatSocketOptions {
  sessionId: string;
  locationId?: string | null;
  onEvent: (event: ServerEvent) => void;
  onStatus?: (status: ChatStatus, info?: { attempt: number; delayMs?: number; code?: number }) => void;
  /** Sin ningún snapshot tras tantos intentos seguidos se da por perdida la conexión (p. ej. handshake rechazado). */
  maxAttempts?: number;
  baseMs?: number;
  maxMs?: number;
  // Inyectables para las pruebas:
  createSocket?: (url: string) => WebSocket;
  getToken?: () => string | null;
  random?: () => number;
  sleep?: (ms: number) => Promise<void>;
}

export interface ChatConnection {
  send: (event: string, data: Record<string, unknown>) => boolean;
  close: () => void;
}

export function connectChat(options: ChatSocketOptions): ChatConnection {
  const create = options.createSocket ?? ((url: string) => new WebSocket(url));
  const getToken = options.getToken ?? getAccessToken;
  let socket: WebSocket | null = null;
  let closed = false;
  let attempt = 0;
  let wake: (() => void) | null = null;

  const wait = (ms: number): Promise<void> => {
    if (options.sleep) return options.sleep(ms);
    return new Promise((resolve) => {
      const timer = setTimeout(() => { wake = null; resolve(); }, ms);
      wake = () => { clearTimeout(timer); wake = null; resolve(); };
    });
  };

  async function run(): Promise<void> {
    while (!closed) {
      options.onStatus?.(attempt === 0 ? "connecting" : "reconnecting", { attempt });
      // Mismo `session_id` en cada intento: el servidor responde con `session_snapshot` y el estado se rehidrata antes de aceptar tokens nuevos.
      const code = await new Promise<number>((resolve) => {
        const ws = create(chatUrl(options.sessionId, { token: getToken(), locationId: options.locationId }));
        socket = ws;
        ws.onmessage = (message) => {
          let parsed: ServerEvent;
          try { parsed = JSON.parse(String(message.data)) as ServerEvent; } catch { return; }
          if (parsed.event === "session_snapshot") { attempt = 0; options.onStatus?.("live", { attempt }); }
          options.onEvent(parsed);
        };
        ws.onclose = (event) => resolve(event.code);
        ws.onerror = () => { /* el cierre posterior informa del motivo */ };
      });
      socket = null;
      if (closed) return;
      if (FATAL_CLOSE_CODES.includes(code) || attempt + 1 >= (options.maxAttempts ?? 8)) {
        options.onStatus?.("closed", { attempt, code });
        return;
      }
      const delayMs = backoffDelay(attempt, { baseMs: options.baseMs, maxMs: options.maxMs, random: options.random });
      attempt += 1;
      options.onStatus?.("reconnecting", { attempt, delayMs, code });
      await wait(delayMs);
    }
  }

  const onOnline = () => wake?.();
  if (typeof window !== "undefined") window.addEventListener("online", onOnline);
  void run().finally(() => { if (typeof window !== "undefined") window.removeEventListener("online", onOnline); });

  return {
    send(event, data) {
      if (!socket || socket.readyState !== 1) return false; // 1 = OPEN
      socket.send(JSON.stringify({ event, data }));
      return true;
    },
    close() {
      closed = true;
      socket?.close();
      wake?.();
      options.onStatus?.("closed", { attempt: 0 });
    },
  };
}

/** `session_id` estable por pestaña: sobrevive a una recarga (sessionStorage) para recuperar el historial. */
export function getOrCreateSessionId(storage: Pick<Storage, "getItem" | "setItem"> | null = typeof window === "undefined" ? null : window.sessionStorage): string {
  const KEY = "brasaland_chat_session_id";
  try {
    const existing = storage?.getItem(KEY);
    if (existing && /^[A-Za-z0-9_-]{8,64}$/.test(existing)) return existing;
  } catch { /* almacenamiento no disponible */ }
  const fresh = `chat_${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36)}`;
  try { storage?.setItem(KEY, fresh); } catch { /* idem */ }
  return fresh;
}
