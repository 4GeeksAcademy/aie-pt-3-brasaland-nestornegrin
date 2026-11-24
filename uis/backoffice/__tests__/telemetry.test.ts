/** @jest-environment jsdom */
import {
  __queueSizeForTests,
  __resetTelemetryForTests,
  flush,
  flushWithBeacon,
  startTelemetrySession,
  track,
  validateEvent,
  FLUSH_INTERVAL_MS,
} from "@/services/telemetry";

const URL = "http://localhost:8000/telemetry/events";

function jwt(sub: string) {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "");
  return `${b64({ alg: "HS256" })}.${b64({ sub, exp: 9999999999 })}.sig`;
}

const incident = { incidentId: 1, category: "service", origin: "customer", branch: "central" };

describe("TelemetryService", () => {
  let fetchMock: jest.Mock;

  beforeEach(() => {
    jest.useFakeTimers();
    process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT = URL;
    __resetTelemetryForTests();
    window.localStorage.clear();
    window.sessionStorage.clear();
    fetchMock = jest.fn().mockResolvedValue({ ok: true, status: 200 });
    global.fetch = fetchMock as unknown as typeof fetch;
    jest.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it("agrupa y envía tras 10 s con los campos estándar añadidos", async () => {
    window.localStorage.setItem("brasaland_access_token", jwt("42"));
    const session = startTelemetrySession();
    track("incident_created", incident);
    expect(fetchMock).not.toHaveBeenCalled();

    await jest.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(URL);
    const [event] = JSON.parse(init.body).events;
    expect(event).toMatchObject({
      event_type: "incident_created",
      sessionId: session,
      userId: "42",
      source: "frontend",
      properties: incident,
    });
    expect(event.eventId).toMatch(/^[0-9a-f-]{36}$/);
    expect(event.requestId).toMatch(/^[0-9a-f-]{36}$/);
    expect(event.timestamp).toMatch(/^\d{4}-\d\d-\d\dT.*Z$/);
    expect(event.schemaVersion).toMatch(/^\d+\.\d+\.\d+$/);
  });

  it("usa userId anonymous sin sesión autenticada", async () => {
    track("incident_created", incident);
    await flush();
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).events[0].userId).toBe("anonymous");
  });

  it("envía de inmediato al llegar a 20 eventos", async () => {
    for (let i = 0; i < 20; i += 1) track("incident_created", incident);
    await Promise.resolve();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).events).toHaveLength(20);
  });

  it("reintenta 3 veces con backoff exponencial y luego descarta", async () => {
    fetchMock.mockRejectedValue(new Error("network"));
    track("incident_created", incident);
    const done = flush();
    await jest.advanceTimersByTimeAsync(1_000 + 2_000 + 4_000);
    await done;
    expect(fetchMock).toHaveBeenCalledTimes(4); // 1 intento + 3 reintentos
    expect(__queueSizeForTests()).toBe(0); // descartado
  });

  it("no reintenta ante un 4xx (salvo 408/429)", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 400 });
    track("incident_created", incident);
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("vuelca la cola con sendBeacon cuando la pestaña se oculta", () => {
    const beacon = jest.fn().mockReturnValue(true);
    Object.defineProperty(navigator, "sendBeacon", { value: beacon, configurable: true });
    track("incident_created", incident);
    track("incident_created", incident);
    flushWithBeacon();
    expect(beacon).toHaveBeenCalledTimes(1);
    expect(beacon.mock.calls[0][0]).toBe(URL);
    expect(__queueSizeForTests()).toBe(0);
  });

  it("descarta eventos fuera del plan (tipo desconocido, propiedad extra, falta obligatoria)", async () => {
    track("evento_inventado", {});
    track("incident_created", { ...incident, email: "a@b.com" });
    track("incident_created", { incidentId: 1 });
    expect(__queueSizeForTests()).toBe(0);
    expect(validateEvent("incident_created", incident)).toBeNull();
  });

  it("no hace nada si NEXT_PUBLIC_TELEMETRY_ENDPOINT no está definido", () => {
    delete process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT;
    track("incident_created", incident);
    expect(__queueSizeForTests()).toBe(0);
  });
});
