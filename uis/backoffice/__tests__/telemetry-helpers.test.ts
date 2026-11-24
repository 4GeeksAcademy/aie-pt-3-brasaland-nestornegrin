/** @jest-environment jsdom */
import { __queueSizeForTests, __resetTelemetryForTests, flush } from "@/services/telemetry";
import { fingerprint, topFrameOf, captureError } from "@/services/telemetry-errors";
import { FlowTracker, IDLE_TIMEOUT_MS, getActiveFlow } from "@/services/telemetry-flow";
import { routeTemplate } from "@/services/telemetry-http";
import { sectionForPath } from "@/services/telemetry-sections";

let sent: Array<{ event_type: string; properties: Record<string, unknown> }> = [];

beforeEach(() => {
  jest.useFakeTimers();
  process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT = "http://localhost:8000/telemetry/events";
  __resetTelemetryForTests();
  sent = [];
  global.fetch = jest.fn(async (_url: unknown, init?: RequestInit) => {
    sent.push(...JSON.parse(String(init?.body)).events);
    return { ok: true, status: 200 } as Response;
  }) as unknown as typeof fetch;
});
afterEach(() => jest.useRealTimers());

describe("routeTemplate", () => {
  it("sustituye ids y elimina la query", () => {
    expect(routeTemplate("/api/incidents/12/status?x=1")).toBe("/api/incidents/{id}/status");
    expect(routeTemplate("/inventory/products/7")).toBe("/inventory/products/{id}");
  });
  it("rutas no válidas → /unknown", () => {
    expect(routeTemplate("/a b")).toBe("/unknown");
  });
});

describe("sectionForPath", () => {
  it("mapea rutas a secciones", () => {
    expect(sectionForPath("/")).toBe("dashboard");
    expect(sectionForPath("/inventory/orders/outbound/")).toBe("inventory_outbound");
    expect(sectionForPath("/nope")).toBeNull();
  });
});

describe("errores", () => {
  it("fingerprint es estable y de 16 hex", () => {
    expect(fingerprint("a")).toMatch(/^[0-9a-f]{16}$/);
    expect(fingerprint("a")).toBe(fingerprint("a"));
    expect(fingerprint("a")).not.toBe(fingerprint("b"));
  });
  it("topFrame quita dominio y query", () => {
    const stack = "Error: x\n    at f (http://localhost:3000/_next/static/chunks/app.js?v=1:10:5)";
    expect(topFrameOf(stack)).toBe("/_next/static/chunks/app.js:10");
  });
  it("no envía el mensaje del error", async () => {
    captureError("window_error", new TypeError("contiene jmv@x.com"));
    await flush();
    expect(JSON.stringify(sent)).not.toContain("jmv@x.com");
    expect(sent[0].event_type).toBe("frontend_error_captured");
  });
});

describe("FlowTracker", () => {
  it("emite flow_started en la 1ª modificación y flow_completed al enviar", async () => {
    const flow = new FlowTracker("incident_report", "incident_new");
    expect(__queueSizeForTests()).toBe(0); // abrir la página no emite nada
    flow.touch("title");
    flow.touch("title");
    expect(getActiveFlow()).toEqual({ flow: "incident_report", dirty: true });
    flow.submitAttempt(false);
    flow.submitAttempt(true);
    await flush();
    expect(sent.map((e) => e.event_type)).toEqual(["flow_started", "flow_completed"]);
    expect(sent[1].properties.submitAttempts).toBe(2);
    expect(getActiveFlow()).toBeNull();
  });

  it("emite flow_abandoned solo si se modificó y no se completó", async () => {
    const untouched = new FlowTracker("registration", "register");
    untouched.abandon("navigation_away");
    expect(__queueSizeForTests()).toBe(0);

    const flow = new FlowTracker("registration", "register");
    flow.touch("email");
    flow.touch("name");
    flow.submitAttempt(false);
    flow.abandon("navigation_away");
    await flush();
    const abandoned = sent.find((e) => e.event_type === "flow_abandoned");
    expect(abandoned?.properties).toMatchObject({ lastStep: "submit_rejected", fieldsTouchedCount: 2, hadSubmitError: true, exitTrigger: "navigation_away" });
  });

  it("abandona por inactividad tras 10 minutos", async () => {
    const flow = new FlowTracker("password_change", "account_password");
    flow.touch("x");
    jest.advanceTimersByTime(IDLE_TIMEOUT_MS);
    await flush();
    expect(sent.map((e) => e.event_type)).toContain("flow_abandoned");
    expect(sent.find((e) => e.event_type === "flow_abandoned")?.properties.exitTrigger).toBe("idle_timeout");
  });
});
