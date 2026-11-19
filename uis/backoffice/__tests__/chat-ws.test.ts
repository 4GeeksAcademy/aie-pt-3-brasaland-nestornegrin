import { chatReducer, chatUrl, connectChat, getOrCreateSessionId, initialChatState, type ChatState, type ServerEvent } from "@/lib/chat-ws";

const S = "chat_0044";
const apply = (events: ServerEvent[], state: ChatState = initialChatState(S)) => events.reduce(chatReducer, state);
const token = (t: string, sequence: number): ServerEvent => ({ event: "token_chunk", data: { session_id: S, token: t, sequence } });

describe("chatReducer: contrato de eventos", () => {
  it("pinta los tokens conforme llegan y cierra con generation_completed", () => {
    const state = apply([
      { event: "session_snapshot", data: { session_id: S, messages: [] } },
      { event: "user_message", data: { session_id: S, text: "hola" } },
      token("Para ", 1), token("Miami", 2),
    ]);
    expect(state.messages.map((m) => [m.role, m.text, m.status])).toEqual([["user", "hola", "completed"], ["assistant", "Para Miami", "streaming"]]);
    const done = chatReducer(state, { event: "generation_completed", data: { session_id: S, message_id: "msg_0091" } });
    expect(done.messages[1]).toMatchObject({ id: "msg_0091", status: "completed" });
    expect(done.generatingId).toBeNull();
  });

  it("interrumpir deja el parcial visible como `interrupted` y la respuesta redirigida es OTRO mensaje", () => {
    const state = apply([
      { event: "user_message", data: { session_id: S, text: "¿Chicago?" } },
      token("Para ", 1), token("Chicago", 2),
      { event: "interrupt_requested", data: { session_id: S, new_input: "espera, pregunté por Miami" } },
      { event: "generation_interrupted", data: { session_id: S, message_id: "msg_0090", status: "interrupted" } },
      { event: "user_message", data: { session_id: S, text: "espera, pregunté por Miami" } },
      token("Miami", 1),
    ]);
    expect(state.messages.map((m) => [m.id, m.text, m.status])).toEqual([
      ["user-0", "¿Chicago?", "completed"],
      ["msg_0090", "Para Chicago", "interrupted"],
      ["user-2", "espera, pregunté por Miami", "completed"],
      ["pending-3", "Miami", "streaming"],
    ]);
    expect(state.interruptingWith).toBeNull();
  });

  it("interrumpir antes del primer token deja un mensaje vacío interrumpido (el servidor lo guardó)", () => {
    const state = apply([{ event: "generation_interrupted", data: { session_id: S, message_id: "msg_0007", status: "interrupted" } }]);
    expect(state.messages).toEqual([{ id: "msg_0007", role: "assistant", text: "", status: "interrupted", sequence: 0 }]);
  });

  it("el snapshot rehidrata el historial y reanuda un mensaje en curso", () => {
    const state = apply([{ event: "session_snapshot", data: { session_id: S, messages: [
      { message_id: "msg_0001", role: "user", text: "hola", status: "completed", sequence: 0 },
      { message_id: "msg_0002", role: "assistant", text: "Para ", status: "streaming", sequence: 1 },
    ] } }, token("Miami", 2)]);
    expect(state.hydrated).toBe(true);
    expect(state.messages[1]).toMatchObject({ id: "msg_0002", text: "Para Miami", status: "streaming" });
  });

  it("ignora tokens ya cubiertos por el snapshot (sequence repetida) y reemplaza el historial al reconectar", () => {
    const snapshot: ServerEvent = { event: "session_snapshot", data: { session_id: S, messages: [
      { message_id: "msg_0002", role: "assistant", text: "Para Miami", status: "streaming", sequence: 2 }] } };
    const state = apply([snapshot, token("Miami", 2)]);
    expect(state.messages[0].text).toBe("Para Miami");
    expect(chatReducer(state, snapshot).messages).toHaveLength(1);
  });

  it("message_corrected sustituye el texto mostrado por el validado por los guardrails", () => {
    const state = apply([token("sin validar", 1), { event: "message_corrected", data: { session_id: S, message_id: "msg_1", text: "validado" } }]);
    expect(state.messages[0].text).toBe("validado");
  });

  it("errores del servidor se exponen y eventos desconocidos se ignoran", () => {
    expect(apply([{ event: "error", data: { code: "read_only", message: "Solo lectura" } }]).error).toBe("Solo lectura");
    const state = initialChatState(S);
    expect(chatReducer(state, { event: "rfp_ticket_created", data: {} })).toBe(state);
  });
});

describe("chatUrl / sesión", () => {
  it("lleva session_id, token y location_id en la URL (ws://)", () => {
    expect(chatUrl(S, { token: "jwt", locationId: "loc_1", apiUrl: "http://localhost:8000" })).toBe("ws://localhost:8000/agent/chat/ws?session_id=chat_0044&token=jwt&location_id=loc_1");
    expect(chatUrl(S, { token: null, apiUrl: "https://api.example.com" })).toBe("wss://api.example.com/agent/chat/ws?session_id=chat_0044");
  });

  it("reutiliza el session_id guardado (recarga) y genera uno válido si no hay", () => {
    const store: Record<string, string> = {};
    const storage = { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v; } };
    const first = getOrCreateSessionId(storage);
    expect(first).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(getOrCreateSessionId(storage)).toBe(first);
  });
});

class FakeSocket {
  static instances: FakeSocket[] = [];
  readyState = 1;
  sent: string[] = [];
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) { FakeSocket.instances.push(this); }
  send(data: string) { this.sent.push(data); }
  close() { this.onclose?.({ code: 1000 }); }
  emit(event: ServerEvent) { this.onmessage?.({ data: JSON.stringify(event) }); }
  drop(code = 1006) { this.onclose?.({ code }); }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("connectChat: reconexión con backoff y el mismo session_id", () => {
  beforeEach(() => { FakeSocket.instances = []; });

  it("tras una caída reconecta con el MISMO session_id tras esperar el backoff y vuelve a recibir el snapshot", async () => {
    const delays: number[] = [];
    const events: ServerEvent[] = [];
    const statuses: string[] = [];
    const chat = connectChat({
      sessionId: S, getToken: () => "jwt", random: () => 1, onEvent: (e) => events.push(e), onStatus: (s) => statuses.push(s),
      createSocket: (url) => new FakeSocket(url) as unknown as WebSocket,
      sleep: async (ms) => { delays.push(ms); },
    });
    await flush();
    FakeSocket.instances[0].emit({ event: "session_snapshot", data: { session_id: S, messages: [] } });
    FakeSocket.instances[0].drop();
    await flush();
    expect(delays).toEqual([1000]);
    expect(FakeSocket.instances).toHaveLength(2);
    expect(new Set(FakeSocket.instances.map((s) => new URL(s.url.replace("ws:", "http:")).searchParams.get("session_id")))).toEqual(new Set([S]));
    FakeSocket.instances[1].emit({ event: "session_snapshot", data: { session_id: S, messages: [{ message_id: "msg_1" }] } });
    expect(events.filter((e) => e.event === "session_snapshot")).toHaveLength(2);
    expect(statuses).toEqual(expect.arrayContaining(["connecting", "live", "reconnecting"]));
    chat.close();
  });

  it("el backoff crece de forma exponencial con cada fallo seguido", async () => {
    const delays: number[] = [];
    connectChat({
      sessionId: S, getToken: () => "jwt", random: () => 1, maxAttempts: 4, onEvent: () => {},
      createSocket: (url) => { const s = new FakeSocket(url); setTimeout(() => s.drop(), 0); return s as unknown as WebSocket; },
      sleep: async (ms) => { delays.push(ms); },
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(delays).toEqual([1000, 2000, 4000]);
  });

  it("un cierre por autenticación (4401) no se reintenta", async () => {
    const statuses: string[] = [];
    connectChat({
      sessionId: S, getToken: () => "malo", onEvent: () => {}, onStatus: (s) => statuses.push(s),
      createSocket: (url) => { const s = new FakeSocket(url); setTimeout(() => s.drop(4401), 0); return s as unknown as WebSocket; },
      sleep: async () => {},
    });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(FakeSocket.instances).toHaveLength(1);
    expect(statuses.at(-1)).toBe("closed");
  });

  it("send serializa {event, data} y devuelve false si no hay conexión abierta", async () => {
    const chat = connectChat({ sessionId: S, getToken: () => "jwt", onEvent: () => {}, createSocket: (url) => new FakeSocket(url) as unknown as WebSocket, sleep: async () => {} });
    await flush();
    expect(chat.send("user_message", { text: "hola" })).toBe(true);
    expect(JSON.parse(FakeSocket.instances[0].sent[0])).toEqual({ event: "user_message", data: { text: "hola" } });
    FakeSocket.instances[0].readyState = 3;
    expect(chat.send("user_message", { text: "x" })).toBe(false);
    chat.close();
  });
});
