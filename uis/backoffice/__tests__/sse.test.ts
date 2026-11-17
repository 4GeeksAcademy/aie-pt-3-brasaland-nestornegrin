/** @jest-environment node */
import { lastKnownTicketId, mergeCreatedTicket, parseTicketCreated, type TicketCreatedEvent, type TicketSummary } from "../lib/rfp";
import { backoffDelay, connectSse, SseParser, type SseMessage, type SseStatus } from "../lib/sse";

const created = (id: number): TicketCreatedEvent => ({
  ticket_id: id, rfp_id: `RFP-${String(id).padStart(5, "0")}`, status: "analizando", requires_processing: true,
  original_filename: `rfp-${id}.pdf`, created_at: "2026-11-17T10:00:00+00:00",
});
const frame = (id: number) => `id: ${id}\nevent: rfp_ticket_created\ndata: ${JSON.stringify(created(id))}\n\n`;
const encoder = new TextEncoder();

/** Respuesta con cuerpo en streaming controlable: `push` envía trozos, `end` cierra limpio, `fail` simula un corte de red. */
function streamResponse(status = 200) {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start: (c) => { controller = c; } });
  return {
    response: { status, ok: status >= 200 && status < 300, body } as unknown as Response,
    push: (text: string) => controller.enqueue(encoder.encode(text)),
    end: () => controller.close(),
    fail: () => controller.error(new Error("network down")),
  };
}
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); await new Promise((r) => setTimeout(r, 0)); };

describe("SseParser", () => {
  test("evento nombrado con id y data JSON", () => {
    const [m] = new SseParser().feed(frame(7));
    expect(m).toMatchObject({ event: "rfp_ticket_created", id: "7" });
    expect(JSON.parse(m.data)).toMatchObject({ ticket_id: 7, status: "analizando" });
  });
  test("aguanta trozos partidos en cualquier punto y CRLF", () => {
    const parser = new SseParser();
    const text = frame(3).replace(/\n/g, "\r\n");
    const out: SseMessage[] = [];
    for (const ch of text) out.push(...parser.feed(ch));
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe("3");
  });
  test("ignora comentarios keep-alive y registra retry", () => {
    const parser = new SseParser();
    expect(parser.feed(": keep-alive\n\nretry: 3000\n\n")).toEqual([]);
    expect(parser.retry).toBe(3000);
  });
  test("data multilínea y evento sin nombre es `message`", () => {
    expect(new SseParser().feed("data: a\ndata: b\n\n")).toEqual([{ event: "message", data: "a\nb" }]);
  });
});

describe("backoffDelay", () => {
  test("crece de forma exponencial, con tope y jitter acotado", () => {
    const top = (n: number) => backoffDelay(n, { random: () => 1 });
    const bottom = (n: number) => backoffDelay(n, { random: () => 0 });
    expect([0, 1, 2, 3].map(top)).toEqual([1000, 2000, 4000, 8000]);
    expect(top(20)).toBe(30000);
    expect(bottom(3)).toBe(4000);
    expect(backoffDelay(2, { baseMs: 500, maxMs: 1500, random: () => 1 })).toBe(1500);
  });
});

describe("mergeCreatedTicket / parseTicketCreated", () => {
  const row = (id: number): TicketSummary => ({ ticket_id: id, rfp_id: "X", status: "analisis_completo", processing: "idle", original_filename: "a.pdf",
    client_name: "Cliente", current_node: null, created_at: "t", updated_at: "t" });
  test("inserta el ticket nuevo arriba, sin tocar el resto", () => {
    const list = [row(2), row(1)];
    const merged = mergeCreatedTicket(list, created(3));
    expect(merged.map((t) => t.ticket_id)).toEqual([3, 2, 1]);
    expect(merged[0]).toMatchObject({ status: "analizando", processing: "running", rfp_id: null });
    expect(merged[1]).toBe(list[0]);
  });
  test("un ticket ya conocido no se duplica ni se pisa (misma lista)", () => {
    const list = [row(2), row(1)];
    expect(mergeCreatedTicket(list, created(2))).toBe(list);
  });
  test("lastKnownTicketId = mayor id; null si no hay tickets", () => {
    expect(lastKnownTicketId([row(2), row(9), row(4)])).toBe("9");
    expect(lastKnownTicketId([])).toBeNull();
  });
  test("solo acepta rfp_ticket_created con payload válido", () => {
    expect(parseTicketCreated({ event: "message", data: "{}" })).toBeNull();
    expect(parseTicketCreated({ event: "rfp_ticket_created", data: "no json" })).toBeNull();
    expect(parseTicketCreated({ event: "rfp_ticket_created", data: JSON.stringify(created(5)) })?.ticket_id).toBe(5);
  });
});

describe("connectSse: reconexión y recuperación", () => {
  test("envía Last-Event-ID, reconecta con backoff creciente y no duplica tras el corte", async () => {
    const streams = [streamResponse(), streamResponse(), streamResponse()];
    const requests: RequestInit[] = [];
    const delays: number[] = [];
    const statuses: SseStatus[] = [];
    const messages: SseMessage[] = [];
    let call = 0;
    let known = "5"; // la lista cargada llega hasta el ticket 5
    const connection = connectSse({
      path: "/rfp/events",
      request: async (_p, init) => { requests.push(init); return streams[call++].response; },
      sleep: async (ms) => { delays.push(ms); },
      random: () => 1,
      getLastEventId: () => known,
      onStatus: (s) => statuses.push(s),
      onMessage: (m) => messages.push(m),
    });

    await flush();
    expect((requests[0].headers as Record<string, string>)["Last-Event-ID"]).toBe("5");
    streams[0].push(": keep-alive\n\n" + frame(6));
    await flush();
    known = "6";
    streams[0].fail(); // se corta la red
    await flush();

    // 2.ª conexión: cae otra vez sin llegar a emitir nada → el backoff crece (1 s → 2 s)
    streams[1].fail();
    await flush();
    expect(delays.slice(0, 2)).toEqual([1000, 2000]);

    // 3.ª conexión: el servidor repite lo que ya tenía y envía lo que se perdió durante el corte
    streams[2].push(frame(6) + frame(7) + frame(8));
    await flush();
    expect((requests[2].headers as Record<string, string>)["Last-Event-ID"]).toBe("6");
    expect(statuses).toContain("reconnecting");
    expect(statuses).toContain("live");

    // La capa de UI deduplica por ticket_id: 6 ya estaba, solo 7 y 8 son nuevos.
    let list: TicketSummary[] = [];
    for (const m of messages) { const ev = parseTicketCreated(m); if (ev) list = mergeCreatedTicket(list, ev); }
    expect(list.map((t) => t.ticket_id)).toEqual([8, 7, 6]);
    expect(list).toHaveLength(new Set(list.map((t) => t.ticket_id)).size);

    connection.close();
  });

  test("tras una conexión estable el backoff vuelve a empezar", async () => {
    const first = streamResponse(); const second = streamResponse(); const third = streamResponse();
    const queue = [first, second, third]; const delays: number[] = [];
    const connection = connectSse({ path: "/x", request: async () => queue.shift()!.response, sleep: async (ms) => { delays.push(ms); }, random: () => 1, onMessage: () => {} });
    await flush();
    first.push(": keep-alive\n\n"); await flush(); first.end(); await flush();
    second.push(": keep-alive\n\n"); await flush(); second.end(); await flush();
    expect(delays).toEqual([1000, 1000]);
    connection.close();
  });

  test("401 no se reintenta en bucle", async () => {
    const calls: number[] = []; const statuses: SseStatus[] = [];
    connectSse({ path: "/x", request: async () => { calls.push(1); return streamResponse(401).response; }, sleep: async () => {}, onMessage: () => {}, onStatus: (s) => statuses.push(s) });
    await flush();
    expect(calls).toHaveLength(1);
    expect(statuses.at(-1)).toBe("closed");
  });

  test("close() aborta la petición y deja de reconectar", async () => {
    let signal: AbortSignal | undefined; let calls = 0;
    const connection = connectSse({ path: "/x", request: async (_p, init) => { calls++; signal = init.signal as AbortSignal; return streamResponse().response; }, sleep: async () => {}, onMessage: () => {} });
    await flush();
    connection.close();
    await flush();
    expect(signal?.aborted).toBe(true);
    expect(calls).toBe(1);
  });
});
